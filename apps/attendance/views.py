import json
import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.conf import settings

from apps.students.models import Student
from apps.students.qr_utils import verify_token
from apps.students.face_pipeline import detect_and_embed, compare_embeddings, passive_liveness_check
from apps.audit.utils import audit
from .models import AttendanceSession, AttendanceRecord, Subject, AcademicClass, AcademicYear
from .forms import AttendanceSessionForm
from .analytics import get_student_analytics, get_admin_analytics
from datetime import datetime

logger = logging.getLogger(__name__)

FACE_MATCH_THRESHOLD = settings.FACE_MATCH_THRESHOLD

@login_required
def session_list(request):
    if request.user.role == 'TEACHER':
        sessions = AttendanceSession.objects.filter(teacher=request.user)
    else:
        sessions = AttendanceSession.objects.all()
    sessions = sessions.order_by('-started_at')
    return render(request, 'attendance/session_list.html', {'sessions': sessions})

@login_required
def session_create(request):
    # Prevent teachers from creating a new session if they already have an active one
    if request.user.role == 'TEACHER':
        active_session = AttendanceSession.objects.filter(teacher=request.user, status='OPEN').first()
        if active_session:
            messages.warning(request, "You currently have an active session open. Please close it before creating a new one.")
            return redirect('session_detail', pk=active_session.id)

    if request.method == 'POST':
        form = AttendanceSessionForm(request.POST, user=request.user)
        if form.is_valid():
            session = form.save(commit=False)
            session.teacher = request.user
            session.save()
            audit(request, 'SESSION_CREATED', 'AttendanceSession', str(session.id))
            messages.success(request, f"Session for {session.subject} created.")
            return redirect('session_detail', pk=session.id)
    else:
        form = AttendanceSessionForm(user=request.user)
    return render(request, 'attendance/session_form.html', {'form': form, 'title': 'Create Session'})

@login_required
def session_detail(request, pk):
    session = get_object_or_404(AttendanceSession, pk=pk)
    records = session.records.select_related('student').all()
    
    # Pre-populate absent records for active students in section if not exist
    if session.subject:
        active_students = session.subject.enrolled_students.filter(enrollment_status='ACTIVE')
        existing_record_student_ids = [r.student_id for r in records]
        
        for student in active_students:
            if student.id not in existing_record_student_ids:
                AttendanceRecord.objects.create(
                    session=session,
                    student=student,
                    status='ABSENT',
                    verification_method='NONE'
                )
                
    # Re-fetch after pre-populating
    records = session.records.select_related('student').order_by('student__full_name')
    
    return render(request, 'attendance/session_detail.html', {
        'session': session,
        'records': records,
    })

@login_required
@require_POST
def session_close(request, pk):
    session = get_object_or_404(AttendanceSession, pk=pk)
    if session.status == 'OPEN':
        session.status = 'CLOSED'
        session.closed_at = timezone.now()
        session.save()
        audit(request, 'SESSION_CLOSED', 'AttendanceSession', str(session.id))
        messages.success(request, "Session closed.")
    return redirect('session_detail', pk=pk)

@login_required
@require_POST
def session_reopen(request, pk):
    if getattr(request.user, 'role', '') != 'ADMIN':
        messages.error(request, "Only administrators can reopen a closed session.")
        return redirect('session_detail', pk=pk)
        
    session = get_object_or_404(AttendanceSession, pk=pk)
    if session.status == 'CLOSED':
        # Re-open the session
        session.status = 'OPEN'
        session.closed_at = None
        session.save()
        audit(request, 'SESSION_REOPENED', 'AttendanceSession', str(session.id))
        messages.success(request, "Session has been successfully reopened.")
    return redirect('session_detail', pk=pk)

@login_required
def scanner_view(request, pk):
    """View that renders the QR and face scanner interface."""
    session = get_object_or_404(AttendanceSession, pk=pk)
    if session.status != 'OPEN':
        messages.warning(request, "This session is not open for scanning.")
        return redirect('session_detail', pk=pk)
    return render(request, 'attendance/scanner.html', {'session': session})

