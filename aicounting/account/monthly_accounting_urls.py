from django.urls import path

from .monthly_accounting_views import (
    MonthlyAccountingListView,
    MonthlyAccountingCreateView,
    MonthlyAccountingDetailView,
    MonthlyAccountingDocumentUploadView,
    MonthlyAccountingDocumentStartExtractionView,
    MonthlyAccountingDocumentLineItemListCreateView,
    MonthlyAccountingDocumentLineItemDetailView,
    MonthlyAccountingDocumentStatusUpdateView
)

from .je_accounting_views import (
    JEAccountingDetailView,
    JEAccountingVerifyView,
    JEAttributeEditView,
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
    # Start extraction after pre-processing is complete
    # path('<int:accounting_id>/documents/<int:document_id>/extract/', MonthlyAccountingDocumentStartExtractionView.as_view(), name='monthly-accounting-document-extract'),
    path('<int:accounting_id>/documents/<int:document_id>/verify/', MonthlyAccountingDocumentStatusUpdateView.as_view(), name='monthly-accounting-document-update-status'),

    path('<int:accounting_id>/documents/<int:document_id>/items/', MonthlyAccountingDocumentLineItemListCreateView.as_view(), name='monthly-accounting-document-lineitems'),
    path('<int:accounting_id>/documents/<int:document_id>/items/<int:line_item_id>/', MonthlyAccountingDocumentLineItemDetailView.as_view(), name='monthly-accounting-document-lineitem-detail'),

    # JE Template endpoints
    path('<int:accounting_id>/je_template/<int:template_id>/', JEAccountingDetailView.as_view(), name='monthly-accounting-template-detail'),
    path('<int:accounting_id>/je_template/<int:template_id>/verify/', JEAccountingVerifyView.as_view(), name='monthly-accounting-template-verify'),
    path('<int:accounting_id>/je_template/<int:template_id>/attribute/<int:attribute_id>/', JEAttributeEditView.as_view(), name='monthly-accounting-attribute-edit'),

]