"""
Root URL configuration.

Everything lives under /api/v1/. There is no admin site and no static or
media serving — files are handed out by an authenticated view that checks
tenancy first.
"""

from django.urls import include, path

urlpatterns = [
    path("api/v1/", include(("v1.urls", "v1"), namespace="v1")),
]
