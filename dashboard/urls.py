from django.urls import path

from dashboard.views import (
    CustomerDashboardView,
    AccountantDashboardView,
    ReviewerDashboardView,
)

urlpatterns = [
    path('customer/', CustomerDashboardView.as_view(), name='dashboard-customer'),
    path('accountant/', AccountantDashboardView.as_view(), name='dashboard-accountant'),
    path('reviewer/', ReviewerDashboardView.as_view(), name='dashboard-reviewer'),
]
