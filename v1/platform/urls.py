from django.urls import path

from v1.platform.views import (
    PlatformFirmDetailView,
    PlatformFirmListView,
    PlatformOverviewView,
)

urlpatterns = [
    path("overview/", PlatformOverviewView.as_view(), name="overview"),
    path("firms/", PlatformFirmListView.as_view(), name="firms"),
    path("firms/<uuid:pk>/", PlatformFirmDetailView.as_view(), name="firm"),
]
