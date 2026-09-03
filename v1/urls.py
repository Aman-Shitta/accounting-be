"""
The /api/v1/ surface.

Resource routers land here as each app is built out in Phase 6; auth is
complete.
"""

from django.urls import include, path

urlpatterns = [
    path("auth/", include(("v1.identity.urls", "identity"), namespace="auth")),
]
