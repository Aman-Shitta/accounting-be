import logging

from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated

from account.accounting.monthly_document_line_item_serializers import (
    MonthlyDocumentBankLineItemSerializer,
    MonthlyDocumentLineItemSerializer,
    GLAccountNestedSerializer
)
from account.models import (
    MonthlyDocumentBankLineItem,
    MonthlyDocumentAttributeItem,
    MonthlyAccountingDocument,
)
from account.reviewer.serializers import (
    ReviewActionResponseSerializer,
    ReviewSubmitSerializer,
    ReviewerDocumentDetailSerializer,
    ReviewerDocumentListSerializer,
)
from aicounting.constants import BANKING_DOCS
from aicounting.response import create_api_response
from authentication import authenticate
from authentication.permissions import IsReviewer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REVIEWABLE_STATUSES = ['pending_review', 'in_review']


class ReviewerMixin(generics.GenericAPIView):
    def _get_reviewer(self, request):
        """Return the DimAICReviewer profile for the authenticated user."""
        return request.user.reviewer_profile

    def _reviewer_document_queryset(self, reviewer, filter_status=None):
        """
        Base queryset: documents assigned to *reviewer* in reviewable statuses.
        Accepts an optional single status string to narrow the filter.
        """
        qs = MonthlyAccountingDocument.objects.filter(
            assigned_reviewer=reviewer,
        ).select_related(
            'monthly_accounting',
            'monthly_accounting__client',
            'input_file_snapshot',
            'assigned_reviewer__system_user',
        ).order_by('-updated_at')

        if filter_status and filter_status in REVIEWABLE_STATUSES:
            qs = qs.filter(status=filter_status)
        else:
            qs = qs.filter(status__in=REVIEWABLE_STATUSES)

        return qs


class ReviewerDocumentListView(ReviewerMixin):
    """
    GET /api/v1/account/reviewer/documents/
    List documents assigned to the authenticated reviewer.

    Query params:
      ?status=pending_review | in_review   (optional – defaults to both)
    """

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsReviewer]
    serializer_class = ReviewerDocumentListSerializer

    def get(self, request, *args, **kwargs):
        try:
            reviewer = self._get_reviewer(request)
            filter_status = request.query_params.get('status')
            queryset = self._reviewer_document_queryset(
                reviewer, filter_status)

            serializer = self.get_serializer(queryset, many=True)

            return create_api_response(
                status.HTTP_200_OK,
                f"{queryset.count()} document(s) assigned for review.",
                data={"documents": serializer.data},
            )

        except Exception as e:
            logger.error(
                f"Error listing reviewer documents: {e}", exc_info=True)
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while listing reviewer documents.",
            )


class ReviewerDocumentDetailView(ReviewerMixin):
    """
    GET /api/v1/account/reviewer/documents/<document_id>/
    Retrieve detailed information for a specific assigned document.
    Automatically transitions status from pending_review → in_review.
    """

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsReviewer]
    serializer_class = ReviewerDocumentDetailSerializer

    def get(self, request, document_id, *args, **kwargs):
        try:
            reviewer = self._get_reviewer(request)
            document = get_object_or_404(
                MonthlyAccountingDocument.objects.select_related(
                    'monthly_accounting',
                    'monthly_accounting__client',
                    'input_file_snapshot',
                ),
                id=document_id,
                assigned_reviewer=reviewer,
            )

            # Auto-transition: pending_review → in_review on first access
            if document.status == 'pending_review':
                document.status = 'in_review'
                document.save(update_fields=['status'])

            serializer = self.get_serializer(document)

            return create_api_response(
                status.HTTP_200_OK,
                "Document details loaded.",
                data=serializer.data,
            )

        except Exception as e:
            logger.error(
                f"Error retrieving reviewer document detail: {e}", exc_info=True)
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving document details.",
            )


