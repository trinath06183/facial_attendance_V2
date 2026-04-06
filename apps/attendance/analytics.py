from django.db.models import Count, Q, Avg, F
from django.utils import timezone
from datetime import datetime, timedelta
from .models import AttendanceRecord, AttendanceSession, Subject

def get_student_analytics(student, start_date=None, end_date=None):
    """
    Returns analytics dictionary for a specific student.
    Filter by date if provided.
    """
    records = AttendanceRecord.objects.filter(student=student)
    
    if start_date:
        records = records.filter(session__started_at__date__gte=start_date)
    if end_date:
        records = records.filter(session__started_at__date__lte=end_date)
        
    total_classes = records.count()
    present_classes = records.filter(status='PRESENT').count()
    absent_classes = records.filter(status__in=['ABSENT', 'LATE']).count()
    
    presence_percentage = 0
    if total_classes > 0:
        presence_percentage = round((present_classes / total_classes) * 100, 1)
        
    # Get last 5 records for quick history
    recent_history = records.order_by('-marked_at')[:5]
    
    # Trend data: presence by date for charts
    from django.db.models.functions import TruncDate
    trend_qs = records.annotate(
        date=TruncDate('session__started_at')
    ).values('date').annotate(
        total=Count('id'),
        present=Count('id', filter=Q(status='PRESENT'))
    ).order_by('date')
    
    trend_labels = []
    trend_rates = []
    for entry in trend_qs:
        if entry['date']:
            date_str = entry['date'].strftime('%b %d')
            rate = round((entry['present'] / entry['total']) * 100, 1) if entry['total'] > 0 else 0
            trend_labels.append(date_str)
            trend_rates.append(rate)
    
    return {
        'total_classes': total_classes,
        'present_classes': present_classes,
        'absent_classes': absent_classes,
        'presence_percentage': presence_percentage,
        'recent_history': recent_history,
        'trend_labels': trend_labels,
        'trend_rates': trend_rates,
    }

def get_admin_analytics(start_date=None, end_date=None, academic_class_id=None, academic_year_id=None, subject_id=None):
    """
    Returns system-wide or filtered analytics for Admin/Teacher dashboard.
    """
    sessions = AttendanceSession.objects.all()
    records = AttendanceRecord.objects.all()
    
    if start_date:
        sessions = sessions.filter(started_at__date__gte=start_date)
        records = records.filter(session__started_at__date__gte=start_date)
    if end_date:
        sessions = sessions.filter(started_at__date__lte=end_date)
        records = records.filter(session__started_at__date__lte=end_date)
        
    if academic_class_id:
        sessions = sessions.filter(subject__academic_year__academic_class_id=academic_class_id)
        records = records.filter(session__subject__academic_year__academic_class_id=academic_class_id)
        
    if academic_year_id:
        sessions = sessions.filter(subject__academic_year_id=academic_year_id)
        records = records.filter(session__subject__academic_year_id=academic_year_id)
        
    if subject_id:
        sessions = sessions.filter(subject_id=subject_id)
        records = records.filter(session__subject_id=subject_id)

    total_sessions = sessions.count()
    total_records = records.count()
    overall_presence = records.filter(status='PRESENT').count()
    
    system_presence_rate = 0
    if total_records > 0:
        system_presence_rate = round((overall_presence / total_records) * 100, 1)

    # Calculate trend grouped by date
    from django.db.models.functions import TruncDate
    trend_qs = records.annotate(
        date=TruncDate('session__started_at')
    ).values('date').annotate(
        total=Count('id'),
        present=Count('id', filter=Q(status='PRESENT'))
    ).order_by('date')
    
    trend_labels = []
    trend_rates = []
    for entry in trend_qs:
        if entry['date']:
            date_str = entry['date'].strftime('%b %d')
            rate = round((entry['present'] / entry['total']) * 100, 1) if entry['total'] > 0 else 0
            trend_labels.append(date_str)
            trend_rates.append(rate)

    return {
        'total_sessions': total_sessions,
        'total_records': total_records,
        'system_presence_rate': system_presence_rate,
        'trend_labels': trend_labels,
        'trend_rates': trend_rates,
    }
