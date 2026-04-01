from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test

from django.contrib.auth import login
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import json
import base64
import time

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


# ── Student Biometric Login Scanner ──────────────────────────────────────────

def student_scanner_view(request):
    """
    Public page: students scan their QR + face to log in.
    No @login_required — accessible from the login page.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'accounts/student_scanner.html')


@require_POST
def student_face_login_api(request):
    """
    Public API for the student biometric login scanner.
    Expects JSON: { "frame": "base64...", "current_qr": "..." or null }

    Phase 1 (current_qr is null):
        - Run process_biometric_frame to detect QR code + face bounding box.
        - If QR detected, look up the student and return their profile.
        - Frontend uses this to lock the QR and show the student card.

    Phase 2 (current_qr is provided):
        - Look up the student by the locked QR token.
        - Load their stored face embeddings.
        - Run process_biometric_frame with stored_vecs to match face.
        - On match, log the student in and return redirect_url.
    """
    # ── Lockout check ────────────────────────────────────────────
    lockout_until = request.session.get('bio_lockout_until')
    if lockout_until and time.time() < lockout_until:
        remaining = int(lockout_until - time.time())
        return JsonResponse({'success': False, 'error': 'ACCOUNT_LOCKED', 'timeout': remaining})

    # ── Parse request ────────────────────────────────────────────
    try:
        data = json.loads(request.body)
        frame_b64  = data.get('frame')
        current_qr = data.get('current_qr')  # None in Phase 1, token string in Phase 2
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'INVALID_JSON'})

    if not frame_b64:
        return JsonResponse({'success': False, 'error': 'MISSING_FRAME'})

    if ',' in frame_b64:
        frame_b64 = frame_b64.split(',')[1]

    try:
        image_bytes = base64.b64decode(frame_b64)
    except Exception:
        return JsonResponse({'success': False, 'error': 'INVALID_BASE64'})

    from apps.students.models import Student
    from apps.students.qr_utils import verify_token
    from apps.students.face_pipeline import process_biometric_frame

    # ── PHASE 1: No QR locked yet — just detect QR + face in frame ──
    if not current_qr:
        result = process_biometric_frame(image_bytes, stored_vecs=None)

        # If a QR was detected in the frame, resolve which student it belongs to
        if result.get('qr_data'):
            student_id_str = verify_token(result['qr_data'])
            if student_id_str:
                student = Student.objects.filter(university_roll_number=student_id_str).first()
                if not student:
                    import uuid
                    try:
                        uuid_obj = uuid.UUID(student_id_str, version=4)
                        student = Student.objects.filter(pk=uuid_obj).first()
                    except ValueError:
                        pass

                if student:
                    primary_photo = student.photos.filter(is_primary=True).first()
                    result['student'] = {
                        'full_name': student.full_name,
                        'student_id': getattr(student, 'university_roll_number', str(student.id)),
                        'photo_url':  primary_photo.image.url if primary_photo else '',
                    }

        return JsonResponse({'success': True, 'data': result})

    # ── PHASE 2: QR is locked — match face against the student's embeddings ──
    student = None
    stored_vecs = None

    student_id_str = verify_token(current_qr)
    if student_id_str:
        student = Student.objects.filter(university_roll_number=student_id_str).first()
        if not student:
            import uuid
            try:
                uuid_obj = uuid.UUID(student_id_str, version=4)
                student = Student.objects.filter(pk=uuid_obj).first()
            except ValueError:
                pass

    if not student:
        return JsonResponse({'success': False, 'error': 'STUDENT_NOT_FOUND'})

    stored_embeddings = student.embeddings.filter(is_active=True)
    if not stored_embeddings.exists():
        return JsonResponse({'success': False, 'error': 'NO_ENROLLED_FACE'})

    stored_vecs = [e.get_vector() for e in stored_embeddings]

    result = process_biometric_frame(image_bytes, stored_vecs=stored_vecs)

    # Keep the student card visible during face scan phase
    primary_photo = student.photos.filter(is_primary=True).first()
    result['student'] = {
        'full_name': student.full_name,
        'student_id': getattr(student, 'university_roll_number', str(student.id)),
        'photo_url':  primary_photo.image.url if primary_photo else '',
    }

    # ── Successful face match → log in ───────────────────────────
    if result.get('face_match'):
        from django.contrib.auth import get_user_model
        from apps.audit.utils import audit
        User = get_user_model()

        # --- Ensure the student has a linked user account ---
        if not student.user:
            # 1. Try to find an existing user by email
            existing = User.objects.filter(email=student.email).first() if student.email else None

            if existing:
                # Link the found user to this student
                student.user = existing
                student.save(update_fields=['user'])
                logger.info(f"Linked existing user {existing.username} to student {student.full_name}")
            else:
                # 2. Auto-create a new user account for the student
                # Username: roll number (sanitised) or uuid prefix
                raw_username = (
                    getattr(student, 'university_roll_number', None)
                    or str(student.id)[:8]
                )
                # Ensure uniqueness
                base = raw_username.lower().replace(' ', '_')
                username = base
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base}_{counter}"
                    counter += 1

                new_user = User.objects.create_user(
                    username=username,
                    email=student.email or '',
                    password=None,          # unusable password — login only via biometrics
                    role='STUDENT',
                    is_active=True,
                )
                student.user = new_user
                student.save(update_fields=['user'])
                audit(request, 'USER_AUTO_CREATED', 'User', str(new_user.id),
                      f"Auto-created biometric-only account for student {student.full_name}")
                logger.info(f"Auto-created user {username} for student {student.full_name}")

        # --- Now log in ---
        if student.user and student.user.is_active:
            login(request, student.user)
            request.session['bio_failed_attempts'] = 0
            audit(request, 'LOGGED_IN_BIOMETRIC', 'User', str(student.user.id),
                  f"Biometric login — score {result.get('face_score', 0):.4f}")
            result['redirect_url'] = '/dashboard/'
        else:
            result['face_match'] = False
            result['error'] = 'ACCOUNT_INACTIVE'

    elif result.get('face_box') and not result.get('face_match'):
        # Track failed frames for lockout
        fails = request.session.get('bio_failed_attempts', 0) + 1
        request.session['bio_failed_attempts'] = fails
        if fails >= 5:
            request.session['bio_lockout_until'] = time.time() + 60
            from apps.audit.utils import audit
            audit(request, 'BIO_AUTH_LOCKED', 'Student', str(student.id),
                  "5 consecutive failed face matches on scanner page")
            result['error'] = 'ACCOUNT_LOCKED'
            result['timeout'] = 60
        else:
            from apps.audit.utils import audit
            audit(request, 'BIO_AUTH_FAILED', 'Student', str(student.id),
                  f"Frame {fails}/5 – Face match failed on scanner page")

    return JsonResponse({'success': True, 'data': result})