class ReviewerSubmitReviewView(ReviewerMixin):
    """
    POST /api/v1/account/reviewer/documents/<document_id>/review/

    Body:
      { "action": "approve" | "reject", "review_notes": "..." }

    approve → status becomes 'reviewed', document is re-queued for classification.
    reject  → status becomes 'failed', accountant / customer can re-upload.
    """

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsReviewer]
    serializer_class = ReviewSubmitSerializer

    def post(self, request, document_id, *args, **kwargs):
        try:
            reviewer = self._get_reviewer(request)

            doc = get_object_or_404(
                MonthlyAccountingDocument,
                id=document_id,
                assigned_reviewer=reviewer,
                status__in=REVIEWABLE_STATUSES,
            )

            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    message="Please correct the errors in your review and try again.",
                    errors=serializer.errors,
                )

            review_notes = serializer.validated_data.get('review_notes', '')

            doc.review_notes = review_notes

            return self._handle_approve(doc, reviewer)

        except Exception as e:
            logger.error(
                f"Error submitting review for document {document_id}: {e}", exc_info=True)
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while submitting the review.",
            )


    @staticmethod
    def _handle_approve(doc, reviewer):
        """Mark as reviewed and re-queue for classification."""
        doc.status = 'reviewed'
        doc.save(update_fields=['status', 'review_notes'])

        # Re-queue for GL classification (skips validation since status is 'reviewed')
        from account.tasks import enqueue_classification_task
        enqueue_classification_task.delay(document_id=str(doc.id))

        logger.info(
            f"Reviewer {reviewer.system_user.username} approved document "
            f"{doc.id} — queued for classification."
        )

        response_data = ReviewActionResponseSerializer(doc).data
        return create_api_response(
            status.HTTP_200_OK,
            "Document approved and sent for processing.",
            data=response_data,
        )


class MonthlyAccountingDocumentLineItemListCreateView(generics.GenericAPIView):
    """List & Create line items for a processed monthly accounting document (bank_statement/credit_card)."""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsReviewer]

    def _get_document(self, document_id, request):
        from account.models import MonthlyAccountingDocument
        user = request.user

        document = get_object_or_404(
            MonthlyAccountingDocument,
            id=document_id,
            status__in=REVIEWABLE_STATUSES,
            assigned_reviewer__system_user=user
        )

        # Remove the document type restriction - now we support all document types
        return document, None

    def get(self, request, document_id, *args, **kwargs):
        """
        Retrieve line items for a processed monthly accounting document.
        Supports both bank statement/credit card line items and attribute items for other document types.

        GET /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/lines/
        """
        try:
            document, error_response = self._get_document(document_id, request)
            if error_response:
                return error_response

            document.status = 'in_review'
            document.save(update_fields=['status'])

            # Determine which type of line items to retrieve based on document type
            if document.doc_type in BANKING_DOCS:
                # Use BankLineItem for bank statements and credit cards
                items = MonthlyDocumentBankLineItem.objects.filter(
                    document=document
                ).select_related(
                    'gl_account',
                    'offset_gl_account',
                ).order_by('page_number', 'line_number')

                total_count = items.count()

                # Get default offset GL account from input file snapshot
                default_offset_gl = None
                try:
                    if document.input_file_snapshot:
                        bank_attributes = document.input_file_snapshot.attribute_snapshots.all()
                        if bank_attributes.exists():
                            default_offset_gl_obj = bank_attributes.first().offset_gl_account
                            if default_offset_gl_obj:

                                default_offset_gl = GLAccountNestedSerializer(
                                    default_offset_gl_obj).data
                except Exception as e:
                    logger.warning(
                        f"Could not retrieve default offset GL account: {e}")

            else:
                # Use AttributeItem for other document types (like sales)
                attribute_items = MonthlyDocumentAttributeItem.objects.filter(
                    document=document
                ).select_related('attribute', 'gl_account', 'offset_gl_account').order_by('page_number', 'id')

                # Add line numbers to attribute items (1-indexed)
                items = []
                for i, item in enumerate(attribute_items, 1):
                    item._line_number = i  # Set line number for serializer
                    items.append(item)

                total_count = len(items)
                default_offset_gl = None

            serializer = MonthlyDocumentLineItemSerializer(
                items, many=True, context={'request': request})

            response_data = {
                'document_id': document.id,
                "input_file_name": document.input_file_snapshot.name if document.input_file_snapshot else None,
                'doc_uuid': str(document.id),
                'doc_type': document.doc_type,
                'total_line_items': total_count,
                'document': document.file_url if document.file else None,
                'line_items': serializer.data,
                'status': document.status,
                'control_items': document.control_item
            }

            # Add default offset GL account for bank statements and credit cards
            if default_offset_gl:
                response_data['default_offset_gl_account'] = default_offset_gl

            return create_api_response(
                status.HTTP_200_OK,
                "Line items loaded.",
                data=response_data
            )
        except Exception as e:
            logger.error(
                f"Error retrieving line items for document {document_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving line items."
            )

    def post(self, request, document_id, *args, **kwargs):
        """
        Create a new line item for a monthly accounting document.
        For bank/credit card: create bank line items
        For other types: create attribute items (only for missing attributes)
        """
        try:

            document, error_response = self._get_document(document_id, request)
            if error_response:
                return error_response

            if document.doc_type in BANKING_DOCS:
                # Create bank line item
                serializer = MonthlyDocumentBankLineItemSerializer(
                    data=request.data,
                    context={'request': request, 'document': document}
                )

            if serializer.is_valid():
                item = serializer.save()

                # Use the appropriate serializer for output
                output_serializer = MonthlyDocumentBankLineItemSerializer(
                    item, context={'request': request})

                return create_api_response(
                    status.HTTP_201_CREATED,
                    "Line item added successfully.",
                    data=output_serializer.data
                )

            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Please correct the errors and try again.",
                errors=serializer.errors
            )

        except Exception as e:
            logger.error(
                f"Error creating line item for document {document_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while creating line item."
            )


