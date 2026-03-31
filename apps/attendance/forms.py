from django.forms import ModelForm
from .models import AttendanceSession


class AttendanceSessionForm(ModelForm):
    class Meta:
        model = AttendanceSession
        fields = ['section', 'room']
