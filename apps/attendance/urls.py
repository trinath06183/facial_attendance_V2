from django.urls import path
from . import views
from . import api_views
from . import report_api

urlpatterns = [
    path('', views.session_list, name='session_list'),
    path('viewer/', views.attendance_viewer, name='attendance_viewer'),
    path('create/', views.session_create, name='session_create'),
    path('<uuid:pk>/', views.session_detail, name='session_detail'),
    path('<uuid:pk>/close/', views.session_close, name='session_close'),
    path('<uuid:pk>/scanner/', views.scanner_view, name='scanner_view'),
    path('<uuid:pk>/verify/', views.verify_attendance, name='verify_attendance'),
    path('<uuid:pk>/lookup/', views.lookup_profile, name='lookup_profile'),
    path('api/analytics/', views.analytics_data, name='analytics_data'),
    path('api/attendances/', api_views.attendances_api, name='attendances_api'),
    path('api/export/', views.export_reports, name='export_reports'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),
    # ── Enhanced Reports ──
    path('reports/', views.reports_dashboard, name='reports_dashboard'),
    path('reports/student/<uuid:student_id>/', views.report_student_detail, name='report_student_detail'),
    path('reports/export/', views.report_export_view, name='report_export_view'),
    path('api/reports/student/<uuid:student_id>/', report_api.report_student_api, name='report_student_api'),
    path('api/reports/section/<uuid:section_id>/', report_api.report_section_api, name='report_section_api'),
    path('api/reports/top-bottom/<uuid:section_id>/', report_api.report_top_bottom_api, name='report_top_bottom_api'),
    path('api/reports/overview/', report_api.report_overview_api, name='report_overview_api'),
    
    # ── Manual Override ──
    path('api/students/search/', api_views.student_search_api, name='student_search_api'),
    path('api/<uuid:session_id>/override/', api_views.manual_override_api, name='manual_override_api'),
    
    # ── Inline Editing & Hydration ──
    path('api/record/<uuid:record_id>/edit/', api_views.attendance_record_edit_api, name='attendance_record_edit_api'),
    path('api/<uuid:session_id>/ledger/', api_views.attendance_session_ledger_api, name='attendance_session_ledger_api'),
]
