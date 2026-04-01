from django.urls import path
from . import views

urlpatterns = [
    path('', views.student_list, name='student_list'),
    path('create/', views.student_create, name='student_create'),
    path('<uuid:pk>/', views.student_detail, name='student_detail'),
    path('<uuid:pk>/edit/', views.student_edit, name='student_edit'),
    path('<uuid:pk>/enroll/', views.student_enroll_face, name='student_enroll_face'),
    path('<uuid:pk>/enroll/upload/', views.upload_face_frame, name='upload_face_frame'),
    path('<uuid:pk>/qr/', views.student_qr, name='student_qr'),
    path('<uuid:pk>/qr/display/', views.student_qr_display, name='student_qr_display'),
    path('<uuid:pk>/photo/upload/', views.student_photo_upload, name='student_photo_upload'),
    path('<uuid:pk>/photo/<uuid:photo_id>/approve/', views.student_photo_approve, name='student_photo_approve'),
    path('<uuid:pk>/photo/<uuid:photo_id>/delete/', views.student_photo_delete, name='student_photo_delete'),
]
