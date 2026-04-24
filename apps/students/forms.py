from django import forms
from .models import Student
from apps.attendance.models import AcademicYear, Subject

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
            'academic_class', 'academic_year', 'enrolled_subjects', 'enrollment_status', 'consent_given'
        ]
        widgets = {
            'student_id': forms.TextInput(attrs={'placeholder': 'Internal ID (e.g. CS2024001)'}),
            'full_name': forms.TextInput(attrs={'placeholder': 'Full legal name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'student@college.edu'}),
            'enrolled_subjects': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # make subjects empty by default unless bound to an academic year
        self.fields['academic_year'].queryset = AcademicYear.objects.none()
        self.fields['enrolled_subjects'].queryset = Subject.objects.none()

        if 'academic_class' in self.data:
            try:
                class_id = self.data.get('academic_class')
                self.fields['academic_year'].queryset = AcademicYear.objects.filter(academic_class_id=class_id).order_by('year_name')
            except (ValueError, TypeError):
                pass
                
        if 'academic_year' in self.data:
            try:
                year_id = self.data.get('academic_year')
                self.fields['enrolled_subjects'].queryset = Subject.objects.filter(academic_year_id=year_id).order_by('name')
            except (ValueError, TypeError):
                pass
                
        elif self.instance.pk:
            if self.instance.academic_class:
                self.fields['academic_year'].queryset = AcademicYear.objects.filter(academic_class=self.instance.academic_class).order_by('year_name')
            if self.instance.academic_year:
                self.fields['enrolled_subjects'].queryset = Subject.objects.filter(academic_year=self.instance.academic_year).order_by('name')
