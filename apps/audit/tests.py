"""
apps/audit/tests.py
────────────────────
Unit tests for the audit logging system.

Run:  python manage.py test apps.audit
"""

from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.contrib.auth import get_user_model
from unittest.mock import patch
import datetime

from .models import AuditLog
from .utils import log_event, audit
from .retention import purge_old_logs

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Model tests
# ─────────────────────────────────────────────────────────────────────────────

class AuditLogModelTest(TestCase):

    def _make_user(self):
        return User.objects.create_user(
            username='testadmin', password='pass1234', role='ADMIN'
        )

    def test_checksum_computed_on_save(self):
        """log_event() must store a non-empty HMAC checksum."""
        log_event(event_type='LOGIN', auth_method='password',
                  context={'test': True})
        log = AuditLog.objects.first()
        self.assertTrue(bool(log.checksum), 'Checksum must not be empty.')

    def test_checksum_verifies_correctly(self):
        """verify_checksum() returns True for untampered rows."""
        log_event(event_type='LOGOUT', auth_method='system')
        log = AuditLog.objects.first()
        self.assertTrue(log.verify_checksum())

    def test_tamper_detection(self):
        """Modifying a field after save must invalidate the checksum."""
        log_event(event_type='LOGIN', auth_method='password')
        log = AuditLog.objects.first()
        # Simulate database-level tampering on a field tracked by checksum
        AuditLog.objects.filter(pk=log.pk).update(event_type='HACKED')
        log.refresh_from_db()
        self.assertFalse(log.verify_checksum(), 'Tampered row must fail checksum.')

    def test_str_representation(self):
        log_event(event_type='ERROR', auth_method='system',
                  context={'error': 'test error'})
        log = AuditLog.objects.first()
        self.assertIn('ERROR', str(log))

    def test_event_display_color(self):
        log_event(event_type='LOGIN', auth_method='password')
        log = AuditLog.objects.first()
        self.assertEqual(log.event_display_color, 'success')

    def test_context_summary(self):
        log_event(event_type='LOGOUT', auth_method='system',
                  context={'logout_reason': 'user_initiated'})
        log = AuditLog.objects.first()
        self.assertIn('logout_reason', log.context_summary())


# ─────────────────────────────────────────────────────────────────────────────
# 2. log_event() API tests
# ─────────────────────────────────────────────────────────────────────────────

class LogEventTest(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='teacher1', password='pass1234', role='TEACHER'
        )

    def test_creates_log_entry(self):
        log_event(event_type='ADMIN_ACTION', auth_method='password')
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_captures_user_fields(self):
        log_event(event_type='LOGIN', auth_method='password', user=self.user)
        log = AuditLog.objects.first()
        self.assertEqual(log.actor_username, 'teacher1')
        self.assertEqual(log.actor_role, 'TEACHER')
        self.assertEqual(log.actor_user_id, str(self.user.id))

    def test_captures_ip_from_request(self):
        request = self.factory.get('/', REMOTE_ADDR='10.0.0.1')
        request.user = self.user
        log_event(event_type='LOGIN', auth_method='password', request=request)
        log = AuditLog.objects.first()
        self.assertEqual(log.ip_address, '10.0.0.1')

    def test_captures_xff_ip(self):
        request = self.factory.get('/', HTTP_X_FORWARDED_FOR='203.0.113.5, 10.0.0.1')
        request.user = self.user
        log_event(event_type='LOGIN', auth_method='password', request=request)
        log = AuditLog.objects.first()
        self.assertEqual(log.ip_address, '203.0.113.5')

    def test_captures_user_agent(self):
        request = self.factory.get(
            '/', HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120'
        )
        request.user = self.user
        log_event(event_type='LOGIN', auth_method='password', request=request)
        log = AuditLog.objects.first()
        self.assertIn('Mozilla', log.user_agent)

    def test_context_stored(self):
        log_event(event_type='ERROR', auth_method='system',
                  context={'error_code': 500, 'path': '/api/test/'})
        log = AuditLog.objects.first()
        self.assertEqual(log.context['error_code'], 500)
        self.assertEqual(log.context['path'], '/api/test/')

    def test_ist_timestamp_in_context(self):
        """log_event should store _ist key in the context."""
        log_event(event_type='LOGIN', auth_method='password')
        log = AuditLog.objects.first()
        self.assertIn('_ist', log.context)
        self.assertIn('IST', log.context['_ist'])

    def test_never_raises_on_bad_input(self):
        """log_event must not raise even with invalid event_type."""
        try:
            log_event(event_type='TOTALLY_INVALID_EVENT_XYZ',
                      auth_method='unknown', context=None)
        except Exception as e:
            self.fail(f'log_event raised an exception: {e}')

    def test_legacy_audit_shim(self):
        """The legacy audit() shim must map old actions to new event types."""
        request = self.factory.get('/')
        request.user = self.user
        audit(request, 'LOGGED_IN_BIOMETRIC', 'User', str(self.user.id), 'test')
        log = AuditLog.objects.first()
        self.assertEqual(log.event_type, 'BIO_LOGIN')
        self.assertEqual(log.auth_method, 'facial_recognition')


