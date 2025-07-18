from django.urls import path
from .admin_auth_views import AdminLoginView, CustomerListView, AdminDashboardView
from .invite_views import AzureInviteView

admin_urlpatterns = [
    # Admin authentication
    path('login/', AdminLoginView.as_view(), name='admin_login'),
    # Admin dashboard
    path('dashboard/', AdminDashboardView.as_view(), name='admin_dashboard'),
    # Customer management
    path('customers/', CustomerListView.as_view(), name='customer_list'),
    path('invite/', AzureInviteView.as_view(), name='customer_invite'),
]
