import json
import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .face_pipeline import detect_and_embed
from .forms import StudentForm
from .models import Embedding, Student, StudentPhoto
from .qr_utils import create_or_update_qr, generate_qr_png
from apps.audit.utils import audit

logger = logging.getLogger(__name__)


@login_required
def student_list(request):
    qs = Student.objects.all()
    subject_id = request.GET.get('subject')
    status = request.GET.get('status', 'ACTIVE')
    search = request.GET.get('search', '')
    if subject_id:
        qs = qs.filter(enrolled_subjects__id=subject_id)
    if status:
        qs = qs.filter(enrollment_status=status)
    if search:
        qs = qs.filter(full_name__icontains=search)
    return render(request, 'students/list.html', {
        'students': qs,
        'search': search,
        'status': status,
    })


@login_required
def student_create(request):
    if request.method == 'POST':
        form = StudentForm(request.POST)
        if form.is_valid():
            from django.contrib.auth import get_user_model
            User = get_user_model()

            student = form.save(commit=False)
            student.created_by = request.user
            if student.consent_given:
                student.consent_timestamp = timezone.now()
                student.consent_ip = request.META.get('REMOTE_ADDR')
            student.save()
            audit(request, 'STUDENT_REGISTERED', 'Student', str(student.id))

            # Auto-create a linked user account if one doesn't exist yet
            if not student.user:
                roll = (student.university_roll_number or str(student.id)[:8])
                base_username = roll.lower().replace(' ', '_')
                username = base_username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}_{counter}"
                    counter += 1

                new_user = User.objects.create_user(
                    username=username,
                    email=student.email or '',
                    password=username,   # default password = username
                    role='STUDENT',
                    is_active=True,
                    must_change_password=True,
                )
                student.user = new_user
                student.save(update_fields=['user'])
                audit(request, 'USER_AUTO_CREATED', 'User', str(new_user.id),
                      f"Default account created for student {student.full_name} (username: {username})")
                logger.info(f"Auto-created login account '{username}' for student {student.full_name}")

            messages.success(
                request,
                f"Student {student.full_name} registered. "
                f"Login account created (username: {student.user.username}, default password = username). "
                "Now enroll facial data."
            )
            return redirect('student_enroll_face', pk=student.pk)
    else:
        form = StudentForm()
    return render(request, 'students/register.html', {'form': form})


@login_required
def student_detail(request, pk):
    student = get_object_or_404(Student, pk=pk)
    embeddings = student.embeddings.filter(is_active=True)
    photos = student.photos.all().order_by('-uploaded_at')
    return render(request, 'students/detail.html', {
        'student': student,
        'embeddings': embeddings,
        'photos': photos,
    })


@login_required
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if request.method == 'POST':
        form = StudentForm(request.POST, instance=student)
        if form.is_valid():
            form.save()
            audit(request, 'STUDENT_UPDATED', 'Student', str(student.id))
            messages.success(request, f"Student {student.full_name} updated. Proceed to face enrollment.")
            return redirect('student_enroll_face', pk=student.pk)
    else:
        form = StudentForm(instance=student)
    return render(request, 'students/register.html', {
        'form': form, 'title': 'Edit Student Details', 'student': student, 'is_edit': True
    })


