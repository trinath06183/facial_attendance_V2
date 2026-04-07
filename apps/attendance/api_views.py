import math
import logging
import json
from datetime import datetime
from django.utils.timezone import now, localtime

from django.core.paginator import Paginator, EmptyPage
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.shortcuts import get_object_or_404
from django.db.models import Q

from .models import AttendanceRecord

logger = logging.getLogger(__name__)

def get_filtered_attendance_qs(request):
    """
    Returns a tuple of (queryset, error_response).
    Applies RBAC and all exact filters based on request.GET.
    """
    user = request.user
    
    # Base queryset with relations
    qs = AttendanceRecord.objects.select_related(
        'student',
        'session',
        'session__subject',
        'session__teacher'
    )
    
    # Role-Based Access Control Filtering
    if user.role == 'STUDENT' or getattr(user, 'is_student', lambda: False)():
        # Students can only see their own records
        if not hasattr(user, 'student_profile'):
            return None, JsonResponse({'success': False, 'error': 'No linked student profile.'}, status=403)
        qs = qs.filter(student=user.student_profile)
        
    elif user.role == 'TEACHER' or getattr(user, 'is_teacher', lambda: False)():
        # Teachers can see sessions they created OR sessions in subjects they are assigned to
        qs = qs.filter(
            session__subject__teachers=user
        ).distinct()
        
    elif user.role == 'ADMIN' or getattr(user, 'is_admin', lambda: False)():
        # Admins see everything
        pass
    else:
        return None, JsonResponse({'success': False, 'error': 'Unauthorized role.'}, status=403)
        
    # --- Exact Filters ---
    student_name = request.GET.get('studentName')
    if student_name and not (user.role == 'STUDENT' or getattr(user, 'is_student', lambda: False)()):
        qs = qs.filter(student__full_name__icontains=student_name)
        
    student_roll = request.GET.get('studentRoll')
    if student_roll and not (user.role == 'STUDENT' or getattr(user, 'is_student', lambda: False)()):
        qs = qs.filter(student__university_roll_number__icontains=student_roll)
        
    teacher_id = request.GET.get('teacherId')
    if teacher_id:
        qs = qs.filter(session__teacher__id=teacher_id)
        
    course_id = request.GET.get('courseId')
    if course_id:
        qs = qs.filter(session__subject__code=course_id)
        
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
        
    session_id = request.GET.get('sessionId')
    if session_id:
        qs = qs.filter(session__id=session_id)
        
    from_date = request.GET.get('fromDate')
    if from_date:
        try:
            dt = datetime.strptime(from_date, '%Y-%m-%d').date()
            qs = qs.filter(session__started_at__date__gte=dt)
        except ValueError:
            return None, JsonResponse({'success': False, 'error': 'Invalid date format for fromDate. Expected YYYY-MM-DD'}, status=400)
            
    to_date = request.GET.get('toDate')
    if to_date:
        try:
            dt = datetime.strptime(to_date, '%Y-%m-%d').date()
            qs = qs.filter(session__started_at__date__lte=dt)
        except ValueError:
            return None, JsonResponse({'success': False, 'error': 'Invalid date format for toDate. Expected YYYY-MM-DD'}, status=400)

    # --- Sorting ---
    sort_param = request.GET.get('sort', '-date')
    
    sort_mapping = {
        'date': 'session__started_at',
        '-date': '-session__started_at',
        'status': 'status',
        '-status': '-status',
        'student_name': 'student__full_name',
        '-student_name': '-student__full_name',
        'course': 'session__subject__code',
        '-course': '-session__subject__code',
    }
    
    order_by_field = sort_mapping.get(sort_param, '-session__started_at')
    qs = qs.order_by(order_by_field)
    
    return qs, None


