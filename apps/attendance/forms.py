from django.forms import ModelForm, ChoiceField, ModelChoiceField
from .models import AttendanceSession, Subject, AcademicClass, AcademicYear

class AttendanceSessionForm(ModelForm):
    academic_class = ModelChoiceField(queryset=AcademicClass.objects.all(), label='Class / Program', empty_label="--- Select Class ---")
    academic_year = ModelChoiceField(queryset=AcademicYear.objects.none(), label='Academic Year', empty_label="--- Select Academic Year ---")
    subject = ModelChoiceField(queryset=Subject.objects.none(), label='Subject', empty_label="--- Select Subject ---")

    class Meta:
        model = AttendanceSession
        fields = ['academic_class', 'academic_year', 'subject', 'room']

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # we need ajax to populate year/subject normally, but we handle basic post bound data here
        if 'academic_class' in self.data:
            try:
                class_id = self.data.get('academic_class')
                self.fields['academic_year'].queryset = AcademicYear.objects.filter(academic_class_id=class_id)
            except (ValueError, TypeError):
                pass
                
        if 'academic_year' in self.data:
            try:
                year_id = self.data.get('academic_year')
                qs = Subject.objects.filter(academic_year_id=year_id)
                self.fields['subject'].queryset = qs
            except (ValueError, TypeError):
                pass
        
        # if we are editing an instance
        elif self.instance.pk and self.instance.subject:
            self.fields['academic_class'].initial = self.instance.subject.academic_year.academic_class
            self.fields['academic_year'].initial = self.instance.subject.academic_year
            self.fields['academic_year'].queryset = AcademicYear.objects.filter(academic_class=self.instance.subject.academic_year.academic_class)
            
            qs = Subject.objects.filter(academic_year=self.instance.subject.academic_year)
            self.fields['subject'].queryset = qs


    def clean(self):
        cleaned_data = super().clean()
        return cleaned_data
