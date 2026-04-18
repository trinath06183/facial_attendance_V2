from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone


class InactivityLogoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            last_activity = request.session.get('last_activity_at')
            if last_activity:
                last_activity_at = timezone.datetime.fromisoformat(last_activity)
                if timezone.is_naive(last_activity_at):
                    last_activity_at = timezone.make_aware(last_activity_at, timezone.get_current_timezone())

                inactive_for = (timezone.now() - last_activity_at).total_seconds()
                if inactive_for >= settings.INACTIVITY_TIMEOUT_SECONDS:
                    request.session['_logout_reason'] = 'inactivity_timeout'
                    logout(request)

                    accepts_json = 'application/json' in request.headers.get('Accept', '')
                    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                    if accepts_json or is_ajax:
                        return JsonResponse({'success': False, 'error': 'SESSION_EXPIRED'}, status=440)
                    return redirect(settings.LOGIN_URL)

        return self.get_response(request)
