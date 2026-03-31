"""
Core reporting calculation engine for SmartAttend.
All metrics are derived at query time from closed AttendanceSessions.
"""
from datetime import timedelta, date
from django.db.models import Count, Q, Avg, FloatField, ExpressionWrapper, F
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncYear
from django.utils import timezone

from .models import AttendanceRecord, AttendanceSession, Section
from apps.students.models import Student


# ── Helpers ──────────────────────────────────────────────────────────────────

def apply_relative_preset(preset: str):
    """Return (from_date, to_date) for a named preset."""
    today = timezone.localdate()
    if preset == 'last_7':
        return today - timedelta(days=6), today
    elif preset == 'last_30':
        return today - timedelta(days=29), today
    elif preset == 'last_90':
        return today - timedelta(days=89), today
    elif preset == 'this_month':
        return today.replace(day=1), today
    elif preset == 'this_year':
        return today.replace(month=1, day=1), today
    return None, None


def _trunc_fn(granularity: str):
    return {
        'daily':   TruncDate,
        'weekly':  TruncWeek,
        'monthly': TruncMonth,
        'yearly':  TruncYear,
    }.get(granularity, TruncDate)


def _closed_sessions_qs(section=None, from_date=None, to_date=None):
    """Base queryset of closed sessions, optionally scoped to a section and date range."""
    qs = AttendanceSession.objects.filter(status='CLOSED')
    if section:
        qs = qs.filter(section=section)
    if from_date:
        qs = qs.filter(started_at__date__gte=from_date)
    if to_date:
        qs = qs.filter(started_at__date__lte=to_date)
    return qs


# ── Per-Student Summary ───────────────────────────────────────────────────────

def get_student_summary(student, from_date=None, to_date=None, granularity='daily'):
    """
    Returns a dict with attendance metrics for a single student.
    total_classes_offered = closed sessions for student's section in period.
    """
    section = student.section

    # Total classes offered (closed sessions in student's section)
    total_offered = _closed_sessions_qs(section=section, from_date=from_date, to_date=to_date).count()

    # Student's attendance records within those closed sessions
    records = AttendanceRecord.objects.filter(
        student=student,
        session__status='CLOSED',
    )
    if from_date:
        records = records.filter(session__started_at__date__gte=from_date)
    if to_date:
        records = records.filter(session__started_at__date__lte=to_date)

    attended = records.filter(status='PRESENT').count()
    late = records.filter(status='LATE').count()
    excused = records.filter(status='EXCUSED').count()
    absent = records.filter(status='ABSENT').count()

    attendance_rate = round((attended / total_offered * 100), 1) if total_offered > 0 else 0.0

    # Cohort average: all students in same section, same period
    cohort_avg = _cohort_avg_rate(section, from_date, to_date)
    delta = round(attendance_rate - cohort_avg, 1)

    # Trend data (bucketed by granularity)
    trend = _student_trend(student, from_date, to_date, granularity)

    # Detailed history
    all_sessions = _closed_sessions_qs(section=section, from_date=from_date, to_date=to_date).order_by('-started_at')
    record_map = { r.session_id: r for r in records }
    
    history = []
    for s in all_sessions:
        rec = record_map.get(s.id)
        status = rec.status if rec else 'ABSENT'
        method = rec.verification_method if rec else '-'
        marked_at = rec.marked_at if rec else None
        
        history.append({
            'session_id': str(s.id),
            'date': s.started_at.strftime('%Y-%m-%d %I:%M %p') if getattr(s, 'started_at', None) else 'Unknown',
            'status': status,
            'method': method,
            'marked_at': marked_at.strftime('%I:%M %p') if marked_at else '-'
        })

    return {
        'student': student,
        'section': section,
        'total_offered': total_offered,
        'attended': attended,
        'late': late,
        'excused': excused,
        'absent': absent,
        'missed': absent + late,
        'attendance_rate': attendance_rate,
        'cohort_avg': cohort_avg,
        'delta_vs_cohort': delta,
        'trend': trend,
        'history': history,
    }


def _cohort_avg_rate(section, from_date, to_date):
    """Average attendance rate for all students in a section over the given period."""
    if not section:
        return 0.0
    total_offered = _closed_sessions_qs(section=section, from_date=from_date, to_date=to_date).count()
    if total_offered == 0:
        return 0.0

    students = section.students.filter(enrollment_status='ACTIVE')
    rates = []
    for s in students:
        records = AttendanceRecord.objects.filter(student=s, session__status='CLOSED', session__section=section)
        if from_date:
            records = records.filter(session__started_at__date__gte=from_date)
        if to_date:
            records = records.filter(session__started_at__date__lte=to_date)
        attended = records.filter(status='PRESENT').count()
        rates.append((attended / total_offered) * 100)

    return round(sum(rates) / len(rates), 1) if rates else 0.0


