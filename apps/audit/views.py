"""
apps/audit/views.py
────────────────────
Admin-only System Log panel.

Endpoints:
  GET  /audit/logs/              — paginated list with filters
  GET  /audit/logs/<uuid>/       — JSON detail for a single entry (AJAX)
  GET  /audit/logs/export/       — CSV download of current filtered result set
"""

import csv
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.core.paginator import Paginator
from django.views.decorators.http import require_GET
from django.db.models import Q

from .models import AuditLog, EVENT_TYPE_CHOICES, AUTH_METHOD_CHOICES


def _admin_required(view_fn):
    """Decorator: only admins (role=ADMIN or is_superuser) can access."""
    from functools import wraps
    from django.shortcuts import redirect

    @login_required
    @wraps(view_fn)
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_superuser or getattr(request.user, 'role', '') == 'ADMIN'):
            from django.contrib import messages
            messages.error(request, 'Access denied — Admin only.')
            return redirect('dashboard')
        return view_fn(request, *args, **kwargs)
    return wrapper


def _build_queryset(params):
    """Apply filter/search params to AuditLog queryset. Returns a QS."""
    qs = AuditLog.objects.select_related('actor').all()

    # ── Enum filters ─────────────────────────────────────────────────────────
    event_type = params.get('event_type', '').strip()
    if event_type:
        qs = qs.filter(event_type=event_type)

    auth_method = params.get('auth_method', '').strip()
    if auth_method:
        qs = qs.filter(auth_method=auth_method)

    actor_role = params.get('actor_role', '').strip()
    if actor_role:
        qs = qs.filter(actor_role=actor_role)

    # ── Text filters ─────────────────────────────────────────────────────────
    user_q = params.get('user_q', '').strip()
    if user_q:
        qs = qs.filter(
            Q(actor_username__icontains=user_q) | Q(actor_user_id__icontains=user_q)
        )

    ip_q = params.get('ip_q', '').strip()
    if ip_q:
        qs = qs.filter(ip_address__icontains=ip_q)

    # ── Full-text search across UA + context (stored as JSON text) ───────────
    search = params.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(user_agent__icontains=search)
            | Q(actor_username__icontains=search)
            | Q(ip_address__icontains=search)
            | Q(context__icontains=search)
            | Q(browser__icontains=search)
            | Q(os__icontains=search)
        )

    # ── Date range (IST dates from the UI, converted to UTC for the query) ───
    date_from = params.get('date_from', '').strip()
    if date_from:
        try:
            from datetime import datetime
            dt = datetime.strptime(date_from, '%Y-%m-%d')
            # Make it timezone-aware in IST then let Django convert to UTC
            import pytz
            ist = pytz.timezone('Asia/Kolkata')
            qs = qs.filter(timestamp__gte=ist.localize(dt))
        except (ValueError, Exception):
            pass

    date_to = params.get('date_to', '').strip()
    if date_to:
        try:
            from datetime import datetime, timedelta
            dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            import pytz
            ist = pytz.timezone('Asia/Kolkata')
            qs = qs.filter(timestamp__lt=ist.localize(dt))
        except (ValueError, Exception):
            pass

    return qs


@_admin_required
@require_GET
def system_logs_list(request):
    """Main System Logs page."""
    qs = _build_queryset(request.GET)
    total = qs.count()

    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page', 1)
    try:
        page_number = int(page_number)
    except (ValueError, TypeError):
        page_number = 1
    page = paginator.get_page(page_number)

    return render(request, 'audit/system_logs.html', {
        'page_obj': page,
        'total': total,
        'event_types': EVENT_TYPE_CHOICES,
        'auth_methods': AUTH_METHOD_CHOICES,
        'role_choices': [
            ('ADMIN', 'Admin'), ('TEACHER', 'Teacher'),
            ('STUDENT', 'Student'), ('READONLY_STAFF', 'Read-Only Staff'),
        ],
        # pass filter values back to template
        'f_event_type':  request.GET.get('event_type', ''),
        'f_auth_method': request.GET.get('auth_method', ''),
        'f_actor_role':  request.GET.get('actor_role', ''),
        'f_user_q':      request.GET.get('user_q', ''),
        'f_ip_q':        request.GET.get('ip_q', ''),
        'f_search':      request.GET.get('search', ''),
        'f_date_from':   request.GET.get('date_from', ''),
        'f_date_to':     request.GET.get('date_to', ''),
    })


@_admin_required
@require_GET
def system_logs_detail(request, log_id):
    """AJAX endpoint — returns full JSON detail for one log entry."""
    log = get_object_or_404(AuditLog, pk=log_id)
    ist = timezone.localtime(log.timestamp)
    data = {
        'id':             str(log.id),
        'timestamp_ist':  ist.strftime('%d %b %Y %H:%M:%S IST'),
        'event_type':     log.event_type,
        'auth_method':    log.auth_method,
        'actor_username': log.actor_username,
        'actor_user_id':  log.actor_user_id,
        'actor_role':     log.actor_role,
        'ip_address':     log.ip_address or '—',
        'browser':        log.browser or '—',
        'os':             log.os or '—',
        'device_type':    log.device_type or '—',
        'user_agent':     log.user_agent or '—',
        'context':        log.context,
        'checksum_valid': log.verify_checksum(),
        'checksum':       log.checksum,
    }
    return JsonResponse(data)


@_admin_required
@require_GET
def system_logs_export(request):
    """Stream filtered results as a CSV download."""
    qs = _build_queryset(request.GET)

    filename = f"smartattend_audit_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'Timestamp (IST)', 'Event Type', 'Auth Method',
        'Username', 'User ID', 'Role',
        'IP Address', 'Browser', 'OS', 'Device', 'User-Agent',
        'Context', 'Checksum Valid',
    ])

    for log in qs.iterator(chunk_size=500):
        ist = timezone.localtime(log.timestamp).strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([
            ist,
            log.event_type,
            log.auth_method,
            log.actor_username,
            log.actor_user_id,
            log.actor_role,
            log.ip_address or '',
            log.browser,
            log.os,
            log.device_type,
            log.user_agent,
            json.dumps(log.context, default=str),
            'YES' if log.verify_checksum() else 'NO',
        ])

    return response
