"""
accounts/signals.py
──────────────────
Single-active-session-per-user enforcement.

When user A logs in from Device Y while already logged in on Device X:
  1. Device X's session is deleted from the session store → silently logged out.
  2. Device Y's new session key is saved on the user record.

User B's sessions are completely unaffected — we only ever touch the
session key stored on the specific user who is logging in.
"""

import logging
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def enforce_single_active_session(sender, request, user, **kwargs):
    """
    Fires immediately after django.contrib.auth.login() for ANY login method
    (biometric, roll-number/password, Django admin, etc.).

    Algorithm:
        old_key = user.active_session_key
        new_key = request.session.session_key
        if old_key exists AND old_key != new_key:
            Session.objects.filter(session_key=old_key).delete()
        user.active_session_key = new_key
    """
    from django.contrib.sessions.models import Session

    new_key = request.session.session_key

    if not new_key:
        logger.warning(
            f"[session-mgmt] No session key found after login for '{user.username}'. Skipping."
        )
        return

    old_key = user.active_session_key

    if old_key and old_key != new_key:
        deleted, _ = Session.objects.filter(session_key=old_key).delete()
        if deleted:
            logger.info(
                f"[session-mgmt] Invalidated old session '{old_key[:8]}…' "
                f"for user '{user.username}' — replaced by new session '{new_key[:8]}…'"
            )
        else:
            # Session had already expired / been cleaned — harmless
            logger.debug(
                f"[session-mgmt] Old session '{old_key[:8]}…' for '{user.username}' "
                "not found in store (may have already expired)."
            )

    # Record the new active session key
    user.active_session_key = new_key
    user.save(update_fields=['active_session_key'])


@receiver(user_logged_out)
def clear_active_session_on_logout(sender, request, user, **kwargs):
    """
    Clears active_session_key when the user explicitly logs out so stale
    keys don't accumulate in the DB.
    """
    if user and user.is_authenticated:
        user.active_session_key = None
        user.save(update_fields=['active_session_key'])
        logger.info(f"[session-mgmt] Cleared session key for '{user.username}' on logout.")
