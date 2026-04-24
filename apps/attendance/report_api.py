"""
rest api endpoints for the enhanced reporting feature.
all data returns json. exports are handled by report_export.py via views.py.
"""
import math
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import AttendanceSession, Subject
from .reports import (
    get_student_summary,
    get_subject_student_rows,
    get_top_bottom_performers,
    get_all_subjects_summary,
    apply_relative_preset,
)
from apps.students.models import Student


def _parse_dates(request):
    """parse fromdate/todate or preset from request.get."""
    preset = request.GET.get('preset')
    if preset:
        return apply_relative_preset(preset)

    from_date = None
    to_date = None
    from_raw = request.GET.get('fromDate')
    to_raw = request.GET.get('toDate')
    try:
        if from_raw:
            from_date = datetime.strptime(from_raw, '%Y-%m-%d').date()
        if to_raw:
            to_date = datetime.strptime(to_raw, '%Y-%m-%d').date()
    except ValueError:
        pass
    return from_date, to_date


def _subject_access_check(user, subject):
    """returns true if user is allowed to view this subject's data."""
    if user.role == 'ADMIN' or getattr(user, 'is_admin', lambda: False)():
        return True
    if user.role == 'TEACHER' or getattr(user, 'is_teacher', lambda: False)():
        return subject.teachers.filter(id=user.id).exists()
    return False


#  student report 

@login_required
@require_GET
def report_student_api(request, student_id):
    """
    get /attendance/api/reports/student/<uuid>/
    returns aggregated metrics for a single student.
    """
    user = request.user

    # students can only view their own
    if user.role == 'STUDENT' or getattr(user, 'is_student', lambda: False)():
        if not hasattr(user, 'student_profile') or str(user.student_profile.id) != str(student_id):
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    try:
        student = Student.objects.prefetch_related('enrolled_subjects').get(id=student_id)
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student not found.'}, status=404)

    # teachers can only see students in subjects they teach
    if user.role == 'TEACHER' or getattr(user, 'is_teacher', lambda: False)():
        teacher_subjects = user.subjects.values_list('id', flat=True)
        if not student.enrolled_subjects.filter(id__in=teacher_subjects).exists():
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    from_date, to_date = _parse_dates(request)
    granularity = request.GET.get('granularity', 'daily')

    summary = get_student_summary(student, from_date=from_date, to_date=to_date, granularity=granularity)

    return JsonResponse({
        'success': True,
        'data': {
            'student': {
                'id': str(student.id),
                'name': student.full_name,
                'roll_no': student.university_roll_number or student.student_id,
                'section': ", ".join([s.name for s in student.enrolled_subjects.all()]) if student.enrolled_subjects.exists() else None,
            },
            'metrics': {
                'total_offered': summary['total_offered'],
                'attended': summary['attended'],
                'missed': summary['missed'],
                'late': summary['late'],
                'excused': summary['excused'],
                'attendance_rate': summary['attendance_rate'],
                'cohort_avg': summary['cohort_avg'],
                'delta_vs_cohort': summary['delta_vs_cohort'],
            },
            'trend': summary['trend'],
            'history': summary.get('history', []),
        }
    })


#  subject students table 

@login_required
@require_GET
def report_section_api(request, section_id):
    """
    get /attendance/api/reports/section/<uuid>/
    returns all-student rows for a subject (for the overview table).
    using old section_id in url to prevent breaking frontend right now
    """
    user = request.user

    try:
        subject = Subject.objects.get(id=section_id)
    except Subject.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Subject not found.'}, status=404)

    if not _subject_access_check(user, subject):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    from_date, to_date = _parse_dates(request)
    sort_by = request.GET.get('sort', 'name')

    rows = get_subject_student_rows(subject, from_date=from_date, to_date=to_date, sort_by=sort_by)

    return JsonResponse({
        'success': True,
        'data': {
            'section': str(subject),
            'rows': rows,
            'total_students': len(rows),
        }
    })


#  top / bottom performers 

@login_required
@require_GET
def report_top_bottom_api(request, section_id):
    """
    get /attendance/api/reports/top-bottom/<uuid>/
    returns top 5 and bottom 5 performers for a subject.
    """
    user = request.user

    try:
        subject = Subject.objects.get(id=section_id)
    except Subject.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Subject not found.'}, status=404)

    if not _subject_access_check(user, subject):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    from_date, to_date = _parse_dates(request)
    result = get_top_bottom_performers(subject, from_date=from_date, to_date=to_date)

    return JsonResponse({'success': True, 'data': result})


#  all subjects summary (admin / teacher) 

@login_required
@require_GET
def report_overview_api(request):
    """
    get /attendance/api/reports/overview/
    returns subject-level summary list for dashboard cards.
    """
    user = request.user
    from_date, to_date = _parse_dates(request)

    if user.role == 'ADMIN' or getattr(user, 'is_admin', lambda: False)():
        summaries = get_all_subjects_summary(from_date=from_date, to_date=to_date)
    elif user.role == 'TEACHER' or getattr(user, 'is_teacher', lambda: False)():
        summaries = get_all_subjects_summary(teacher=user, from_date=from_date, to_date=to_date)
    else:
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    data = []
    for s in summaries:
        data.append({
            'section_id': str(s['subject'].id),
            'section_name': str(s['subject']),
            'total_sessions': s['total_sessions'],
            'overall_rate': s['overall_rate'],
        })

    return JsonResponse({'success': True, 'data': data})