# ─────────────────────────────────────────────────────────────────────────────
# 3. Retention tests
# ─────────────────────────────────────────────────────────────────────────────

class RetentionTest(TestCase):

    def _create_old_log(self, hours_ago: int):
        """Create a log entry and backdate its timestamp."""
        log_event(event_type='LOGIN', auth_method='password')
        log = AuditLog.objects.order_by('-timestamp').first()
        old_ts = timezone.now() - datetime.timedelta(hours=hours_ago)
        AuditLog.objects.filter(pk=log.pk).update(timestamp=old_ts)
        return log

    def test_purge_removes_old_entries(self):
        self._create_old_log(49)  # older than 48 h → should be deleted
        log_event(event_type='LOGOUT', auth_method='system')  # fresh → must survive
        self.assertEqual(AuditLog.objects.count(), 2)

        with patch('django.conf.settings.AUDIT_LOG_RETENTION_HOURS', 48):
            deleted = purge_old_logs()

        # The 49-hour-old entry should be gone; the PURGE event created by
        # purge_old_logs() itself is fresh, so total = 2 (fresh + purge)
        self.assertEqual(deleted, 1)

    def test_dry_run_does_not_delete(self):
        self._create_old_log(50)
        count_before = AuditLog.objects.count()
        purge_old_logs(dry_run=True)
        self.assertEqual(AuditLog.objects.count(), count_before)

    def test_recent_entries_not_purged(self):
        # All entries are recent — nothing should be deleted
        log_event(event_type='LOGIN', auth_method='password')
        log_event(event_type='LOGOUT', auth_method='system')
        deleted = purge_old_logs()
        self.assertEqual(deleted, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 4. View tests (System Logs panel)
# ─────────────────────────────────────────────────────────────────────────────

class SystemLogsViewTest(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin1', password='admin1234', role='ADMIN', is_staff=True
        )
        self.student = User.objects.create_user(
            username='student1', password='pass1234', role='STUDENT'
        )
        # Create some log entries
        for evt in ('LOGIN', 'LOGOUT', 'BIO_LOGIN', 'ERROR'):
            log_event(event_type=evt, auth_method='password', user=self.admin)

    def test_admin_can_access(self):
        self.client.login(username='admin1', password='admin1234')
        resp = self.client.get('/audit/logs/')
        self.assertEqual(resp.status_code, 200)

    def test_non_admin_redirected(self):
        self.client.login(username='student1', password='pass1234')
        resp = self.client.get('/audit/logs/')
        self.assertEqual(resp.status_code, 302)

    def test_unauthenticated_redirected(self):
        resp = self.client.get('/audit/logs/')
        self.assertEqual(resp.status_code, 302)

    def test_filter_by_event_type(self):
        self.client.login(username='admin1', password='admin1234')
        resp = self.client.get('/audit/logs/?event_type=LOGIN')
        self.assertEqual(resp.status_code, 200)
        # Only LOGIN entries should appear
        for log in resp.context['page_obj']:
            self.assertEqual(log.event_type, 'LOGIN')

    def test_detail_json_endpoint(self):
        self.client.login(username='admin1', password='admin1234')
        log = AuditLog.objects.filter(event_type='LOGIN').first()
        resp = self.client.get(f'/audit/logs/{log.id}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['event_type'], 'LOGIN')
        self.assertIn('checksum_valid', data)

    def test_csv_export(self):
        self.client.login(username='admin1', password='admin1234')
        resp = self.client.get('/audit/logs/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        content = resp.content.decode()
        self.assertIn('Timestamp (IST)', content)
        self.assertIn('Event Type', content)
