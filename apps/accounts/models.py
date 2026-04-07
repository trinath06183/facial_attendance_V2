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
    must_change_password = models.BooleanField(
        default=False,
        help_text="If True, the user will be forced to change their password on next login."
    )

    def is_admin(self):
        return self.role == 'ADMIN' or self.is_superuser

    def is_teacher(self):
        return self.role == 'TEACHER'

    def is_student(self):
        return self.role == 'STUDENT'

    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"

class PasswordResetOTP(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='otp_resets')
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def is_valid(self):
        from django.utils import timezone
        import datetime
        # OTP is valid for exactly 10 minutes
        return timezone.now() < self.created_at + datetime.timedelta(minutes=10)
