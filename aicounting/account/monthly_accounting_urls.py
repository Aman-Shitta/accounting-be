from django.urls import path

from .monthly_accounting_views import (
    MonthlyAccountingListView,
    MonthlyAccountingCreateView,
    MonthlyAccountingDetailView,
    MonthlyAccountingDocumentUploadView
)

# Monthly Accounting API URL patterns
monthly_accounting_url_patterns = [
    # List monthly accounting sessions
    path('list/', MonthlyAccountingListView.as_view(), name='monthly-accounting-list'),
    # Create new monthly accounting session
    path('create/', MonthlyAccountingCreateView.as_view(), name='monthly-accounting-create'),
    # Retrieve, update, or delete specific monthly accounting session
    path('<int:accounting_id>/', MonthlyAccountingDetailView.as_view(), name='monthly-accounting-detail'),
    # Upload a file for a specific document
    path('documents/<uuid:doc_id>/upload/', MonthlyAccountingDocumentUploadView.as_view(), name='monthly-accounting-document-upload'),
]