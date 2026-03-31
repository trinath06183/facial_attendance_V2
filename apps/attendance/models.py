import uuid
from django.db import models
from django.conf import settings


class Room(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    capacity = models.IntegerField(default=50)

    def __str__(self):
        return self.name


class Subject(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)

    def __str__(self):
        return f"{self.code} - {self.name}"


class Batch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100) # e.g., "Class of 2026" or "2024-2025"
    year = models.IntegerField()

    def __str__(self):
        return self.name


class Section(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course_code = models.CharField(max_length=20)
    course_name = models.CharField(max_length=200)
    section_identifier = models.CharField(max_length=10)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='sections', null=True, blank=True)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='sections', null=True, blank=True)
    teachers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='sections')

    class Meta:
        unique_together = [('course_code', 'section_identifier')]

    def __str__(self):
        return f"{self.course_code} - {self.course_name} ({self.section_identifier})"


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
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='sessions')
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='IN_PERSON')
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    def __str__(self):
        return f"{self.section} on {self.started_at.strftime('%Y-%m-%d %H:%M')}"

    @property
    def total_expected(self):
        return self.section.students.filter(enrollment_status='ACTIVE').count()

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
        return f"{self.student.full_name} - {self.session.section} ({self.status})"
