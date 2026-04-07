"""apps/audit/urls.py"""
from django.urls import path
from . import views

urlpatterns = [
    path('logs/',               views.system_logs_list,   name='system_logs'),
    path('logs/export/',        views.system_logs_export,  name='system_logs_export'),
    path('logs/<uuid:log_id>/', views.system_logs_detail,  name='system_logs_detail'),
]
