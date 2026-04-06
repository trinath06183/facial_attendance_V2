from django.forms import ModelForm, ChoiceField, ModelChoiceField
from .models import AttendanceSession, Subject, Section

class AttendanceSessionForm(ModelForm):
    year = ChoiceField(choices=Subject.YEAR_CHOICES, label='Academic Year')
    subject = ModelChoiceField(queryset=Subject.objects.none(), label='Subject', empty_label="--- Select Academic Year First ---")

    class Meta:
        model = AttendanceSession
        fields = ['year', 'subject', 'room']

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user and hasattr(self.user, 'role') and self.user.role == 'TEACHER':
            # Check if year is bound in POST data to populate subject dropdown correctly for validation
            if 'year' in self.data:
                try:
                    year_val = int(self.data.get('year'))
                    valid_subjects = Subject.objects.filter(
                        year=year_val,
                        sections__teachers=self.user
                    ).distinct()
                    self.fields['subject'].queryset = valid_subjects
                except (ValueError, TypeError):
                    pass

    def clean(self):
        cleaned_data = super().clean()
        subject = cleaned_data.get('subject')
        
        if subject and self.user:
            section = Section.objects.filter(subject=subject, teachers=self.user).first()
            if not section:
                self.add_error('subject', 'No class section found for this subject assigned to you.')
            else:
                # Attach the inferred section to the instance before saving
                self.instance.section = section
                cleaned_data['section'] = section
                
        return cleaned_data

