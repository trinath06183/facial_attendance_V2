from .models import AttendanceSession


class AttendanceAutoCloseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        AttendanceSession.close_expired_sessions()
        return self.get_response(request)
