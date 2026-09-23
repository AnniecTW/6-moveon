"""A protected endpoint used to exercise authorization through Django's URL stack."""

from django.http import HttpResponse
from django.urls import path

from moveon.urls import urlpatterns as app_urlpatterns


def protected_probe(request):
    return HttpResponse("private student action")


urlpatterns = [
    *app_urlpatterns,
    path("__auth_probe__/", protected_probe, name="campus_probe"),
]
