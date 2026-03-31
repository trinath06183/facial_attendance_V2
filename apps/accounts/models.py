import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('ADMIN', 'Admin'),
        ('TEACHER', 'Teacher'),
        ('STUDENT', 'Student'),
        ('READONLY_STAFF', 'Read-Only Staff'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='TEACHER')
    mfa_enabled = models.BooleanField(default=False)

    def is_admin(self):
        return self.role == 'ADMIN'

    def is_teacher(self):
        return self.role == 'TEACHER'

    def is_student(self):
        return self.role == 'STUDENT'

    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"