def _student_trend(student, from_date, to_date, granularity):
    """Returns list of {bucket, rate, attended, total} dicts for chart rendering."""
    trunc = _trunc_fn(granularity)
    section = student.section

    # Sessions bucketed
    session_counts = (
        _closed_sessions_qs(section=section, from_date=from_date, to_date=to_date)
        .annotate(bucket=trunc('started_at'))
        .values('bucket')
        .annotate(total=Count('id'))
        .order_by('bucket')
    )

    # Attendance bucketed
    records = AttendanceRecord.objects.filter(
        student=student,
        session__status='CLOSED',
    )
    if section:
        records = records.filter(session__section=section)
    if from_date:
        records = records.filter(session__started_at__date__gte=from_date)
    if to_date:
        records = records.filter(session__started_at__date__lte=to_date)

    attended_counts = (
        records.filter(status='PRESENT')
        .annotate(bucket=trunc('session__started_at'))
        .values('bucket')
        .annotate(attended=Count('id'))
        .order_by('bucket')
    )

    # Merge buckets
    sessions_map = {entry['bucket']: entry['total'] for entry in session_counts}
    attended_map = {entry['bucket']: entry['attended'] for entry in attended_counts}

    result = []
    for bucket, total in sorted(sessions_map.items()):
        if bucket is None:
            continue
        att = attended_map.get(bucket, 0)
        rate = round((att / total * 100), 1) if total > 0 else 0.0
        result.append({
            'bucket': bucket.strftime('%Y-%m-%d') if hasattr(bucket, 'strftime') else str(bucket),
            'rate': rate,
            'attended': att,
            'total': total,
        })
    return result


# ── All Students in a Section ─────────────────────────────────────────────────

def get_section_student_rows(section, from_date=None, to_date=None, sort_by='full_name'):
    """
    Returns a list of dicts (one per student in section) with summary metrics.
    Used for the "Student Overview" table tab.
    """
    total_offered = _closed_sessions_qs(section=section, from_date=from_date, to_date=to_date).count()
    students = section.students.filter(enrollment_status='ACTIVE').order_by('full_name')

    rows = []
    for student in students:
        records = AttendanceRecord.objects.filter(
            student=student,
            session__status='CLOSED',
            session__section=section,
        )
        if from_date:
            records = records.filter(session__started_at__date__gte=from_date)
        if to_date:
            records = records.filter(session__started_at__date__lte=to_date)

        attended = records.filter(status='PRESENT').count()
        missed = records.filter(status__in=['ABSENT', 'LATE']).count()
        rate = round((attended / total_offered * 100), 1) if total_offered > 0 else 0.0

        rows.append({
            'student_id': str(student.id),
            'name': student.full_name,
            'roll_no': student.university_roll_number or student.student_id,
            'total_offered': total_offered,
            'attended': attended,
            'missed': missed,
            'rate': rate,
        })

    # Compute cohort average for delta
    all_rates = [r['rate'] for r in rows]
    cohort_avg = round(sum(all_rates) / len(all_rates), 1) if all_rates else 0.0
    for row in rows:
        row['delta'] = round(row['rate'] - cohort_avg, 1)
        row['cohort_avg'] = cohort_avg

    # Sort
    reverse = sort_by.startswith('-')
    key = sort_by.lstrip('-')
    valid_keys = {'name', 'rate', 'attended', 'missed', 'roll_no'}
    if key in valid_keys:
        rows.sort(key=lambda r: r.get(key, ''), reverse=reverse)

    return rows


# ── Top / Bottom Performers ───────────────────────────────────────────────────

def get_top_bottom_performers(section, from_date=None, to_date=None, n=5):
    rows = get_section_student_rows(section, from_date, to_date)
    rows_sorted = sorted(rows, key=lambda r: r['rate'], reverse=True)
    return {
        'top': rows_sorted[:n],
        'bottom': list(reversed(rows_sorted[-n:])) if len(rows_sorted) >= n else list(reversed(rows_sorted)),
    }


# ── Section Summary ───────────────────────────────────────────────────────────

def get_section_summary(section, from_date=None, to_date=None):
    total_sessions = _closed_sessions_qs(section=section, from_date=from_date, to_date=to_date).count()
    records = AttendanceRecord.objects.filter(
        session__status='CLOSED', session__section=section
    )
    if from_date:
        records = records.filter(session__started_at__date__gte=from_date)
    if to_date:
        records = records.filter(session__started_at__date__lte=to_date)

    total_records = records.count()
    total_present = records.filter(status='PRESENT').count()
    overall_rate = round((total_present / total_records * 100), 1) if total_records > 0 else 0.0

    return {
        'section': section,
        'total_sessions': total_sessions,
        'total_records': total_records,
        'total_present': total_present,
        'overall_rate': overall_rate,
    }


# ── Multi-Section (Admin view) ────────────────────────────────────────────────

def get_all_sections_summary(teacher=None, from_date=None, to_date=None):
    """Returns list of section summaries, optionally scoped to a teacher."""
    sections = Section.objects.all()
    if teacher:
        sections = sections.filter(teachers=teacher)

    summaries = []
    for sec in sections:
        s = get_section_summary(sec, from_date, to_date)
        summaries.append(s)
    return summaries
