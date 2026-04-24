"""
core reporting calculation engine for smartattend.
all metrics are derived at query time from closed attendancesessions.
"""
from datetime import timedelta, date
from django.db.models import Count, Q, Avg, FloatField, ExpressionWrapper, F
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncYear
from django.utils import timezone

from .models import AttendanceRecord, AttendanceSession, Subject
from apps.students.models import Student


#  helpers 

def apply_relative_preset(preset: str):
    """return (from_date, to_date) for a named preset."""
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


def _closed_sessions_qs(subject=None, from_date=None, to_date=None):
    """base queryset of closed sessions, optionally scoped to a subject and date range."""
    qs = AttendanceSession.objects.filter(status='CLOSED')
    if subject:
        qs = qs.filter(subject=subject)
    if from_date:
        qs = qs.filter(started_at__date__gte=from_date)
    if to_date:
        qs = qs.filter(started_at__date__lte=to_date)
    return qs


#  per-student summary 

def get_student_summary(student, from_date=None, to_date=None, granularity='daily'):
    """
    returns a dict with attendance metrics for a single student.
    total_classes_offered = closed sessions for student's subjects in period.
    """
    subjects = student.enrolled_subjects.all()

    # total classes offered (closed sessions in student's subjects)
    total_offered = _closed_sessions_qs(from_date=from_date, to_date=to_date).filter(subject__in=subjects).count()

    # student's attendance records within those closed sessions
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

    # cohort average: all students in same subjects, same period
    cohort_avg = _cohort_avg_rate(subjects, from_date, to_date)
    delta = round(attendance_rate - cohort_avg, 1)

    # trend data (bucketed by granularity)
    trend = _student_trend(student, subjects, from_date, to_date, granularity)

    # detailed history
    all_sessions = _closed_sessions_qs(from_date=from_date, to_date=to_date).filter(subject__in=subjects).order_by('-started_at')
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
        'subjects': subjects,
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


def _cohort_avg_rate(subjects, from_date, to_date):
    """average attendance rate for all students in the given subjects over the given period."""
    if not subjects:
        return 0.0
    total_offered = _closed_sessions_qs(from_date=from_date, to_date=to_date).filter(subject__in=subjects).count()
    if total_offered == 0:
        return 0.0

    students = Student.objects.filter(enrolled_subjects__in=subjects, enrollment_status='ACTIVE').distinct()
    
    rates = []
    for s in students:
        records = AttendanceRecord.objects.filter(student=s, session__status='CLOSED', session__subject__in=subjects)
        if from_date:
            records = records.filter(session__started_at__date__gte=from_date)
        if to_date:
            records = records.filter(session__started_at__date__lte=to_date)
        attended = records.filter(status='PRESENT').count()
        rates.append((attended / total_offered) * 100)

    return round(sum(rates) / len(rates), 1) if rates else 0.0


def _student_trend(student, subjects, from_date, to_date, granularity):
    """returns list of {bucket, rate, attended, total} dicts for chart rendering."""
    trunc = _trunc_fn(granularity)

    # sessions bucketed
    session_counts = (
        _closed_sessions_qs(from_date=from_date, to_date=to_date).filter(subject__in=subjects)
        .annotate(bucket=trunc('started_at'))
        .values('bucket')
        .annotate(total=Count('id'))
        .order_by('bucket')
    )

    # attendance bucketed
    records = AttendanceRecord.objects.filter(
        student=student,
        session__status='CLOSED',
    )
    if subjects:
        records = records.filter(session__subject__in=subjects)
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

    # merge buckets
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


#  all students in a subject 

def get_subject_student_rows(subject, from_date=None, to_date=None, sort_by='full_name'):
    """
    returns a list of dicts (one per student in subject) with summary metrics.
    used for the "student overview" table tab.
    """
    total_offered = _closed_sessions_qs(subject=subject, from_date=from_date, to_date=to_date).count()
    if subject:
        students = subject.enrolled_students.filter(enrollment_status='ACTIVE').order_by('full_name')
    else:
        students = Student.objects.none()

    rows = []
    for student in students:
        records = AttendanceRecord.objects.filter(
            student=student,
            session__status='CLOSED',
            session__subject=subject,
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

    # compute cohort average for delta
    all_rates = [r['rate'] for r in rows]
    cohort_avg = round(sum(all_rates) / len(all_rates), 1) if all_rates else 0.0
    for row in rows:
        row['delta'] = round(row['rate'] - cohort_avg, 1)
        row['cohort_avg'] = cohort_avg

    # sort
    reverse = sort_by.startswith('-')
    key = sort_by.lstrip('-')
    valid_keys = {'name', 'rate', 'attended', 'missed', 'roll_no'}
    if key in valid_keys:
        rows.sort(key=lambda r: r.get(key, ''), reverse=reverse)

    return rows


#  top / bottom performers 

def get_top_bottom_performers(subject, from_date=None, to_date=None, n=5):
    rows = get_subject_student_rows(subject, from_date, to_date)
    rows_sorted = sorted(rows, key=lambda r: r['rate'], reverse=True)
    return {
        'top': rows_sorted[:n],
        'bottom': list(reversed(rows_sorted[-n:])) if len(rows_sorted) >= n else list(reversed(rows_sorted)),
    }


#  subject summary 

def get_subject_summary(subject, from_date=None, to_date=None):
    total_sessions = _closed_sessions_qs(subject=subject, from_date=from_date, to_date=to_date).count()
    records = AttendanceRecord.objects.filter(
        session__status='CLOSED', session__subject=subject
    )
    if from_date:
        records = records.filter(session__started_at__date__gte=from_date)
    if to_date:
        records = records.filter(session__started_at__date__lte=to_date)

    total_records = records.count()
    total_present = records.filter(status='PRESENT').count()
    overall_rate = round((total_present / total_records * 100), 1) if total_records > 0 else 0.0

    return {
        'subject': subject,
        'total_sessions': total_sessions,
        'total_records': total_records,
        'total_present': total_present,
        'overall_rate': overall_rate,
    }


#  multi-subject (admin view) 

def get_all_subjects_summary(teacher=None, from_date=None, to_date=None):
    """returns list of subject summaries, optionally scoped to a teacher."""
    subjects = Subject.objects.all()
    if teacher:
        subjects = subjects.filter(teachers=teacher)

    summaries = []
    for sub in subjects:
        s = get_subject_summary(sub, from_date, to_date)
        summaries.append(s)
    return summaries