@login_required
@require_GET
def attendances_api(request):
    """
    Unified API for Role-Based Attendance Viewer.
    Supports filtering, sorting, pagination.
    """
    qs, err_resp = get_filtered_attendance_qs(request)
    if err_resp:
        return err_resp
    
    # --- Pagination ---
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('pageSize', 25))
        page_size = min(max(1, page_size), 500)
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid pagination parameters.'}, status=400)
        
    paginator = Paginator(qs, page_size)
    
    try:
        page_obj = paginator.page(page)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages) if paginator.num_pages > 0 else []
        page = paginator.num_pages
        if int(request.GET.get('page', 1)) > paginator.num_pages and paginator.num_pages > 0:
            page_obj = [] 
        
    records_data = []
    items = page_obj.object_list if hasattr(page_obj, 'object_list') else []
    
    for record in items:
        duration_str = "Ongoing"
        if record.session.closed_at:
            delta = record.session.closed_at - record.session.started_at
            mins = math.ceil(delta.total_seconds() / 60)
            duration_str = f"{mins} mins"
            
        tdict = {
            'id': str(record.id),
            'date': record.session.started_at.isoformat(),
            'session': {
                'id': str(record.session.id),
                'name': str(record.session)
            },
            'course': {
                'code': record.session.subject.code if record.session.subject else "N/A",
                'name': record.session.subject.name if record.session.subject else "N/A"
            },
            'class_section': "N/A", # Dropped with 'Section' removal
            'teacher': {
                'id': str(record.session.teacher.id) if record.session.teacher else None,
                'name': record.session.teacher.get_full_name() or record.session.teacher.username if record.session.teacher else 'Unknown'
            },
            'student': {
                'id': str(record.student.id),
                'name': record.student.full_name,
                'roll_no': record.student.university_roll_number or record.student.student_id
            },
            'status': record.status,
            'mode': record.session.mode,
            'duration': duration_str,
            'notes': record.notes or ""
        }
        records_data.append(tdict)

    return JsonResponse({
        'success': True,
        'data': {
            'records': records_data,
            'pagination': {
                'page': page,
                'pageSize': page_size,
                'totalRecords': paginator.count,
                'totalPages': paginator.num_pages
            }
        }
    })


@login_required
@require_GET
def attendance_summary_api(request):
    """
    GET /attendance/api/summary/
    Returns aggregate attendance counts for the current filter set.
    """
    from django.http import QueryDict
    mutable = request.GET.copy()
    mutable.pop('status', None)

    original_get = request.GET
    request.GET  = mutable
    qs, err_resp = get_filtered_attendance_qs(request)
    request.GET  = original_get

    if err_resp:
        return err_resp

    from django.db.models import Count
    agg = qs.aggregate(
        total   = Count('id'),
        present = Count('id', filter=Q(status='PRESENT')),
        absent  = Count('id', filter=Q(status='ABSENT')),
        late    = Count('id', filter=Q(status='LATE')),
        excused = Count('id', filter=Q(status='EXCUSED')),
    )

    total   = agg['total']   or 0
    present = agg['present'] or 0
    absent  = agg['absent']  or 0
    late    = agg['late']    or 0
    excused = agg['excused'] or 0
    pct     = round((present / total) * 100, 1) if total > 0 else 0.0

    return JsonResponse({
        'success': True,
        'data': {
            'total':   total,
            'present': present,
            'absent':  absent,
            'late':    late,
            'excused': excused,
            'pct':     pct,
        }
    })


@login_required
@require_GET
def student_search_api(request):
    """
    Finds students by name or roll number for manual attendance override.
    """
    query = request.GET.get('q', '').strip()
    section_id = request.GET.get('section_id') # Leaving section_id for compat
    
    if not query or len(query) < 2:
        return JsonResponse({'success': True, 'data': []})
        
    from apps.students.models import Student
    
    qs = Student.objects.filter(
        Q(full_name__icontains=query) | 
        Q(university_roll_number__icontains=query) |
        Q(student_id__icontains=query)
    )
    
    if section_id:
        qs = qs.filter(enrolled_subjects__id=section_id)
        
    results = qs[:10]
    
    data = [{
        'id': str(student.id),
        'name': student.full_name,
        'roll_no': student.university_roll_number or student.student_id,
        'photo_url': student.photos.filter(is_primary=True).first().image.url if student.photos.filter(is_primary=True).exists() else None
    } for student in results]
    
    return JsonResponse({'success': True, 'data': data})


@login_required
@require_POST
def manual_override_api(request, session_id):
    """
    Manually mark a student present (for staff only).
    """
    if request.user.role not in ['ADMIN', 'TEACHER']:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
        
    import json
    from apps.attendance.models import AttendanceSession, AttendanceRecord
    from apps.students.models import Student
    
    try:
        data = json.loads(request.body)
        student_id = data.get('student_id')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'})
        
    session = get_object_or_404(AttendanceSession, id=session_id)
    student = get_object_or_404(Student, id=student_id)
    
    if session.status != 'OPEN':
        return JsonResponse({'success': False, 'error': 'Session is closed.'})
        
    if session.subject and not student.enrolled_subjects.filter(id=session.subject_id).exists():
        return JsonResponse({'success': False, 'error': 'Student not in this subject.'})
        
    record, created = AttendanceRecord.objects.get_or_create(
        session=session, 
        student=student,
        defaults={'status': 'PRESENT', 'verification_method': 'MANUAL', 'notes': f"Manually verified by {request.user.username}"}
    )
    
    if not created and record.status != 'PRESENT':
        record.status = 'PRESENT'
        record.verification_method = 'MANUAL'
        record.notes = f"Manual override by {request.user.username}"
        record.save()
        
    from apps.audit.utils import audit
    audit(request, 'ATTENDANCE_OVERRIDE', 'AttendanceRecord', str(record.id), {'notes': f"Student {student.university_roll_number} manually marked present"})
        
    return JsonResponse({'success': True, 'message': 'Successfully marked present manually.'})


