"""
apps/audit/utils.py
───────────────────
Public API for recording audit log events.

Usage:
    from apps.audit.utils import log_event

    log_event(
        event_type='LOGIN',
        auth_method='password',
        request=request,        # optional – extracts IP, UA, actor
        user=some_user,         # optional override / supplement
        context={'score': 0.97},
    )

The function is thread-safe (Django ORM writes are atomic per-row),
performant (no synchronous blocking), and fails silently (never raises
so it cannot break a request/response cycle).
"""

import logging
import traceback

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── UA parser (optional dependency) ──────────────────────────────────────────

def _parse_user_agent(ua_string: str) -> dict:
    """Return browser/OS/device info from a User-Agent string."""
    result = {'browser': '', 'os': '', 'device_type': 'desktop'}
    if not ua_string:
        return result
    try:
        from user_agents import parse as ua_parse
        ua = ua_parse(ua_string)
        result['browser'] = f"{ua.browser.family} {ua.browser.version_string}".strip()
        result['os'] = f"{ua.os.family} {ua.os.version_string}".strip()
        if ua.is_mobile:
            result['device_type'] = 'mobile'
        elif ua.is_tablet:
            result['device_type'] = 'tablet'
        else:
            result['device_type'] = 'desktop'
    except ImportError:
        # user-agents not installed — store raw UA only
        pass
    except Exception:
        pass
    return result


def _get_client_ip(request) -> str | None:
    """Return the real client IP, respecting X-Forwarded-For."""
    if not request:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


# ── Main logging function ─────────────────────────────────────────────────────

def log_event(
    event_type: str,
    auth_method: str = 'system',
    request=None,
    user=None,
    context: dict | None = None,
) -> None:
    """
    Record one audit log entry.  Never raises — errors are logged to the
    Python `audit` logger and swallowed so they cannot break a request.

    Parameters
    ----------
    event_type  : one of the EVENT_TYPE_CHOICES keys (e.g. 'LOGIN')
    auth_method : one of the AUTH_METHOD_CHOICES keys (e.g. 'password')
    request     : Django HttpRequest (optional) — used to extract IP, UA, actor
    user        : CustomUser instance (optional) — overrides request.user
    context     : dict with any extra payload (logout_reason, error_code, …)
    """
    try:
        from .models import AuditLog  # lazy import to avoid circular imports

        # Resolve actor
        actor = user
        if actor is None and request is not None:
            req_user = getattr(request, 'user', None)
            if req_user and getattr(req_user, 'is_authenticated', False):
                actor = req_user

        # Network
        ip = _get_client_ip(request)

        # Device fingerprint
        ua_string = ''
        if request is not None:
            ua_string = request.META.get('HTTP_USER_AGENT', '')
        ua_info = _parse_user_agent(ua_string)

        # Denormalised actor fields (survive user deletion)
        actor_user_id = ''
        actor_username = ''
        actor_role = ''
        if actor is not None:
            actor_user_id = str(getattr(actor, 'id', '') or '')
            actor_username = getattr(actor, 'username', '') or ''
            actor_role = getattr(actor, 'role', '') or ''

        # Context
        ctx = dict(context) if context else {}
        # Add IST timestamp string for human readability in JSON exports
        ctx['_ist'] = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S IST')

        # Build the row
        log = AuditLog(
            event_type=event_type,
            auth_method=auth_method,
            actor=actor,
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            actor_role=actor_role,
            ip_address=ip,
            user_agent=ua_string[:2048],
            browser=ua_info['browser'][:120],
            os=ua_info['os'][:120],
            device_type=ua_info['device_type'][:40],
            context=ctx,
        )
        # Compute checksum before save (id and timestamp will be set on save)
        log.save()  # sets id + timestamp
        log.checksum = log.compute_checksum()
        log.save(update_fields=['checksum'])

    except Exception as exc:  # noqa: BLE001
        logger.error(
            'audit.log_event failed: %s\n%s',
            exc,
            traceback.format_exc(),
        )


# ── Legacy shim (keeps old callers working) ──────────────────────────────────

def audit(request, action: str, target_resource: str = '', resource_id: str = '',
          metadata=None) -> None:
    """
    Backward-compatible wrapper around log_event().
    Old code that calls audit(request, 'LOGGED_IN_BIOMETRIC', …) continues
    to work without modification.
    """
    context = {}
    if metadata:
        if isinstance(metadata, dict):
            context.update(metadata)
        else:
            context['notes'] = str(metadata)
    if target_resource:
        context['target_resource'] = target_resource
    if resource_id:
        context['resource_id'] = resource_id

    # Map old action strings → new event_type
    action_map = {
        'LOGGED_IN_BIOMETRIC':          ('BIO_LOGIN', 'facial_recognition'),
        'BIO_AUTH_LOCKED':              ('BIO_AUTH_LOCKED', 'facial_recognition'),
        'BIO_AUTH_FAILED':              ('BIO_LOGIN_FAILED', 'facial_recognition'),
        'PASSWORD_CHANGED_FIRST_LOGIN': ('PASSWORD_CHANGE', 'password'),
        'USER_AUTO_CREATED':            ('USER_AUTO_CREATED', 'system'),
    }
    event_type, auth_method = action_map.get(action, (action, 'system'))

    log_event(
        event_type=event_type,
        auth_method=auth_method,
        request=request,
        context=context,
    )
