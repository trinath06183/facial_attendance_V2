"""
apps/audit/middleware.py

lightweight request middleware that:
  1. logs http 4xx/5xx responses that aren't already captured by view-level logging.
  2. captures csrf failures (403 with reason header).
"""

import logging
from .utils import log_event

logger = logging.getLogger(__name__)


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        status = response.status_code

        # csrf failure
        if status == 403 and getattr(response, 'reason_phrase', '') == 'Forbidden':
            csrf_reason = getattr(response, 'csrf_reason', '')
            if csrf_reason or 'csrf' in request.path.lower():
                log_event(
                    event_type='CSRF_FAILURE',
                    auth_method='unknown',
                    request=request,
                    context={'path': request.path, 'method': request.method,
                             'reason': csrf_reason},
                )

        # generic 4xx (access denied, not found) and 5xx (errors)
        elif status == 403:
            log_event(
                event_type='ACCESS_DENIED',
                auth_method='unknown',
                request=request,
                context={'path': request.path, 'method': request.method,
                         'status_code': status},
            )
        elif status >= 500:
            log_event(
                event_type='ERROR',
                auth_method='system',
                request=request,
                context={'path': request.path, 'method': request.method,
                         'status_code': status},
            )

        return response
