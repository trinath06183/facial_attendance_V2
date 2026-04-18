from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test

from django.contrib.auth import login, logout
from django.contrib.auth.views import LoginView
from django.conf import settings
from apps.accounts.utils import is_user_already_active, terminate_user_session, touch_user_activity
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse
import json
import base64
import time
import logging

from .forms import CustomUserCreationForm, CustomUserChangeForm
from .models import CustomUser

logger = logging.getLogger(__name__)

class CustomLoginView(LoginView):
    """
    Extends generic LoginView to block login if user is already active.
    """
    template_name = 'accounts/login.html'

    def form_valid(self, form):
        user = form.get_user()
        force_login = self.request.POST.get('force_login') == 'true'

        if is_user_already_active(user, self.request):
            if force_login:
                terminate_user_session(user)
            else:
                # Log failed login attempt because of conflict
                from apps.audit.utils import log_event
                log_event(
                    event_type='LOGIN_FAILED',
                    auth_method='password',
                    request=self.request,
                    user=user,
                    context={'reason': 'USER_ALREADY_ACTIVE'},
                )
                return self.render_to_response(self.get_context_data(
                    form=form,
                    admin_teacher_already_active=True
                ))

        # Tell the signal which auth method was used
        self.request.session['_auth_method'] = 'password'
        response = super().form_valid(form)
        touch_user_activity(self.request)
        return response

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
            force_login = data.get('force_login') is True
            if is_user_already_active(student.user, request):
                if force_login:
                    terminate_user_session(student.user)
                else:
                    return JsonResponse({'success': False, 'error': 'USER_ALREADY_ACTIVE'})

            request.session['_auth_method'] = 'facial_recognition'
            login(request, student.user)
            touch_user_activity(request)
            # Reset failed attempts
            request.session['bio_failed_attempts'] = 0
            
            # Log the biometric login in the audit system
            from apps.audit.utils import log_event
            log_event(request=request, event_type='BIO_LOGIN', auth_method='facial_recognition',
                      context={'score': result.get('face_score', 0),
                               'student_id': str(student.user.id)})
            result['redirect_url'] = '/dashboard/'
        else:
            result['face_match'] = False
            result['error'] = 'ACCOUNT_INACTIVE'
    elif current_qr and result.get('face_box') and not result.get('face_match'):
        # Failed match while looking at a face
        fails = request.session.get('bio_failed_attempts', 0) + 1
        request.session['bio_failed_attempts'] = fails
        if fails >= 5:
            import time
            request.session['bio_lockout_until'] = time.time() + 60
            from apps.audit.utils import log_event
            log_event(event_type='BIO_AUTH_LOCKED', auth_method='facial_recognition',
                      request=request,
                      context={'student_id': str(student.id), 'reason': '5 consecutive failed face matches'})
            result['error'] = 'ACCOUNT_LOCKED'
            result['timeout'] = 60
        else:
            from apps.audit.utils import log_event
            log_event(event_type='BIO_LOGIN_FAILED', auth_method='facial_recognition',
                      request=request,
                      context={'student_id': str(student.id), 'attempt': f"{fails}/5"})
            
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
    # ── Lockout check (DISABLED) ───────────────────────────────
    # lockout_until = request.session.get('bio_lockout_until')
    # if lockout_until and time.time() < lockout_until:
    #     remaining = int(lockout_until - time.time())
    #     return JsonResponse({'success': False, 'error': 'ACCOUNT_LOCKED', 'timeout': remaining})

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
            # 1. Only link an existing user if they are already STUDENT role.
            #    NEVER touch ADMIN or TEACHER accounts — doing so would demote them.
            existing = None
            if student.email:
                candidate = User.objects.filter(email=student.email).first()
                if candidate and candidate.role == 'STUDENT':
                    existing = candidate

            if existing:
                student.user = existing
                student.save(update_fields=['user'])
                logger.info(f"Linked existing student user '{existing.username}' to student {student.full_name}")
            else:
                # 2. Auto-create a fresh student-only user account
                raw_username = (
                    getattr(student, 'university_roll_number', None)
                    or str(student.id)[:8]
                )
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
                    must_change_password=True,
                )
                student.user = new_user
                student.save(update_fields=['user'])
                audit(request, 'USER_AUTO_CREATED', 'User', str(new_user.id),
                      f"Auto-created biometric-only account for student {student.full_name}")
                logger.info(f"Auto-created user '{username}' for student {student.full_name}")

        # Do NOT forcibly change the role of any linked user.
        # If an admin/teacher is accidentally linked, that must be fixed manually.

        # --- Now log in ---
        if student.user and student.user.is_active:
            force_login = data.get('force_login') is True
            if is_user_already_active(student.user, request):
                if force_login:
                    terminate_user_session(student.user)
                else:
                    return JsonResponse({'success': False, 'error': 'USER_ALREADY_ACTIVE'})

            if not request.user.is_authenticated or request.user.id != student.user.id:
                login(request, student.user, backend='django.contrib.auth.backends.ModelBackend')
                touch_user_activity(request)
                request.session['bio_failed_attempts'] = 0
                audit(request, 'LOGGED_IN_BIOMETRIC', 'User', str(student.user.id),
                      f"Biometric login — score {result.get('face_score', 0):.4f}")
            # Force password change on first login
            if student.user.must_change_password:
                result['redirect_url'] = '/accounts/student/first-login-change-password/'
            else:
                result['redirect_url'] = '/dashboard/'
        else:
            result['face_match'] = False
            result['error'] = 'ACCOUNT_INACTIVE'

    elif result.get('face_box') and not result.get('face_match'):
        # Lockout system disabled
        from apps.audit.utils import audit
        audit(request, 'BIO_AUTH_FAILED', 'Student', str(student.id), "Face match failed on scanner page")

    return JsonResponse({'success': True, 'data': result})


