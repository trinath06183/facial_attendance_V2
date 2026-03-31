from django.urls import path
from . import dashboard_views

urlpatterns = [
    path('', dashboard_views.dashboard, name='dashboard'),
]
