import uuid
import base64
import numpy as np
from django.db import models
from django.conf import settings


class Student(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('GRADUATED', 'Graduated'),
        ('SUSPENDED', 'Suspended'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_id = models.CharField(max_length=50) # Internal ID
    university_roll_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, 
        null=True, blank=True, related_name='student_profile'
    )
    full_name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    section = models.ForeignKey(
        'attendance.Section', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='students'
    )
    enrollment_status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='ACTIVE'
    )
    consent_given = models.BooleanField(default=False)
    consent_timestamp = models.DateTimeField(null=True, blank=True)
    consent_ip = models.GenericIPAddressField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='registered_students'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('student_id', 'section')]
        ordering = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.student_id})"

    @property
    def qr_ready(self):
        return self.embeddings.filter(is_active=True).exists()

    @property
    def embedding_count(self):
        return self.embeddings.filter(is_active=True).count()


class Embedding(models.Model):
    ENV_CHOICES = [
        ('WELL_LIT', 'Well Lit'),
        ('DIM', 'Dim'),
        ('OUTDOOR', 'Outdoor'),
        ('UNKNOWN', 'Unknown'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='embeddings')
    embedding_vector = models.TextField()          # Base64-encoded float32 array
    model_name = models.CharField(max_length=100, default='SFace_v1.0')
    model_version = models.CharField(max_length=50, default='1.0')
    is_active = models.BooleanField(default=True)
    quality_score = models.FloatField(null=True, blank=True)
    source_image_hash = models.CharField(max_length=64, blank=True)
    capture_environment = models.CharField(max_length=20, choices=ENV_CHOICES, default='UNKNOWN')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def set_vector(self, arr: np.ndarray):
        """Store a numpy float32 array as base64 text."""
        self.embedding_vector = base64.b64encode(arr.astype(np.float32).tobytes()).decode()

    def get_vector(self) -> np.ndarray:
        """Retrieve the embedding as a numpy float32 array."""
        raw = base64.b64decode(self.embedding_vector.encode())
        return np.frombuffer(raw, dtype=np.float32)

    def __str__(self):
        return f"Embedding for {self.student.full_name} [{self.model_name}]"


class QRCodeRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name='qr_record')
    token_payload = models.TextField()
    issued_at = models.DateTimeField(auto_now_add=True)
    last_regenerated_at = models.DateTimeField(auto_now=True)
    signing_key_version = models.IntegerField(default=1)
    is_valid = models.BooleanField(default=True)

    def __str__(self):
        return f"QR for {self.student.full_name}"


class StudentPhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='student_photos/')
    is_primary = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)
    privacy_consent = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Photo for {self.student.full_name}"
