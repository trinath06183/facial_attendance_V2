from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from apps.students.models import Student
from apps.attendance.models import AttendanceSession, AttendanceRecord
from apps.attendance.analytics import get_student_analytics, get_admin_analytics
from datetime import datetime
from django.utils import timezone


@login_required
def dashboard(request):
    user = request.user
    ctx = {}

    if user.is_admin():
        # High level system overview for Admin Dashboard
        analytics = get_admin_analytics()
        ctx['total_students'] = Student.objects.filter(enrollment_status='ACTIVE').count()
        ctx['total_sessions'] = analytics['total_sessions']
        ctx['system_presence_rate'] = analytics['system_presence_rate']
        ctx['open_sessions'] = AttendanceSession.objects.filter(status='OPEN').count()
        ctx['recent_sessions'] = AttendanceSession.objects.order_by('-started_at')[:8]
        return render(request, 'dashboards/admin.html', ctx)

    elif user.is_teacher():
        # Teacher Dashboard
        my_sections = user.sections.all()
        ctx['my_sections'] = my_sections
        ctx['open_sessions'] = AttendanceSession.objects.filter(
            section__in=my_sections, status='OPEN'
        )
        ctx['recent_sessions'] = AttendanceSession.objects.filter(
            section__in=my_sections
        ).order_by('-started_at')[:8]
        return render(request, 'dashboards/teacher.html', ctx)

    elif user.is_student():
        # Student Dashboard
        if hasattr(user, 'student_profile') and user.student_profile:
            analytics = get_student_analytics(user.student_profile)
            ctx['presence_percentage'] = analytics['presence_percentage']
            ctx['classes_missed'] = analytics['absent_classes']
            ctx['recent_attendance'] = analytics['recent_history']
            ctx['student'] = user.student_profile
            # Courses for the embedded logs viewer filter
            from apps.attendance.models import AttendanceRecord
            ctx['log_courses'] = (
                AttendanceRecord.objects
                .filter(student=user.student_profile)
                .values_list('session__section__course_code', flat=True)
                .distinct()
                .order_by('session__section__course_code')
            )
        else:
            ctx['error'] = "No student profile linked to this account."
            
        return render(request, 'dashboards/student.html', ctx)

    # Fallback
    return render(request, 'dashboards/dashboard.html', ctx)