# Removed destructive browser_logout_api endpoint that caused erratic auto-logouts
# ── Email OTP Password Reset Flow ─────────────────────────────────────────────

import secrets
from django.core.mail import send_mail
from .models import PasswordResetOTP

def password_reset_request(request):
    """Step 1: User enters their email to request an OTP."""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        user = CustomUser.objects.filter(email=email).first()
        
        # Security: Only allow ADMIN and TEACHER to use this flow.
        if user and user.role in ['ADMIN', 'TEACHER']:
            # Generate 6-digit OTP
            otp_code = str(secrets.randbelow(900000) + 100000)
            
            # Save OTP to DB
            PasswordResetOTP.objects.create(user=user, otp=otp_code)
            
            # Send Email
            subject = "SmartAttend - Password Reset Verification Code"
            message = f"Hello {user.get_full_name()},\n\nYour password reset OTP code is: {otp_code}\nThis code will expire in 10 minutes.\n\nIf you did not request this, please ignore this email."
            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
                from apps.audit.utils import log_event
                log_event(event_type='OTP_SENT', auth_method='otp', request=request, user=user,
                          context={'flow': 'admin_teacher_password_reset', 'email_masked': user.email[:3]+'***'})
                request.session['reset_email'] = user.email
                return redirect('password_reset_verify')
            except Exception:
                logger.exception("Failed to send OTP email")
                messages.error(request, "Unable to send verification email; please try again later.")
        else:
            # Vague message for security (don't reveal if email exists)
            messages.info(request, "If an Admin or Teacher account exists with that email, an OTP has been sent.")
            # Even if it failed, redirect to verification for security obscurity, 
            # or just show a message.
            request.session['reset_email'] = email
            return redirect('password_reset_verify')
            
    return render(request, 'accounts/password_reset_email.html')


def password_reset_verify(request):
    """Step 2: User enters the OTP received in email."""
    email = request.session.get('reset_email')
    if not email:
        return redirect('password_reset_request')
        
    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()
        user = CustomUser.objects.filter(email=email).first()
        
        if user:
            # Get the latest OTP for this user
            valid_otp = PasswordResetOTP.objects.filter(user=user).order_by('-created_at').first()
            if valid_otp and secrets.compare_digest(str(valid_otp.otp), str(otp_input)):
                if valid_otp.is_valid():
                    # Success
                    valid_otp.delete()
                    request.session['reset_verified_user_id'] = str(user.id)
                    return redirect('password_reset_confirm')
                else:
                    messages.error(request, "This OTP has expired. Please request a new one.")
            else:
                messages.error(request, "Invalid Verification Code.")
        else:
            messages.error(request, "Invalid Request.")

    return render(request, 'accounts/password_reset_otp.html', {'email': email})