@login_required
def student_enroll_face(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if not student.consent_given:
        messages.error(request, "Cannot enroll: student has not given consent.")
        return redirect('student_detail', pk=pk)
    return render(request, 'students/enroll_face.html', {'student': student})


@login_required
@require_POST
def upload_face_frame(request, pk):
    """Receive a single captured frame, extract embedding, store it.
    
    Query param ?overwrite=1 clears all existing active embeddings first
    (used during re-enrollment to replace old face data).
    """
    student = get_object_or_404(Student, pk=pk)
    frame_file = request.FILES.get('frame')
    if not frame_file:
        return JsonResponse({'success': False, 'error': 'No frame provided'}, status=400)

    image_bytes = frame_file.read()
    result = detect_and_embed(image_bytes)

    if not result['success']:
        return JsonResponse({'success': False, 'error': result['error'], 'face_box': result.get('face_box')})

    # Overwrite mode: clear all existing active embeddings before the first new frame
    overwrite = request.GET.get('overwrite') == '1'
    if overwrite:
        deleted_count = student.embeddings.filter(is_active=True).count()
        student.embeddings.filter(is_active=True).delete()
        if deleted_count:
            audit(request, 'EMBEDDINGS_CLEARED', 'Student', str(student.id),
                  f"Overwrite re-enrollment: {deleted_count} embeddings removed")

    # Deduplicate by image hash (skip if we just cleared)
    if not overwrite and Embedding.objects.filter(student=student, source_image_hash=result['image_hash']).exists():
        return JsonResponse({'success': False, 'error': 'DUPLICATE_FRAME'})

    emb = Embedding(
        student=student,
        quality_score=result['quality_score'],
        source_image_hash=result['image_hash'],
        capture_environment=request.POST.get('environment', 'UNKNOWN'),
    )
    emb.set_vector(result['vector'])
    emb.save()

    audit(request, 'EMBEDDING_ADDED', 'Embedding', str(emb.id))

    # Auto-generate / refresh QR after first embedding
    if student.embedding_count == 1:
        create_or_update_qr(student)
        audit(request, 'QR_GENERATED', 'Student', str(student.id))

    return JsonResponse({
        'success': True,
        'embedding_count': student.embedding_count,
        'quality_score': result['quality_score'],
        'face_box': result.get('face_box'),
    })


@login_required
def student_qr(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if not hasattr(student, 'qr_record') or not student.qr_record.is_valid:
        if student.qr_ready:
            create_or_update_qr(student)
        else:
            messages.error(request, "No embeddings yet. Enroll face first.")
            return redirect('student_enroll_face', pk=pk)
    png = generate_qr_png(student.qr_record.token_payload)
    return HttpResponse(png, content_type='image/png')


@login_required
def student_qr_display(request, pk):
    student = get_object_or_404(Student, pk=pk)
    return render(request, 'students/qr_display.html', {'student': student})

@login_required
@require_POST
def student_photo_upload(request, pk):
    student = get_object_or_404(Student, pk=pk)
    photo_file = request.FILES.get('photo')
    if photo_file:
        privacy_consent = request.POST.get('privacy_consent') == 'on'
        is_primary = request.POST.get('is_primary') == 'on'
        
        # If student is uploading, it requires approval and overrides is_primary request initially
        is_approved = True
        if request.user.role == 'STUDENT':
            is_approved = False
            is_primary = False 
            
        if is_primary:
            student.photos.update(is_primary=False)
            
        StudentPhoto.objects.create(
            student=student,
            image=photo_file,
            is_primary=is_primary,
            privacy_consent=privacy_consent,
            is_approved=is_approved
        )
        if not is_approved:
            messages.success(request, "Photo uploaded successfully. It is pending admin approval.")
        else:
            messages.success(request, "Photo uploaded successfully.")
    else:
        messages.error(request, "No file selected.")
        
    return redirect('student_detail', pk=pk)

@login_required
@require_POST
def student_photo_approve(request, pk, photo_id):
    if request.user.role == 'STUDENT':
        return HttpResponseForbidden()
    photo = get_object_or_404(StudentPhoto, id=photo_id, student_id=pk)
    photo.is_approved = True
    # Auto-make primary if it's their only photo or explicitly chosen previously
    if not photo.student.photos.filter(is_primary=True).exists():
        photo.is_primary = True
    photo.save(update_fields=['is_approved', 'is_primary'])
    messages.success(request, "Photo approved successfully.")
    return redirect('student_detail', pk=pk)

@login_required
@require_POST
def student_photo_delete(request, pk, photo_id):
    if request.user.role == 'STUDENT':
        return HttpResponseForbidden()
    photo = get_object_or_404(StudentPhoto, id=photo_id, student_id=pk)
    photo.delete()
    messages.success(request, "Photo deleted successfully.")
    return redirect('student_detail', pk=pk)
