from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from . import views

urlpatterns = [
    path('login/', LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<uuid:user_id>/edit/', views.user_edit, name='user_edit'),
    path('users/<uuid:user_id>/toggle/', views.user_toggle_status, name='user_toggle_status'),
    path('api/login/biometric/', views.biometric_login_api, name='biometric_login_api'),
    # ── Student Biometric Login Scanner (public) ──────────────
    path('student-login/', views.student_scanner_view, name='student_scanner'),
    path('api/student-face-login/', views.student_face_login_api, name='student_face_login_api'),
    # ── Browser-close auto-logout (sendBeacon) ──────────────────────
    path('api/browser-logout/', views.browser_logout_api, name='browser_logout_api'),
    
    # ── OTP Password Reset (Admin / Teacher) ──────────────────────
    path('password-reset/', views.password_reset_request, name='password_reset_request'),
    path('password-reset/verify/', views.password_reset_verify, name='password_reset_verify'),
    path('password-reset/confirm/', views.password_reset_confirm, name='password_reset_confirm'),

    # ── Student Password Login ──────────────────────
    path('student-login/password/', views.student_password_login, name='student_password_login'),

    # ── Student OTP Password Reset ──────────────────────
    path('student/password-reset/', views.student_password_reset_request, name='student_password_reset_request'),
    path('student/password-reset/verify/', views.student_password_reset_verify, name='student_password_reset_verify'),
    path('student/password-reset/confirm/', views.student_password_reset_confirm, name='student_password_reset_confirm'),

    # ── Student Change Password (logged in) ──────────────────────
    path('student/change-password/', views.student_change_password, name='student_change_password'),
    path('student/first-login-change-password/', views.student_first_login_change_password, name='student_first_login_change_password'),
]