def password_reset_confirm(request):
    """Step 3: User resets their password after verifying OTP."""
    user_id = request.session.get('reset_verified_user_id')
    if not user_id:
        return redirect('password_reset_request')
        
    user = get_object_or_404(CustomUser, id=user_id)
    
    if request.method == 'POST':
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        
        if password and password == password_confirm:
            if len(password) >= 8:
                user.set_password(password)
                user.save()
                
                # Cleanup session variables
                del request.session['reset_verified_user_id']
                if 'reset_email' in request.session:
                    del request.session['reset_email']
                
                from apps.audit.utils import log_event
                log_event(event_type='PASSWORD_CHANGE', auth_method='otp', request=request, user=user,
                          context={'flow': 'admin_teacher_otp_reset'})
                messages.success(request, "Password has been reset successfully. You may now log in.")
                return redirect('login')
            else:
                messages.error(request, "Password must be at least 8 characters long.")
        else:
            messages.error(request, "Passwords do not match.")
            
    return render(request, 'accounts/password_reset_confirm.html', {'user': user})


# ── Student Password Login ─────────────────────────────────────────────────────

@require_POST
def student_password_login(request):
    """
    POST handler for the student roll-number + password login form on the main login page.
    Authenticates via the linked CustomUser account on the Student model.
    """
    from apps.students.models import Student
    from django.contrib.auth import authenticate

    roll_number = request.POST.get('roll_number', '').strip()
    password = request.POST.get('password', '')

    student = Student.objects.filter(university_roll_number__iexact=roll_number).select_related('user').first()

    if student and student.user:
        user = authenticate(request, username=student.user.username, password=password)
        if user is not None:
            force_login = request.POST.get('force_login') == 'true'
            if is_user_already_active(user, request):
                if force_login:
                    terminate_user_session(user)
                else:
                    from apps.accounts.forms import CustomAuthenticationForm
                    return render(request, 'accounts/login.html', {
                        'form': CustomAuthenticationForm(),
                        'student_already_active': True,
                        'roll_number': roll_number,
                        'password': password
                    })

            request.session['_auth_method'] = 'password'
            login(request, user)
            touch_user_activity(request)
            # Force password change on first login
            if user.must_change_password:
                return redirect('student_first_login_change_password')
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid password. Please try again.")
            from apps.audit.utils import log_event
            log_event(event_type='LOGIN_FAILED', auth_method='password',
                      request=request,
                      context={'roll_number': roll_number, 'reason': 'INVALID_PASSWORD'})
    else:
        messages.error(request, "No student account found with that Roll Number.")

    return redirect('login')


# ── Student OTP Password Reset ─────────────────────────────────────────────────

def student_password_reset_request(request):
    """
    Step 1: Student enters their University Roll Number.
    System finds their registered email and dispatches an OTP.
    """
    from apps.students.models import Student

    if request.method == 'POST':
        roll_number = request.POST.get('roll_number', '').strip()
        student = Student.objects.filter(university_roll_number__iexact=roll_number).select_related('user').first()

        if student and student.user and student.email:
            otp_code = str(secrets.randbelow(900000) + 100000)
            PasswordResetOTP.objects.create(user=student.user, otp=otp_code)

            subject = "SmartAttend - Password Reset Verification Code"
            message = (
                f"Hello {student.full_name},\n\n"
                f"Your password reset OTP code is: {otp_code}\n"
                f"This code will expire in 10 minutes.\n\n"
                f"If you did not request this, please ignore this email."
            )
            try:
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [student.email], fail_silently=False)
                request.session['student_reset_roll'] = roll_number
                return redirect('student_password_reset_verify')
            except Exception:
                logger.exception("Failed to send student OTP email")
                messages.error(request, "Unable to send verification email; please try again later.")
        else:
            # Vague error for security
            messages.info(request, "If a student account exists with that Roll Number, an OTP has been sent to the registered email.")
            request.session['student_reset_roll'] = roll_number
            return redirect('student_password_reset_verify')

    return render(request, 'accounts/student_password_reset_request.html')


