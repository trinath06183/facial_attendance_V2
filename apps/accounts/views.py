from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test

from django.contrib.auth import login
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import json
import base64

from .forms import CustomUserCreationForm, CustomUserChangeForm
from .models import CustomUser


def is_admin(user):
    return user.is_authenticated and user.role == 'ADMIN'


@login_required
def user_list(request):
    if not request.user.is_admin():
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    users = CustomUser.objects.all().order_by('username')
    return render(request, 'accounts/user_list.html', {'users': users})


@login_required
def user_create(request):
    if not request.user.is_admin():
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "User created successfully.")
            return redirect('user_list')
    else:
        form = CustomUserCreationForm()
    return render(request, 'accounts/user_form.html', {'form': form, 'title': 'Create User'})

@login_required
def user_edit(request, user_id):
    if not request.user.is_admin():
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    user = get_object_or_404(CustomUser, id=user_id)
    if request.method == 'POST':
        form = CustomUserChangeForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f"User {user.username} updated successfully.")
            return redirect('user_list')
    else:
        form = CustomUserChangeForm(instance=user)
    return render(request, 'accounts/user_form.html', {'form': form, 'title': f'Edit User: {user.username}'})

@login_required
def user_toggle_status(request, user_id):
    if not request.user.is_admin():
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    user = get_object_or_404(CustomUser, id=user_id)
    if user == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect('user_list')
    
    user.is_active = not user.is_active
    user.save()
    status = "activated" if user.is_active else "deactivated"
    messages.success(request, f"User {user.username} has been {status}.")
    return redirect('user_list')


@require_POST
def biometric_login_api(request):
    """
    API endpoint for biometric login.
    Expects JSON: { "frame": "base64...", "current_qr": "..." }
    """
    import time
    
    # Lockout check
    lockout_until = request.session.get('bio_lockout_until')
    if lockout_until and time.time() < lockout_until:
        remaining = int(lockout_until - time.time())
        return JsonResponse({'success': False, 'error': 'ACCOUNT_LOCKED', 'timeout': remaining})

    try:
        data = json.loads(request.body)
        frame_b64 = data.get('frame')
        current_qr = data.get('current_qr')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'INVALID_JSON'})

    if not frame_b64:
        return JsonResponse({'success': False, 'error': 'MISSING_FRAME'})

    # Strip data URL prefix if present
    if ',' in frame_b64:
        frame_b64 = frame_b64.split(',')[1]
    
    try:
        image_bytes = base64.b64decode(frame_b64)
    except Exception:
        return JsonResponse({'success': False, 'error': 'INVALID_BASE64'})

    from apps.students.models import Student
    from apps.students.qr_utils import verify_token
    from apps.students.face_pipeline import process_biometric_frame

    student = None
    stored_vecs = None

    # If QR is provided, find the student
    if current_qr:
        student_id_str = verify_token(current_qr)
        if student_id_str:
            student = Student.objects.filter(university_roll_number=student_id_str).first()
            if not student:
                # Legacy UUID fallback
                import uuid
                try:
                    uuid_obj = uuid.UUID(student_id_str, version=4)
                    student = Student.objects.filter(pk=uuid_obj).first()
                except ValueError:
                    pass
                    
        if student:
            stored_embeddings = student.embeddings.filter(is_active=True)
            if stored_embeddings.exists():
                stored_vecs = [e.get_vector() for e in stored_embeddings]

    # Process the frame
    result = process_biometric_frame(image_bytes, stored_vecs=stored_vecs)

    # If we have a successful face match and a student, log them in!
    if result.get('face_match') and student and hasattr(student, 'user') and student.user:
        if student.user.is_active:
            login(request, student.user)
            # Reset failed attempts
            request.session['bio_failed_attempts'] = 0
            
            # Log the biometric login in the audit system
            from apps.audit.utils import audit
            audit(request, 'LOGGED_IN_BIOMETRIC', 'User', str(student.user.id), "Biometric verification successful")
            result['redirect_url'] = '/dashboard/'
        else:
            result['face_match'] = False
            result['error'] = 'ACCOUNT_INACTIVE'
    elif current_qr and result.get('face_box') and not result.get('face_match'):
        # Failed match while looking at a face
        fails = request.session.get('bio_failed_attempts', 0) + 1
        request.session['bio_failed_attempts'] = fails
        if fails >= 5: # Lockout after 5 continuous failed face frames
            import time
            request.session['bio_lockout_until'] = time.time() + 60 # 60 second lockout
            from apps.audit.utils import audit
            audit(request, 'BIO_AUTH_LOCKED', 'Student', str(student.id), "5 consecutive failed face matches")
            result['error'] = 'ACCOUNT_LOCKED'
            result['timeout'] = 60
        else:
            # Simple failure log
            from apps.audit.utils import audit
            audit(request, 'BIO_AUTH_FAILED', 'Student', str(student.id), f"Frame {fails}/5 - Face match failed")
            
    return JsonResponse({'success': True, 'data': result})
