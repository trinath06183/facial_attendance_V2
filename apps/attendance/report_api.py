"""
REST API endpoints for the Enhanced Reporting feature.
All data returns JSON. Exports are handled by report_export.py via views.py.
"""
import math
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import AttendanceSession, Section
from .reports import (
    get_student_summary,
    get_section_student_rows,
    get_top_bottom_performers,
    get_all_sections_summary,
    apply_relative_preset,
)
from apps.students.models import Student


def _parse_dates(request):
    """Parse fromDate/toDate or preset from request.GET."""
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


def _section_access_check(user, section):
    """Returns True if user is allowed to view this section's data."""
    if user.role == 'ADMIN' or getattr(user, 'is_admin', lambda: False)():
        return True
    if user.role == 'TEACHER' or getattr(user, 'is_teacher', lambda: False)():
        return section.teachers.filter(id=user.id).exists()
    return False


# ── Student Report ────────────────────────────────────────────────────────────

@login_required
@require_GET
def report_student_api(request, student_id):
    """
    GET /attendance/api/reports/student/<uuid>/
    Returns aggregated metrics for a single student.
    """
    user = request.user

    # Students can only view their own
    if user.role == 'STUDENT' or getattr(user, 'is_student', lambda: False)():
        if not hasattr(user, 'student_profile') or str(user.student_profile.id) != str(student_id):
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    try:
        student = Student.objects.select_related('section').get(id=student_id)
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student not found.'}, status=404)

    # Teachers can only see students in their sections
    if user.role == 'TEACHER' or getattr(user, 'is_teacher', lambda: False)():
        if student.section and not student.section.teachers.filter(id=user.id).exists():
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
                'section': str(student.section) if student.section else None,
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


# ── Section Students Table ────────────────────────────────────────────────────

@login_required
@require_GET
def report_section_api(request, section_id):
    """
    GET /attendance/api/reports/section/<uuid>/
    Returns all-student rows for a section (for the overview table).
    """
    user = request.user

    try:
        section = Section.objects.get(id=section_id)
    except Section.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Section not found.'}, status=404)

    if not _section_access_check(user, section):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    from_date, to_date = _parse_dates(request)
    sort_by = request.GET.get('sort', 'name')

    rows = get_section_student_rows(section, from_date=from_date, to_date=to_date, sort_by=sort_by)

    return JsonResponse({
        'success': True,
        'data': {
            'section': str(section),
            'rows': rows,
            'total_students': len(rows),
        }
    })


# ── Top / Bottom Performers ───────────────────────────────────────────────────

@login_required
@require_GET
def report_top_bottom_api(request, section_id):
    """
    GET /attendance/api/reports/top-bottom/<uuid>/
    Returns top 5 and bottom 5 performers for a section.
    """
    user = request.user

    try:
        section = Section.objects.get(id=section_id)
    except Section.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Section not found.'}, status=404)

    if not _section_access_check(user, section):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    from_date, to_date = _parse_dates(request)
    result = get_top_bottom_performers(section, from_date=from_date, to_date=to_date)

    return JsonResponse({'success': True, 'data': result})


# ── All Sections Summary (Admin / Teacher) ────────────────────────────────────

@login_required
@require_GET
def report_overview_api(request):
    """
    GET /attendance/api/reports/overview/
    Returns section-level summary list for dashboard cards.
    """
    user = request.user
    from_date, to_date = _parse_dates(request)

    if user.role == 'ADMIN' or getattr(user, 'is_admin', lambda: False)():
        summaries = get_all_sections_summary(from_date=from_date, to_date=to_date)
    elif user.role == 'TEACHER' or getattr(user, 'is_teacher', lambda: False)():
        summaries = get_all_sections_summary(teacher=user, from_date=from_date, to_date=to_date)
    else:
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    data = []
    for s in summaries:
        data.append({
            'section_id': str(s['section'].id),
            'section_name': str(s['section']),
            'total_sessions': s['total_sessions'],
            'overall_rate': s['overall_rate'],
        })

    return JsonResponse({'success': True, 'data': data})
