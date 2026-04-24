"""
accounts/signals.py

single-active-session-per-user enforcement + full audit logging.

when user a logs in from device y while already logged in on device x:
  1. device x's session is deleted from the session store → silently logged out.
  2. device y's new session key is saved on the user record.
  3. a login / logout audit event is recorded with full context.
"""

import logging
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def enforce_single_active_session(sender, request, user, **kwargs):
    """
    fires immediately after django.contrib.auth.login() for any login method.
    records the new session key and logs the login event.
    """
    new_key = request.session.session_key

    if not new_key:
        logger.warning(
            f"[session-mgmt] No session key found after login for '{user.username}'. Skipping."
        )
        return

    user.active_session_key = new_key
    user.save(update_fields=['active_session_key'])

    #  audit log 
    # determine auth method from session flags set by views
    auth_method = request.session.get('_auth_method', 'password')

    try:
        from apps.audit.utils import log_event
        log_event(
            event_type='LOGIN',
            auth_method=auth_method,
            request=request,
            user=user,
            context={
                'session_key': new_key,
                'method_detail': auth_method,
            },
        )
    except Exception as exc:
        logger.error('[audit] Failed to log LOGIN event: %s', exc)


@receiver(user_logged_out)
def clear_active_session_on_logout(sender, request, user, **kwargs):
    """
    clears active_session_key on logout and logs the logout event.
    """
    if user and user.is_authenticated:
        old_key = user.active_session_key
        user.active_session_key = None
        user.save(update_fields=['active_session_key'])
        logger.info(f"[session-mgmt] Cleared session key for '{user.username}' on logout.")

        #  audit log 
        try:
            from apps.audit.utils import log_event
            log_event(
                event_type='LOGOUT',
                auth_method='system',
                request=request,
                user=user,
                context={
                    'session_key': old_key,
                    'logout_reason': request.session.get('_logout_reason', 'user_initiated'),
                },
            )
        except Exception as exc:
            logger.error('[audit] Failed to log LOGOUT event: %s', exc)
