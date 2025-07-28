from django.urls import path
from .views import AccountListView

urlpatterns = [
    path('client/<int:client_id>/accounts/', AccountListView.as_view(), name='client-accounts-list'),
]
