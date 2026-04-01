from django import forms
from .models import Student


class StudentForm(forms.ModelForm):
    consent_given = forms.BooleanField(
        required=True,
        label='I confirm this student has been informed of and consents to '
              'the collection of their biometric facial data for attendance purposes.'
    )
    university_roll_number = forms.CharField(
        required=True,
        label='University Roll Number',
        widget=forms.TextInput(attrs={'placeholder': 'Required (e.g. 1012345678)'})
    )

    class Meta:
        model = Student
        fields = [
            'student_id', 'university_roll_number', 'full_name', 'email', 'phone',
            'subjects', 'enrollment_status', 'consent_given'
        ]
        widgets = {
            'student_id': forms.TextInput(attrs={'placeholder': 'Internal ID (e.g. CS2024001)'}),
            'full_name': forms.TextInput(attrs={'placeholder': 'Full legal name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'student@college.edu'}),
            'subjects': forms.CheckboxSelectMultiple(),
        }