@login_required
@require_POST
def attendance_record_edit_api(request, record_id):
    """
    Inline edit an attendance record (Status/Reason) and log it.
    """
    import json
    from django.utils.timezone import now
    from apps.attendance.models import AttendanceRecord
    from apps.audit.utils import audit
    
    if request.user.role not in ['ADMIN', 'TEACHER']:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
        
    try:
        data = json.loads(request.body)
        new_status = data.get('status')
        reason = data.get('reason', '')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON format.'}, status=400)
        
    valid_statuses = ['PRESENT', 'ABSENT', 'LATE', 'EXCUSED']
    if new_status not in valid_statuses:
        return JsonResponse({'success': False, 'error': f'Invalid status. Must be one of {valid_statuses}'}, status=400)
        
    try:
        record = get_object_or_404(AttendanceRecord.objects.select_related('session__subject', 'student'), id=record_id)
        
        # RBAC logic for edits
        if request.user.role != 'ADMIN':
            if record.session.status != 'OPEN':
                return JsonResponse({'success': False, 'error': 'Cannot edit attendance in a CLOSED session unless you are an ADMIN.'}, status=403)
            if record.session.subject and not record.session.subject.teachers.filter(id=request.user.id).exists():
                return JsonResponse({'success': False, 'error': 'You are not assigned to this subject.'}, status=403)
                
        if record.original_status is None:
            record.original_status = record.status 
            
        old_status = record.status
        record.status = new_status
        record.edited_by = request.user
        record.edited_at = now()
        record.reason = reason
        record.save()
        
        audit(request, 'ATTENDANCE_INLINE_EDIT', 'AttendanceRecord', str(record.id), 
              {'notes': f"Changed status from {old_status} to {new_status} for {record.student.university_roll_number}. Reason: {reason}"})
              
        return JsonResponse({'success': True, 'data': {'status': new_status, 'reason': reason, 'edited_by': request.user.username}})
    except Exception as e:
        import traceback
        error_msg = f"Edit Error: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return JsonResponse({'success': False, 'error': error_msg}, status=500)


@login_required
@require_GET
def student_attendance_stats_api(request, student_id):
    """
    GET /attendance/api/stats/student/<uuid>/
    Returns attendance percentage statistics for a student.
    """
    from apps.students.models import Student
    from .models import AttendanceSession, AttendanceRecord, Subject

    user = request.user

    if user.role == 'STUDENT' or getattr(user, 'is_student', lambda: False)():
        if not hasattr(user, 'student_profile') or str(user.student_profile.id) != str(student_id):
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    try:
        student = Student.objects.prefetch_related('enrolled_subjects').get(id=student_id)
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student not found.'}, status=404)

    if user.role == 'TEACHER' or getattr(user, 'is_teacher', lambda: False)():
        teacher_subject_ids = user.subjects.values_list('id', flat=True)
        if not student.enrolled_subjects.filter(id__in=teacher_subject_ids).exists():
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    section_id_filter = request.GET.get('section_id') # actually subject_id

    enrolled_subjects = student.enrolled_subjects.all()
    if section_id_filter:
        enrolled_subjects = enrolled_subjects.filter(id=section_id_filter)

    per_section = []
    total_occurred = 0
    total_attended = 0

    for subject in enrolled_subjects:
        occurred_sessions = AttendanceSession.objects.filter(
            subject=subject,
            status__in=['CLOSED', 'OPEN']
        )
        occurred_count = occurred_sessions.count()

        attended_count = AttendanceRecord.objects.filter(
            session__subject=subject,
            student=student,
            status='PRESENT'
        ).count()

        pct = round((attended_count / occurred_count) * 100, 1) if occurred_count > 0 else 0.0

        per_section.append({
            'section_id': str(subject.id),
            'section_name': str(subject),
            'course_code': subject.code,
            'occurred': occurred_count,
            'attended': attended_count,
            'pct': pct,
        })

        total_occurred += occurred_count
        total_attended += attended_count

    overall_pct = round((total_attended / total_occurred) * 100, 1) if total_occurred > 0 else 0.0

    return JsonResponse({
        'success': True,
        'data': {
            'student': {
                'id': str(student.id),
                'name': student.full_name,
                'roll_no': student.university_roll_number or student.student_id,
            },
            'sections_enrolled': enrolled_subjects.count(),
            'total_classes': total_occurred,
            'classes_attended': total_attended,
            'attendance_pct': overall_pct,
            'per_section': per_section,
        }
    })


