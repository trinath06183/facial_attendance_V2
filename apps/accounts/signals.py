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
    Fires immediately after django.contrib.auth.login() for ANY login method.
    We just record the active_session_key here.
    The rejection of the new login is handled in views/forms.
    """
    new_key = request.session.session_key

    if not new_key:
        logger.warning(
            f"[session-mgmt] No session key found after login for '{user.username}'. Skipping."
        )
        return

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
