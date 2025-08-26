from django.urls import path

from .monthly_accounting_views import (
    MonthlyAccountingListView,
    MonthlyAccountingCreateView,
    MonthlyAccountingDetailView,
    MonthlyAccountingDocumentUploadView,
    MonthlyAccountingDocumentLineItemListCreateView,
    MonthlyAccountingDocumentLineItemDetailView,
)

# Monthly Accounting API URL patterns
monthly_accounting_url_patterns = [
    # List monthly accounting sessions
    path('list/', MonthlyAccountingListView.as_view(), name='monthly-accounting-list'),
    # Create new monthly accounting session
    path('create/', MonthlyAccountingCreateView.as_view(), name='monthly-accounting-create'),
    # Retrieve, update, or delete specific monthly accounting session
    path('<int:accounting_id>/', MonthlyAccountingDetailView.as_view(), name='monthly-accounting-detail'),
    # Upload a file for a specific document (requires accounting session id and document id)
    path('<int:accounting_id>/documents/<int:document_id>/upload/', MonthlyAccountingDocumentUploadView.as_view(), name='monthly-accounting-document-upload'),
    path('<int:accounting_id>/documents/<int:document_id>/items/', MonthlyAccountingDocumentLineItemListCreateView.as_view(), name='monthly-accounting-document-lineitems'),
    path('<int:accounting_id>/documents/<int:document_id>/items/<int:line_item_id>/', MonthlyAccountingDocumentLineItemDetailView.as_view(), name='monthly-accounting-document-lineitem-detail'),
]