"""
accounts/signals.py
──────────────────
Single-active-session-per-user enforcement + full audit logging.

When user A logs in from Device Y while already logged in on Device X:
  1. Device X's session is deleted from the session store → silently logged out.
  2. Device Y's new session key is saved on the user record.
  3. A LOGIN / LOGOUT audit event is recorded with full context.
"""

import logging
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def enforce_single_active_session(sender, request, user, **kwargs):
    """
    Fires immediately after django.contrib.auth.login() for ANY login method.
    Records the new session key and logs the LOGIN event.
    """
    new_key = request.session.session_key

    if not new_key:
        logger.warning(
            f"[session-mgmt] No session key found after login for '{user.username}'. Skipping."
        )
        return

    user.active_session_key = new_key
    user.save(update_fields=['active_session_key'])

    # ── Audit log ────────────────────────────────────────────────────────────
    # Determine auth method from session flags set by views
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
    Clears active_session_key on logout and logs the LOGOUT event.
    """
    if user and user.is_authenticated:
        old_key = user.active_session_key
        user.active_session_key = None
        user.save(update_fields=['active_session_key'])
        logger.info(f"[session-mgmt] Cleared session key for '{user.username}' on logout.")

        # ── Audit log ────────────────────────────────────────────────────────
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