class MonthlyAccountingDocumentLineItemDetailView(generics.GenericAPIView):
    """Retrieve, Update, or Delete a specific line item."""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsReviewer]

    def _get_line_item(self, document_id, line_item_id, request):
        """Helper method to get line item with proper authorization - supports both BankLineItem and AttributeItem"""
        user = request.user

        document = get_object_or_404(
            MonthlyAccountingDocument,
            id=document_id,
            status__in=REVIEWABLE_STATUSES,
            assigned_reviewer__system_user=user
        )

        # Try to fetch the appropriate line item based on document type
        line_item = get_object_or_404(
            MonthlyDocumentBankLineItem,
            id=line_item_id,
            document=document
        )
        item_type = 'banking_type'

        return line_item, item_type, None

    def patch(self, request, document_id, line_item_id, *args, **kwargs):
        """
        Update a specific line item. Supports both bank line items and attribute items.
        """
        try:
            line_item, item_type, error_response = self._get_line_item(
                document_id, line_item_id, request
            )
            if error_response:
                return error_response

            # Use appropriate serializer based on item type
            serializer = MonthlyDocumentBankLineItemSerializer(
                line_item,
                data=request.data,
                partial=True,
                context={'request': request}
            )

            if serializer.is_valid():
                updated_item = serializer.save()

                output_serializer = MonthlyDocumentBankLineItemSerializer(
                    updated_item, context={'request': request}
                )
                return create_api_response(
                    status.HTTP_200_OK,
                    "Line item updated successfully.",
                    data=output_serializer.data
                )

            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Please correct the errors and try again.",
                errors=serializer.errors
            )

        except Exception as e:
            logger.error(f"Error updating line item {line_item_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while updating line item."
            )

    def delete(self, request, document_id, line_item_id, *args, **kwargs):
        """
        Delete a specific line item.
        For bank items: renumber subsequent lines.
        For attribute items: just delete (no renumbering needed).

        DELETE /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/lines/{line_item_id}/
        """
        try:
            line_item, item_type, error_response = self._get_line_item(
                document_id, line_item_id, request
            )
            if error_response:
                return error_response

            if item_type == 'bank':
                page_number = line_item.page_number
                document = line_item.document
                deleted_line_number = line_item.line_number

                with transaction.atomic():
                    # Delete the line item
                    line_item.delete()

                    # Renumber subsequent lines on the same page
                    updated_count = MonthlyDocumentBankLineItem.objects.filter(
                        document=document,
                        page_number=page_number,
                        line_number__gt=deleted_line_number
                    ).update(line_number=F('line_number') - 1)

                    logger.error(
                        f"Deleted line {deleted_line_number} and renumbered {updated_count} subsequent lines")

                return create_api_response(
                    status.HTTP_200_OK,
                    f"Line item deleted successfully."
                )
            else:
                # For attribute items, just delete
                line_item.delete()
                logger.error(f"Deleted attribute item {line_item_id}")

                return create_api_response(
                    status.HTTP_200_OK,
                    "Line item deleted successfully."
                )

        except Exception as e:
            logger.error(f"Error deleting line item {line_item_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while deleting line item."
            )
