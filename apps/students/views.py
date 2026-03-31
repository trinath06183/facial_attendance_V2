import json
import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
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
    section_id = request.GET.get('section')
    status = request.GET.get('status', 'ACTIVE')
    search = request.GET.get('search', '')
    if section_id:
        qs = qs.filter(section_id=section_id)
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
            student = form.save(commit=False)
            student.created_by = request.user
            if student.consent_given:
                student.consent_timestamp = timezone.now()
                student.consent_ip = request.META.get('REMOTE_ADDR')
            student.save()
            audit(request, 'STUDENT_REGISTERED', 'Student', str(student.id))
            messages.success(request, f"Student {student.full_name} registered. Now enroll facial data.")
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
            messages.success(request, "Student updated.")
            return redirect('student_detail', pk=pk)
    else:
        form = StudentForm(instance=student)
    return render(request, 'students/register.html', {
        'form': form, 'title': 'Edit Student', 'student': student
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
    """Receive a single captured frame, extract embedding, store it."""
    student = get_object_or_404(Student, pk=pk)
    frame_file = request.FILES.get('frame')
    if not frame_file:
        return JsonResponse({'success': False, 'error': 'No frame provided'}, status=400)

    image_bytes = frame_file.read()
    result = detect_and_embed(image_bytes)

    if not result['success']:
        return JsonResponse({'success': False, 'error': result['error']})

    # Deduplicate by image hash
    if Embedding.objects.filter(student=student, source_image_hash=result['image_hash']).exists():
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

    # Auto-generate QR after first embedding
    if student.embedding_count == 1:
        create_or_update_qr(student)
        audit(request, 'QR_GENERATED', 'Student', str(student.id))

    return JsonResponse({
        'success': True,
        'embedding_count': student.embedding_count,
        'quality_score': result['quality_score'],
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
        
        if is_primary:
            student.photos.update(is_primary=False)
            
        StudentPhoto.objects.create(
            student=student,
            image=photo_file,
            is_primary=is_primary,
            privacy_consent=privacy_consent
        )
        messages.success(request, "Photo uploaded successfully.")
    else:
        messages.error(request, "No file selected.")
        
    return redirect('student_detail', pk=pk)
