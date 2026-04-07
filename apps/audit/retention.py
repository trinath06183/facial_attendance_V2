"""
apps/audit/retention.py
────────────────────────
Log retention logic — purges entries older than AUDIT_LOG_RETENTION_HOURS (default 48h).
"""

import logging
from django.utils import timezone
from django.conf import settings
import datetime

logger = logging.getLogger(__name__)

RETENTION_HOURS = getattr(settings, 'AUDIT_LOG_RETENTION_HOURS', 48)


def purge_old_logs(dry_run: bool = False) -> int:
    """
    Delete AuditLog rows older than RETENTION_HOURS.

    Returns the number of rows deleted (or that would be deleted in dry_run).
    This function never raises — errors are logged and 0 is returned.
    """
    try:
        from .models import AuditLog

        cutoff = timezone.now() - datetime.timedelta(hours=RETENTION_HOURS)
        qs = AuditLog.objects.filter(timestamp__lt=cutoff)
        count = qs.count()

        if dry_run:
            logger.info('[audit.retention] DRY RUN — would purge %d entries older than %s', count, cutoff)
            return count

        deleted, _ = qs.delete()
        if deleted:
            from .utils import log_event
            log_event(
                event_type='PURGE',
                auth_method='system',
                context={
                    'purged_count': deleted,
                    'cutoff_utc': cutoff.isoformat(),
                    'retention_hours': RETENTION_HOURS,
                },
            )
            logger.info('[audit.retention] Purged %d log entries older than %s', deleted, cutoff)
        return deleted

    except Exception as exc:
        logger.error('[audit.retention] purge_old_logs failed: %s', exc)
        return 0
