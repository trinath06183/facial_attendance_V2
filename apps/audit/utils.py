"""
apps/audit/utils.py

public api for recording audit log events.

usage:
    from apps.audit.utils import log_event

    log_event(
        event_type='login',
        auth_method='password',
        request=request,        # optional – extracts ip, ua, actor
        user=some_user,         # optional override / supplement
        context={'score': 0.97},
    )

the function is thread-safe (django orm writes are atomic per-row),
performant (no synchronous blocking), and fails silently (never raises
so it cannot break a request/response cycle).
"""

import logging
import traceback

from django.utils import timezone

logger = logging.getLogger(__name__)


#  ua parser (optional dependency) 

def _parse_user_agent(ua_string: str) -> dict:
    """return browser/os/device info from a user-agent string."""
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
        # user-agents not installed — store raw ua only
        pass
    except Exception:
        pass
    return result


def _get_client_ip(request) -> str | None:
    """return the real client ip, respecting x-forwarded-for."""
    if not request:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


#  main logging function 

def log_event(
    event_type: str,
    auth_method: str = 'system',
    request=None,
    user=None,
    context: dict | None = None,
) -> None:
    """
    record one audit log entry.  never raises — errors are logged to the
    python `audit` logger and swallowed so they cannot break a request.

    parameters
    
    event_type  : one of the event_type_choices keys (e.g. 'login')
    auth_method : one of the auth_method_choices keys (e.g. 'password')
    request     : django httprequest (optional) — used to extract ip, ua, actor
    user        : customuser instance (optional) — overrides request.user
    context     : dict with any extra payload (logout_reason, error_code, …)
    """
    try:
        from .models import AuditLog  # lazy import to avoid circular imports

        # resolve actor
        actor = user
        if actor is None and request is not None:
            req_user = getattr(request, 'user', None)
            if req_user and getattr(req_user, 'is_authenticated', False):
                actor = req_user

        # network
        ip = _get_client_ip(request)

        # device fingerprint
        ua_string = ''
        if request is not None:
            ua_string = request.META.get('HTTP_USER_AGENT', '')
        ua_info = _parse_user_agent(ua_string)

        # denormalised actor fields (survive user deletion)
        actor_user_id = ''
        actor_username = ''
        actor_role = ''
        if actor is not None:
            actor_user_id = str(getattr(actor, 'id', '') or '')
            actor_username = getattr(actor, 'username', '') or ''
            actor_role = getattr(actor, 'role', '') or ''

        # context
        ctx = dict(context) if context else {}
        # add ist timestamp string for human readability in json exports
        ctx['_ist'] = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S IST')

        # build the row
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
        # compute checksum before save (id and timestamp will be set on save)
        log.save()  # sets id + timestamp
        log.checksum = log.compute_checksum()
        log.save(update_fields=['checksum'])

    except Exception as exc:  # noqa: ble001
        logger.error(
            'audit.log_event failed: %s\n%s',
            exc,
            traceback.format_exc(),
        )


#  legacy shim (keeps old callers working) 

def audit(request, action: str, target_resource: str = '', resource_id: str = '',
          metadata=None) -> None:
    """
    backward-compatible wrapper around log_event().
    old code that calls audit(request, 'logged_in_biometric', …) continues
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

    # map old action strings → new event_type
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
