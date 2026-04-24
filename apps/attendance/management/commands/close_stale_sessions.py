"""
management command: close_stale_sessions
auto-closes any attendancesession that is still open at the end of the calendar day.
usage: py manage.py close_stale_sessions
schedule via windows task scheduler or cron to run daily at ~23:59.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.attendance.models import AttendanceSession


class Command(BaseCommand):
    help = "Auto-close any OPEN attendance sessions whose start date is before today."

    def handle(self, *args, **kwargs):
        now = timezone.now()
        today = now.date()

        # find all open sessions whose started_at date is strictly before today (eod passed)
        stale_sessions = AttendanceSession.objects.filter(
            status='OPEN',
            started_at__date__lt=today
        )

        count = stale_sessions.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("No stale sessions to close."))
            return

        # close each one: set closed_at to 23:59:59 of their start date
        closed = 0
        for session in stale_sessions:
            # set closed_at to end of the day the session was opened
            eod = timezone.datetime.combine(
                session.started_at.date(),
                timezone.datetime.max.time(),
                tzinfo=session.started_at.tzinfo
            )
            session.closed_at = eod
            session.status = 'CLOSED'
            session.save(update_fields=['closed_at', 'status'])
            closed += 1
            self.stdout.write(f"  Closed session {session.id} ({session.section}) — started {session.started_at.date()}")

        self.stdout.write(self.style.SUCCESS(f"Done. Auto-closed {closed} stale session(s)."))