@login_required
@require_GET
def attendance_session_ledger_api(request, session_id):
    """
    Returns an unpaginated JSON of all students assigned to this session.
    """
    from apps.attendance.models import AttendanceSession, AttendanceRecord
    from apps.students.models import Student
    
    session = get_object_or_404(AttendanceSession.objects.select_related('subject', 'teacher'), id=session_id)
    
    if session.subject:
        if not (request.user.role == 'ADMIN' or request.user in session.subject.teachers.all() or request.user == session.teacher):
            return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
            
    records = AttendanceRecord.objects.filter(session=session).select_related('student')
    record_map = { r.student_id: r for r in records }
    
    if session.subject:
        students = session.subject.enrolled_students.filter(enrollment_status='ACTIVE').order_by('full_name')
    else:
        students = []
        
    roster = []
    for s in students:
        rec = record_map.get(s.id)
        
        marked_at_str = None
        if rec and rec.marked_at:
            if rec.status != 'ABSENT' or rec.edited_by is not None:
                marked_at_str = localtime(rec.marked_at).strftime('%I:%M:%S %p')
                
        roster.append({
            'record_id': str(rec.id) if rec else None,
            'student_id': str(s.id),
            'full_name': s.full_name,
            'roll_no': s.university_roll_number or s.student_id,
            'photo_url': s.photos.filter(is_primary=True).first().image.url if s.photos.filter(is_primary=True).exists() else None,
            'status': rec.status if rec else 'ABSENT',
            'method': rec.verification_method if rec else None,
            'marked_at': marked_at_str,
            'face_match_score': rec.face_match_score if rec else None,
            'edited_by': rec.edited_by.username if rec and rec.edited_by else None,
            'has_reason': bool(rec.reason) if rec else False
        })
        
    return JsonResponse({
        'success': True,
        'data': {
            'total_expected': session.total_expected,
            'total_present': session.total_present,
            'status': session.status,
            'roster': roster
        }
    })


@require_POST
def close_open_sessions_api(request):
    """
    POST /attendance/api/browser-close-sessions/
    """
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'reason': 'anonymous'})

    from .models import AttendanceSession

    role = getattr(request.user, 'role', '')
    if role not in ('TEACHER', 'ADMIN'):
        return JsonResponse({'success': True, 'closed': 0})

    filter_kwargs = {'status': 'OPEN'}
    if role == 'TEACHER':
        filter_kwargs['teacher'] = request.user

    open_sessions = AttendanceSession.objects.filter(**filter_kwargs)
    count = open_sessions.count()

    open_sessions.update(
        status='CLOSED',
        closed_at=now(),
    )

    logger.info(f'[browser-close] {request.user} ({role}): auto-closed {count} open session(s).')
    return JsonResponse({'success': True, 'closed': count})


@login_required
@require_GET
def teacher_subjects_api(request):
    """
    GET /attendance/api/teacher-subjects/?year=1
    """
    year = request.GET.get('year')
    if not year:
        return JsonResponse({'success': False, 'error': 'No academic year id provided'})
        
    if getattr(request.user, 'role', '') not in ['TEACHER', 'ADMIN']:
        return JsonResponse({'success': True, 'subjects': []})
        
    from .models import Subject
    qs = Subject.objects.filter(academic_year_id=year)
    subjects = qs.distinct()
    
    data = [{'id': str(s.id), 'name': f"{s.code} - {s.name}"} for s in subjects]
    return JsonResponse({'success': True, 'subjects': data})

@login_required
@require_GET
def get_academic_years_api(request):
    """
    GET /attendance/api/academic-years/?class_id=1
    """
    class_id = request.GET.get('class_id')
    from .models import AcademicYear
    qs = AcademicYear.objects.all()
    if class_id:
        qs = qs.filter(academic_class_id=class_id)
    data = [{'id': str(y.id), 'name': y.year_name} for y in qs.order_by('year_name')]
    return JsonResponse({'success': True, 'years': data})

@login_required
@require_GET
def get_subjects_api(request):
    """
    GET /attendance/api/subjects/?year_id=1
    """
    year_id = request.GET.get('year_id')
    from .models import Subject
    qs = Subject.objects.all()
    if year_id:
        qs = qs.filter(academic_year_id=year_id)
    data = [{'id': str(s.id), 'name': f"{s.code} - {s.name}"} for s in qs.order_by('name')]
    return JsonResponse({'success': True, 'subjects': data})
