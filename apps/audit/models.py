"""
apps/audit/models.py
────────────────────
Immutable, tamper-evident audit log for every back-end action.

Each row captures:
  • IST timestamp (stored as UTC, displayed as IST)
  • event_type & auth_method enum choices
  • denormalised user identifiers (survive user deletion)
  • full device fingerprint (browser, OS, device class, raw UA)
  • client IP
  • arbitrary context JSON (logout reason, error codes, stack traces, …)
  • HMAC-SHA256 checksum for tamper-detection
"""

import uuid
import hmac
import hashlib
import json

from django.conf import settings
from django.db import models


# ── Event type choices ────────────────────────────────────────────────────────

EVENT_TYPE_CHOICES = [
    # Auth
    ('LOGIN',               'Login'),
    ('LOGIN_FAILED',        'Login Failed'),
    ('LOGOUT',              'Logout'),
    ('BIO_LOGIN',           'Biometric Login'),
    ('BIO_LOGIN_FAILED',    'Biometric Login Failed'),
    ('BIO_AUTH_LOCKED',     'Biometric Auth Locked'),
    # Password / OTP
    ('PASSWORD_CHANGE',     'Password Change'),
    ('PASSWORD_RESET_REQ',  'Password Reset Requested'),
    ('OTP_SENT',            'OTP Sent'),
    ('OTP_VERIFIED',        'OTP Verified'),
    ('OTP_FAILED',          'OTP Verification Failed'),
    # Account lifecycle
    ('USER_CREATED',        'User Created'),
    ('USER_AUTO_CREATED',   'User Auto-Created'),
    ('USER_MODIFIED',       'User Modified'),
    ('USER_DEACTIVATED',    'User Deactivated'),
    ('USER_ACTIVATED',      'User Activated'),
    # Session / access
    ('SESSION_EXPIRED',     'Session Expired'),
    ('ACCESS_DENIED',       'Access Denied'),
    ('CSRF_FAILURE',        'CSRF Failure'),
    # System
    ('ERROR',               'Error'),
    ('ADMIN_ACTION',        'Admin Action'),
    ('PURGE',               'Log Purge'),
    # Legacy / catch-all
    ('OTHER',               'Other'),
]

AUTH_METHOD_CHOICES = [
    ('password',           'Password'),
    ('facial_recognition', 'Facial Recognition'),
    ('otp',               'OTP'),
    ('mfa',               'MFA'),
    ('system',            'System / Internal'),
    ('unknown',           'Unknown'),
]


def _compute_checksum(row_dict: dict) -> str:
    """
    Deterministic HMAC-SHA256 of the immutable row fields.
    Stored in `checksum`; any tampering will invalidate it.
    """
    key = (getattr(settings, 'HMAC_SIGNING_KEY', '') or 'audit-fallback-key').encode()
    payload = json.dumps(row_dict, sort_keys=True, default=str).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


class AuditLog(models.Model):
    """Immutable audit log entry. Never update rows — append only."""

    # Primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # When (stored UTC, displayed IST via TIME_ZONE = 'Asia/Kolkata')
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    # What happened
    event_type = models.CharField(
        max_length=30,
        choices=EVENT_TYPE_CHOICES,
        default='OTHER',
        db_index=True,
    )
    auth_method = models.CharField(
        max_length=20,
        choices=AUTH_METHOD_CHOICES,
        default='unknown',
        db_index=True,
    )

    # Who (FK + denormalised strings so logs survive user deletion)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    actor_user_id = models.CharField(max_length=64, blank=True, db_index=True,
                                     help_text='UUID string of actor (denormalised)')
    actor_username = models.CharField(max_length=150, blank=True,
                                      help_text='Username at the time of the event')
    actor_role = models.CharField(max_length=20, blank=True,
                                  help_text='Role at the time of the event')

    # Network
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)

    # Device fingerprint (parsed from User-Agent)
    user_agent = models.TextField(blank=True)
    browser = models.CharField(max_length=120, blank=True)
    os = models.CharField(max_length=120, blank=True)
    device_type = models.CharField(max_length=40, blank=True)  # desktop / mobile / tablet

    # Contextual payload
    context = models.JSONField(
        default=dict,
        blank=True,
        help_text='Arbitrary key-value context: logout reason, error codes, stack traces, …',
    )

    # Tamper-evidence
    checksum = models.CharField(max_length=64, blank=True,
                                help_text='HMAC-SHA256 of immutable fields')

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['event_type', 'timestamp'], name='al_evtype_ts_idx'),
            models.Index(fields=['actor_user_id', 'timestamp'], name='al_userid_ts_idx'),
            models.Index(fields=['ip_address', 'timestamp'], name='al_ip_ts_idx'),
            models.Index(fields=['auth_method', 'timestamp'], name='al_authm_ts_idx'),
        ]

    # ── helpers ──────────────────────────────────────────────────────────────

    def compute_checksum(self) -> str:
        payload = {
            'id': str(self.id),
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'event_type': self.event_type,
            'auth_method': self.auth_method,
            'actor_user_id': self.actor_user_id,
            'ip_address': self.ip_address,
            'context': self.context,
        }
        return _compute_checksum(payload)

    def verify_checksum(self) -> bool:
        """Returns True if the stored checksum matches a freshly computed one."""
        return hmac.compare_digest(self.checksum, self.compute_checksum())

    @property
    def event_display_color(self) -> str:
        """Bootstrap/Tailwind colour class for the event badge."""
        danger = {'LOGIN_FAILED', 'BIO_LOGIN_FAILED', 'BIO_AUTH_LOCKED',
                  'ACCESS_DENIED', 'CSRF_FAILURE', 'ERROR', 'OTP_FAILED'}
        warning = {'PASSWORD_RESET_REQ', 'OTP_SENT', 'SESSION_EXPIRED'}
        success = {'LOGIN', 'BIO_LOGIN', 'OTP_VERIFIED', 'PASSWORD_CHANGE'}
        info = {'USER_CREATED', 'USER_AUTO_CREATED', 'USER_MODIFIED',
                'USER_DEACTIVATED', 'USER_ACTIVATED', 'ADMIN_ACTION'}
        if self.event_type in danger:
            return 'danger'
        if self.event_type in warning:
            return 'warning'
        if self.event_type in success:
            return 'success'
        if self.event_type in info:
            return 'info'
        return 'secondary'

    def context_summary(self) -> str:
        """One-line human-readable summary of the context payload."""
        if not self.context:
            return '—'
        parts = []
        for key in ('reason', 'logout_reason', 'error', 'error_code', 'score', 'notes', 'message'):
            if key in self.context:
                parts.append(f"{key}: {self.context[key]}")
        if parts:
            return '; '.join(parts)
        # fallback: first two keys
        items = list(self.context.items())[:2]
        return '; '.join(f"{k}: {v}" for k, v in items)

    def __str__(self):
        actor = self.actor_username or 'anonymous'
        ts = self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else '?'
        return f"[{ts}] {self.event_type} — {actor} ({self.ip_address})"