def student_password_reset_verify(request):
    """Step 2: Student enters the 6-digit OTP sent to their email."""
    from apps.students.models import Student

    roll_number = request.session.get('student_reset_roll')
    if not roll_number:
        return redirect('student_password_reset_request')

    student = Student.objects.filter(university_roll_number__iexact=roll_number).select_related('user').first()

    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()
        if student and student.user:
            valid_otp = PasswordResetOTP.objects.filter(user=student.user).order_by('-created_at').first()
            if valid_otp and secrets.compare_digest(str(valid_otp.otp), str(otp_input)):
                if valid_otp.is_valid():
                    valid_otp.delete()
                    request.session['student_reset_verified_user_id'] = str(student.user.id)
                    return redirect('student_password_reset_confirm')
                else:
                    messages.error(request, "This OTP has expired. Please request a new one.")
            else:
                messages.error(request, "Invalid verification code.")
        else:
            messages.error(request, "Invalid request.")

    # Mask the email for display
    masked_email = ''
    if student and student.email:
        parts = student.email.split('@')
        masked_email = parts[0][:2] + '****@' + parts[1] if len(parts) == 2 else '****'

    return render(request, 'accounts/student_password_reset_otp.html', {'masked_email': masked_email, 'roll_number': roll_number})


def student_password_reset_confirm(request):
    """Step 3: Student sets a new password."""
    user_id = request.session.get('student_reset_verified_user_id')
    if not user_id:
        return redirect('student_password_reset_request')

    user = get_object_or_404(CustomUser, id=user_id)

    if request.method == 'POST':
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')

        if password and password == password_confirm:
            if len(password) >= 8:
                user.set_password(password)
                user.save()
                del request.session['student_reset_verified_user_id']
                if 'student_reset_roll' in request.session:
                    del request.session['student_reset_roll']
                messages.success(request, "Password updated! You can now log in with your Roll Number and new password.")
                return redirect('login')
            else:
                messages.error(request, "Password must be at least 8 characters long.")
        else:
            messages.error(request, "Passwords do not match.")

    return render(request, 'accounts/student_password_reset_confirm.html', {'user': user})


# ── Student Change Password (logged in) ────────────────────────────────────────

@login_required
def student_change_password(request):
    """Allows a logged-in STUDENT to change their password."""
    from django.contrib.auth import update_session_auth_hash

    if request.user.role != 'STUDENT':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if not request.user.check_password(current_password):
            messages.error(request, "Your current password is incorrect.")
        elif new_password != confirm_password:
            messages.error(request, "New passwords do not match.")
        elif len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
        else:
            request.user.set_password(new_password)
            request.user.must_change_password = False
            request.user.save()
            # Keep the user logged in after password change
            update_session_auth_hash(request, request.user)
            messages.success(request, "Your password has been changed successfully!")
            return redirect('dashboard')

    return render(request, 'accounts/student_change_password.html')


@login_required
def student_first_login_change_password(request):
    """
    Shown immediately after a student's very first login.
    The student is NOT required to enter their old (default) password.
    After a successful change, must_change_password is cleared and 
    they are redirected to the dashboard.
    """
    from django.contrib.auth import update_session_auth_hash

    if request.user.role != 'STUDENT':
        return redirect('dashboard')

    # If they've already changed their password, go straight to dashboard
    if not request.user.must_change_password:
        return redirect('dashboard')

    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if not new_password or new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
        elif len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
        elif new_password == request.user.username:
            messages.error(request, "Your new password cannot be the same as your username (default password). Please choose a different password.")
        else:
            request.user.set_password(new_password)
            request.user.must_change_password = False
            request.user.save()
            update_session_auth_hash(request, request.user)
            from apps.audit.utils import log_event
            log_event(event_type='PASSWORD_CHANGE', auth_method='password', request=request,
                      context={'flow': 'student_first_login', 'forced': True})
            messages.success(request, "Password updated! Welcome to SmartAttend.")
            return redirect('dashboard')

    return render(request, 'accounts/student_first_login_change_password.html')


@login_required
@require_POST
def session_activity_ping(request):
    touch_user_activity(request)
    return JsonResponse({'success': True})


@login_required
@require_POST
def session_idle_logout(request):
    request.session['_logout_reason'] = 'inactivity_timeout'
    logout(request)
    return JsonResponse({'success': True, 'redirect_url': settings.LOGIN_URL})
