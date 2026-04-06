import uuid
from django.db import models
from django.conf import settings


class Room(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    capacity = models.IntegerField(default=50)

    def __str__(self):
        return self.name

class AcademicClass(models.Model):
    """ E.g. 'MCA', 'B.Tech CSE' """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    
    class Meta:
        verbose_name_plural = "Academic Classes"

    def __str__(self):
        return self.name

class AcademicYear(models.Model):
    """ E.g. '1st Year', '2nd Year', mapped under an AcademicClass """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_class = models.ForeignKey(AcademicClass, on_delete=models.CASCADE, related_name='years')
    year_name = models.CharField(max_length=50) # e.g. "1st Year", "2nd Year"

    class Meta:
        unique_together = ['academic_class', 'year_name']
        ordering = ['year_name']

    def __str__(self):
        return f"{self.academic_class.name} - {self.year_name}"

class Subject(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name='subjects', null=True)
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    teachers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='subjects', blank=True)

    def __str__(self):
        yr_str = str(self.academic_year) if self.academic_year else "N/A"
        return f"[{yr_str}] {self.code} - {self.name}"


class AttendanceSession(models.Model):
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('OPEN', 'Open'),
        ('CLOSED', 'Closed'),
        ('CANCELLED', 'Cancelled'),
    ]

    MODE_CHOICES = [
        ('IN_PERSON', 'In-Person'),
        ('ONLINE', 'Online'),
        ('HYBRID', 'Hybrid'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='sessions', null=True)
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='IN_PERSON')
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    def __str__(self):
        subj = str(self.subject) if self.subject else "No Subject"
        return f"{subj} on {self.started_at.strftime('%Y-%m-%d %H:%M')}"

    @property
    def total_expected(self):
        if self.subject:
            return self.subject.enrolled_students.filter(enrollment_status='ACTIVE').count()
        return 0

    @property
    def total_present(self):
        return self.records.filter(status='PRESENT').count()


class AttendanceRecord(models.Model):
    STATUS_CHOICES = [
        ('PRESENT', 'Present'),
        ('ABSENT', 'Absent'),
        ('EXCUSED', 'Excused'),
        ('LATE', 'Late'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name='records')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE, related_name='attendance_records')
    marked_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ABSENT')
    verification_method = models.CharField(max_length=50, default='QR_AND_FACE')
    face_match_score = models.FloatField(null=True, blank=True)
    device_fingerprint = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    # Edit Tracking
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='edited_attendance_records')
    edited_at = models.DateTimeField(null=True, blank=True)
    original_status = models.CharField(max_length=20, null=True, blank=True)
    reason = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = [('session', 'student')]
        indexes = [
            models.Index(fields=['session', 'student']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        subj = str(self.session.subject) if getattr(self.session, 'subject', None) else "No Subject"
        return f"{self.student.full_name} - {subj} ({self.status})"
