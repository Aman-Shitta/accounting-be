"""
Root URL configuration.

Everything lives under /api/v1/. There is no admin site and no static or
media serving — files are handed out by an authenticated view that checks
tenancy first.
"""

from django.urls import include, path

app_v1_url_patterns = [
    path("auth/", include("authentication.urls")),
    path("user/", include("user.urls")),
    path("account/", include("account.urls")),
    path("dashboard/", include("dashboard.urls")),
]

urlpatterns = [
    path("api/v1/", include((app_v1_url_patterns, "api_v1"))),
]
