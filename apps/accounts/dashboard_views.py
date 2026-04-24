from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from apps.students.models import Student
from apps.attendance.models import AttendanceSession, AttendanceRecord
from apps.attendance.analytics import get_student_analytics, get_admin_analytics
from datetime import datetime
from django.utils import timezone


@login_required
def dashboard(request):
    user = request.user

    # guard: student must set a new password before accessing any dashboard page
    if user.role == 'STUDENT' and user.must_change_password:
        return redirect('student_first_login_change_password')

    ctx = {}

    if user.is_admin():
        # high level system overview for admin dashboard
        analytics = get_admin_analytics()
        ctx['total_students'] = Student.objects.filter(enrollment_status='ACTIVE').count()
        ctx['total_sessions'] = analytics['total_sessions']
        ctx['system_presence_rate'] = analytics['system_presence_rate']
        ctx['open_sessions'] = AttendanceSession.objects.filter(status='OPEN').count()
        ctx['recent_sessions'] = AttendanceSession.objects.order_by('-started_at')[:8]
        return render(request, 'dashboards/admin.html', ctx)

    elif user.is_teacher():
        # teacher dashboard
        my_subjects = user.subjects.all()
        ctx['my_sections'] = my_subjects
        ctx['open_sessions'] = AttendanceSession.objects.filter(
            subject__in=my_subjects, status='OPEN'
        )
        ctx['recent_sessions'] = AttendanceSession.objects.filter(
            subject__in=my_subjects
        ).order_by('-started_at')[:8]
        return render(request, 'dashboards/teacher.html', ctx)

    elif user.is_student():
        # student dashboard
        if hasattr(user, 'student_profile') and user.student_profile:
            analytics = get_student_analytics(user.student_profile)
            ctx['presence_percentage'] = analytics['presence_percentage']
            ctx['classes_missed'] = analytics['absent_classes']
            ctx['recent_attendance'] = analytics['recent_history']
            ctx['student'] = user.student_profile
            # courses for the embedded logs viewer filter
            from apps.attendance.models import AttendanceRecord
            ctx['log_courses'] = (
                AttendanceRecord.objects
                .filter(student=user.student_profile)
                .values_list('session__subject__code', flat=True)
                .distinct()
                .order_by('session__subject__code')
            )
        else:
            ctx['error'] = "No student profile linked to this account."
            
        return render(request, 'dashboards/student.html', ctx)

    # fallback
    return render(request, 'dashboards/dashboard.html', ctx)
