"""
Management command: python manage.py purge_audit_logs

Options:
  --dry-run     Print how many records would be deleted without deleting.
  --hours N     Override retention window (default: AUDIT_LOG_RETENTION_HOURS setting or 48).
"""

from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Purge AuditLog entries older than the configured retention window (default 48 h).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report how many rows would be deleted without actually deleting.'
        )
        parser.add_argument(
            '--hours', type=int,
            default=getattr(settings, 'AUDIT_LOG_RETENTION_HOURS', 48),
            help='Retention window in hours (overrides the settings value).'
        )

    def handle(self, *args, **options):
        # Temporarily override the retention setting so retention.py picks it up
        original = getattr(settings, 'AUDIT_LOG_RETENTION_HOURS', 48)
        settings.AUDIT_LOG_RETENTION_HOURS = options['hours']

        from apps.audit.retention import purge_old_logs
        count = purge_old_logs(dry_run=options['dry_run'])

        settings.AUDIT_LOG_RETENTION_HOURS = original  # restore

        verb = 'Would delete' if options['dry_run'] else 'Deleted'
        self.stdout.write(
            self.style.SUCCESS(f'{verb} {count} audit log entries older than {options["hours"]} hours.')
        )