@login_required
@require_POST
def lookup_profile(request, pk):
    """
    API endpoint called to quickly fetch profile info upon QR scan.
    Expects JSON: { "qr_token": "..." }
    """
    session = get_object_or_404(AttendanceSession, pk=pk)
    if session.status != 'OPEN':
        return JsonResponse({'success': False, 'error': 'SESSION_CLOSED'})
        
    try:
        data = json.loads(request.body)
        qr_token = data.get('qr_token')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'INVALID_JSON'})

    if not qr_token:
        return JsonResponse({'success': False, 'error': 'MISSING_DATA'})

    student_id_str = verify_token(qr_token)
    if not student_id_str:
        return JsonResponse({'success': False, 'error': 'INVALID_QR'})
        
    student = Student.objects.filter(university_roll_number=student_id_str).first()
    
    # Fallback to legacy UUID token
    if not student:
        import uuid
        try:
            uuid_obj = uuid.UUID(student_id_str, version=4)
            student = Student.objects.filter(pk=uuid_obj).first()
        except ValueError:
            pass

    if not student:
        return JsonResponse({'success': False, 'error': 'STUDENT_NOT_FOUND'})

    if session.subject and not student.enrolled_subjects.filter(id=session.subject_id).exists():
        return JsonResponse({'success': False, 'error': 'STUDENT_NOT_IN_SUBJECT'})
        
    # Determine photo URL
    primary_photo = student.photos.filter(is_primary=True).first()
    photo_url = primary_photo.image.url if primary_photo else None
    
    # Check if already marked present
    record = AttendanceRecord.objects.filter(session=session, student=student).first()
    already_marked = record and record.status == 'PRESENT'

    return JsonResponse({
        'success': True,
        'student': {
            'id': str(student.id),
            'full_name': student.full_name,
            'student_id': student.student_id,
            'course': getattr(session.subject, 'code', 'N/A') if session.subject else 'N/A',
            'status': student.enrollment_status,
            'photo_url': photo_url,
            'already_marked': already_marked
        }
    })

@login_required
@require_POST
def verify_attendance(request, pk):
    """
    API endpoint called by the scanner JS.
    Expects JSON: { "frame": "base64...", "current_qr": "..." }
    """
    session = get_object_or_404(AttendanceSession, pk=pk)
    if session.status != 'OPEN':
        return JsonResponse({'success': False, 'error': 'SESSION_CLOSED'})

    try:
        data = json.loads(request.body)
        frame_b64 = data.get('frame')
        current_qr = data.get('current_qr')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'INVALID_JSON'})

    if not frame_b64:
        return JsonResponse({'success': False, 'error': 'MISSING_FRAME'})

    if ',' in frame_b64:
        frame_b64 = frame_b64.split(',')[1]
        
    import base64
    try:
        image_bytes = base64.b64decode(frame_b64)
    except Exception:
        return JsonResponse({'success': False, 'error': 'INVALID_BASE64'})

    from apps.students.face_pipeline import process_biometric_frame
    student = None
    stored_vecs = None

    if current_qr:
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
            
        if session.subject and not student.enrolled_subjects.filter(id=session.subject_id).exists():
             return JsonResponse({'success': False, 'error': 'STUDENT_NOT_IN_SUBJECT'})

        stored_embeddings = student.embeddings.filter(is_active=True)
        if not stored_embeddings.exists():
            return JsonResponse({'success': False, 'error': 'NO_ENROLLED_FACE'})
            
        stored_vecs = [e.get_vector() for e in stored_embeddings]

    try:
        logger.info(f"Biometric Request: frame_size={{len(image_bytes)}} bytes, qr_present={{bool(current_qr)}}")
        result = process_biometric_frame(image_bytes, stored_vecs=stored_vecs, threshold=FACE_MATCH_THRESHOLD)
        logger.info(f"Biometric Result: qr_detected={{bool(result.get('qr_data'))}} face_detected={{bool(result.get('face_box'))}}")
    except Exception as e:
        logger.error(f"Biometric Processing Crash: {e}")
        return JsonResponse({'success': False, 'error': 'SERVER_PIPELINE_ERROR', 'details': str(e)})

    if result.get('face_match') and student:
        record, created = AttendanceRecord.objects.get_or_create(
            session=session, student=student,
            defaults={'status': 'ABSENT'}
        )
        if record.status != 'PRESENT':
            record.status = 'PRESENT'
            record.marked_at = timezone.now()
            record.verification_method = 'FACE'
            record.face_match_score = result.get('face_score')
            record.save()
            audit(request, 'ATTENDANCE_MARKED', 'AttendanceRecord', str(record.id))
            
    return JsonResponse({'success': True, 'data': result})

