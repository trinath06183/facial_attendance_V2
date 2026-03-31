import logging

logger = logging.getLogger(__name__)

class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # We process before view
        response = self.get_response(request)
        # We could also log 403s or 500s here automatically.
        if response.status_code >= 400:
            user = request.user.username if hasattr(request, 'user') and request.user.is_authenticated else 'Anonymous'
            path = request.path
            logger.warning(f"HTTP {response.status_code} on {path} by user {user}")
            
        return response
