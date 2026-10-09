"""Shared navigation state for every marketplace template."""

from .auth_backend import has_campus_access


def campus_access(request):
    return {"campus_access": request.user.is_authenticated and has_campus_access(request.user)}