@login_required
def attendance_viewer(request):
    """
    Renders the UI framework for the advanced Role-Based Attendance Viewer.
    Provides necessary filter options natively.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    context = {}
    if request.user.role == 'ADMIN' or getattr(request.user, 'is_admin', lambda: False)():
        context['teachers'] = User.objects.filter(role='TEACHER')
        context['courses'] = Subject.objects.values_list('code', flat=True).distinct()
        
    elif request.user.role == 'TEACHER' or getattr(request.user, 'is_teacher', lambda: False)():
        context['courses'] = Subject.objects.filter(teachers=request.user).values_list('code', flat=True).distinct()
        subjects = Subject.objects.filter(teachers=request.user)
        context['students'] = Student.objects.filter(enrolled_subjects__in=subjects).distinct()
        
    elif request.user.role == 'STUDENT' or getattr(request.user, 'is_student', lambda: False)():
        if hasattr(request.user, 'student_profile'):
            subjects = request.user.student_profile.enrolled_subjects.all()
            context['courses'] = list(subjects.values_list('code', flat=True).distinct())
        else:
            context['courses'] = []

    return render(request, 'attendance/viewer.html', context)

@login_required
def analytics_dashboard(request):
    if not (request.user.is_admin() or request.user.is_teacher()):
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    subjects = Subject.objects.all()
    # Simplified context since we dropped Section, giving raw Subjects for now
    return render(request, 'attendance/analytics.html', {
        'sections': subjects, # renamed variable eventually!
    })

@login_required
def analytics_data(request):
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None

    if request.user.is_student():
        if not hasattr(request.user, 'student_profile'):
            return JsonResponse({'error': 'No profile linked'}, status=400)
            
        data = get_student_analytics(request.user.student_profile, start_date, end_date)
        data['recent_history'] = [{'status': r.status, 'marked_at': r.marked_at} for r in data['recent_history']]
        return JsonResponse(data)
    else:
        # Re-use academic filters if possible, but keep simple mapped equivalent
        subject_id = request.GET.get('section_id') # Map from old JS
        data = get_admin_analytics(start_date, end_date, subject_id=subject_id)
        return JsonResponse(data)

@login_required
def export_reports(request):
    return JsonResponse({'success': False, 'error': 'Export feature removed.'})

@login_required
def reports_dashboard(request):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    ctx = {}
    if request.user.role == 'ADMIN' or getattr(request.user, 'is_admin', lambda: False)():
        ctx['sections'] = Subject.objects.all().order_by('code')
        ctx['teachers'] = User.objects.filter(role='TEACHER')
        ctx['role'] = 'ADMIN'

    elif request.user.role == 'TEACHER' or getattr(request.user, 'is_teacher', lambda: False)():
        ctx['sections'] = Subject.objects.filter(teachers=request.user).order_by('code')
        ctx['role'] = 'TEACHER'

    elif request.user.role == 'STUDENT' or getattr(request.user, 'is_student', lambda: False)():
        ctx['role'] = 'STUDENT'
        if hasattr(request.user, 'student_profile'):
            ctx['student'] = request.user.student_profile

    return render(request, 'attendance/reports.html', ctx)

@login_required
def report_student_detail(request, student_id):
    student = get_object_or_404(Student, pk=student_id)

    user = request.user
    if user.role == 'STUDENT' or getattr(user, 'is_student', lambda: False)():
        if not hasattr(user, 'student_profile') or user.student_profile.id != student.id:
            messages.error(request, "Access denied.")
            return redirect('dashboard')
    elif user.role == 'TEACHER' or getattr(user, 'is_teacher', lambda: False)():
        if not student.enrolled_subjects.filter(teachers=user).exists():
            messages.error(request, "Access denied.")
            return redirect('dashboard')

    return render(request, 'attendance/report_student.html', {'student': student})

@login_required
def report_export_view(request):
    return JsonResponse({'success': False, 'error': 'Export feature removed.'})

