"""apps/audit/apps.py — starts the background purge scheduler on server start."""

from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class AuditConfig(AppConfig):
    name = 'apps.audit'
    verbose_name = 'Audit Logs'

    def ready(self):
        """
        start an in-process apscheduler job that runs purge_old_logs()
        every hour.  we guard with run_main so the scheduler only starts
        once (not twice in django's auto-reloader mode).
        """
        import os
        if os.environ.get('RUN_MAIN') != 'true':
            # when django's auto-reloader is active it spawns two processes;
            # only the child (run_main=true) should run the scheduler.
            # in production (gunicorn/uwsgi) run_main is not set, so we
            # still only start once.
            if not _is_management_command():
                return

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.interval import IntervalTrigger
            from django.conf import settings
            from .retention import purge_old_logs

            scheduler = BackgroundScheduler(timezone='Asia/Kolkata')
            scheduler.add_job(
                purge_old_logs,
                trigger=IntervalTrigger(hours=1),
                id='audit_purge',
                replace_existing=True,
                misfire_grace_time=300,
            )
            scheduler.start()
            logger.info('[audit] Background purge scheduler started (runs every 1 h).')
        except ImportError:
            logger.warning(
                '[audit] APScheduler not installed. '
                'Run: pip install apscheduler  '
                'Or schedule: python manage.py purge_audit_logs via cron.'
            )
        except Exception as exc:
            logger.error('[audit] Failed to start purge scheduler: %s', exc)


def _is_management_command() -> bool:
    """return true when django is being invoked as a management command."""
    import sys
    return len(sys.argv) > 1 and sys.argv[1] not in ('runserver', 'runserver_plus')
