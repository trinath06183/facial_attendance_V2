import math
import logging
import json
from datetime import datetime
from django.utils.timezone import now

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
        'session__section',
        'session__section__subject',
        'session__teacher'
    )
    
    # Role-Based Access Control Filtering
    if user.role == 'STUDENT' or getattr(user, 'is_student', lambda: False)():
        # Students can only see their own records
        if not hasattr(user, 'student_profile'):
            return None, JsonResponse({'success': False, 'error': 'No linked student profile.'}, status=403)
        qs = qs.filter(student=user.student_profile)
        
    elif user.role == 'TEACHER' or getattr(user, 'is_teacher', lambda: False)():
        # Teachers can see sessions they created OR sessions in sections they are assigned to
        qs = qs.filter(
            session__section__teachers=user
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
        qs = qs.filter(session__section__course_code=course_id)
        
    class_id = request.GET.get('classId')
    if class_id:
        qs = qs.filter(session__section__section_identifier=class_id)
        
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
        'course': 'session__section__course_code',
        '-course': '-session__section__course_code',
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
        # Instead of going to the last page, return an empty array if requested out of bounds
        page_obj = paginator.page(paginator.num_pages) if paginator.num_pages > 0 else []
        page = paginator.num_pages
        if int(request.GET.get('page', 1)) > paginator.num_pages and paginator.num_pages > 0:
            page_obj = [] # If asking completely out of bounds, return empty list
        
    # --- Serialization ---
    records_data = []
    
    # If page_obj is empty list, iterate over []
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
                'code': record.session.section.course_code,
                'name': record.session.section.course_name
            },
            'class_section': record.session.section.section_identifier,
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
def student_search_api(request):
    """
    Finds students by name or roll number for manual attendance override.
    """
    query = request.GET.get('q', '').strip()
    section_id = request.GET.get('section_id')
    
    if not query or len(query) < 2:
        return JsonResponse({'success': True, 'data': []})
        
    from apps.students.models import Student
    
    qs = Student.objects.filter(
        Q(full_name__icontains=query) | 
        Q(university_roll_number__icontains=query) |
        Q(student_id__icontains=query)
    )
    
    if section_id:
        qs = qs.filter(subjects__id=section_id)
        
    # Limit results to top 10 for performance in dropdowns
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
    Expects JSON: { "student_id": "uuid..." }
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
        
    if not student.subjects.filter(id=session.section_id).exists():
        return JsonResponse({'success': False, 'error': 'Student not in this section.'})
        
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
    Expects JSON: { "status": "PRESENT"|"ABSENT"|"LATE"|"EXCUSED", "reason": "Text..." }
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
        record = get_object_or_404(AttendanceRecord.objects.select_related('session__section', 'student'), id=record_id)
        
        # RBAC logic for edits
        if request.user.role != 'ADMIN':
            if record.session.status != 'OPEN':
                return JsonResponse({'success': False, 'error': 'Cannot edit attendance in a CLOSED session unless you are an ADMIN.'}, status=403)
            if not record.session.section.teachers.filter(id=request.user.id).exists():
                return JsonResponse({'success': False, 'error': 'You are not assigned to this section.'}, status=403)
                
        # Stash original properties before mutation
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
def attendance_session_ledger_api(request, session_id):
    """
    Returns an unpaginated JSON of all students assigned to this session along with 
    their current AttendanceRecord. Used for event-driven dashboard hydration.
    """
    from apps.attendance.models import AttendanceSession, AttendanceRecord
    from apps.students.models import Student
    
    session = get_object_or_404(AttendanceSession.objects.select_related('section', 'teacher'), id=session_id)
    
    # Ensure permission
    if not (request.user.role == 'ADMIN' or request.user in session.section.teachers.all()):
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
        
    records = AttendanceRecord.objects.filter(session=session).select_related('student')
    record_map = { r.student_id: r for r in records }
    
    students = session.section.students.filter(enrollment_status='ACTIVE').order_by('full_name')
    
    roster = []
    for s in students:
        rec = record_map.get(s.id)
        roster.append({
            'record_id': str(rec.id) if rec else None,
            'student_id': str(s.id),
            'full_name': s.full_name,
            'roll_no': s.university_roll_number or s.student_id,
            'photo_url': s.photos.filter(is_primary=True).first().image.url if s.photos.filter(is_primary=True).exists() else None,
            'status': rec.status if rec else 'ABSENT',
            'method': rec.verification_method if rec else None,
            'marked_at': rec.marked_at.strftime('%I:%M:%S %p') if rec else None,
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
