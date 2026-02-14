from django.urls import path

from account.reviewer.reviewer_views import (
    MonthlyAccountingDocumentLineItemDetailView,
    MonthlyAccountingDocumentLineItemListCreateView,
    ReviewerDocumentDetailView,
    ReviewerDocumentListView,
    ReviewerSubmitReviewView,
)

# Reviewer API URL patterns
# Included under:  /api/v1/account/reviewer/
reviewer_url_patterns = [
    path('documents/', ReviewerDocumentListView.as_view(),
         name='reviewer-document-list'),
    path('documents/<int:document_id>/',
         ReviewerDocumentDetailView.as_view(), name='reviewer-document-detail'),
    path('documents/<int:document_id>/items/',
         MonthlyAccountingDocumentLineItemListCreateView.as_view(), name='reviewer-document-data-retrieve'),
    path('documents/<int:document_id>/items/<int:line_item_id>/',
         MonthlyAccountingDocumentLineItemDetailView.as_view(), name='reviewer-document-data-detail'),
    path('documents/<int:document_id>/review/',
         ReviewerSubmitReviewView.as_view(), name='reviewer-submit-review'),
]
