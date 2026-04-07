import logging
from django.utils import timezone
from django.contrib.sessions.models import Session

logger = logging.getLogger(__name__)

def is_user_already_active(user, request):
    """
    Checks if the user has an active session in the database
    that is DIFFERENT from the current request's session key.
    Returns True if an active session exists.
    """
    if not user or not user.active_session_key:
        return False

    current_key = request.session.session_key
    old_key = user.active_session_key

    # If the active key is the same as the current browser's key, they aren't "elsewhere"
    if current_key and old_key == current_key:
        return False

    # Check if the old key still exists and hasn't expired in the DB
    old_session = Session.objects.filter(session_key=old_key).first()
    if old_session and old_session.expire_date > timezone.now():
        return True

    return False
