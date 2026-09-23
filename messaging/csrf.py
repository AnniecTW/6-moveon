"""JSON CSRF failures for Messaging API, standard Django response elsewhere."""

from django.http import JsonResponse
from django.views.csrf import csrf_failure as default_csrf_failure


def csrf_failure(request, reason=""):
    if request.path.startswith("/api/messaging/"):
        return JsonResponse({"error": "Security token expired. Reload and try again.",
                             "code": "csrf_failed"}, status=403)
    return default_csrf_failure(request, reason=reason)
