import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import generics, permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from account.models import (
    FactAICMonthlyAccounting,
    MonthlyAccountingDocument,
    MonthlyDocumentBankLineItem,
    MonthlyDocumentAttributeItem,
)

from aicounting.response import create_api_response
from authentication import authenticate
from authentication.permissions import IsCustomerOrAccountant, IsCustomerOrAccountantOrReviewer
from extractor.services import DocumentProcessingService, UnsupportedDocTypeError
from user.models import DimAICClient

from account.accounting.monthly_document_line_item_serializers import (
    MonthlyDocumentBankLineItemSerializer,
    MonthlyDocumentAttributeItemSerializer,
    GLAccountNestedSerializer,
    MonthlyDocumentLineItemSerializer,
)

from aicounting.constants import BANKING_DOCS
logger = logging.getLogger(__name__)


class MonthlyAccountingListView(generics.GenericAPIView):
    """List existing monthly accounting sessions for a specific client"""

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]

    def get_queryset(self, client_id):
        """Get monthly accounting sessions with proper authorization checks"""
        user = self.request.user

        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return FactAICMonthlyAccounting.objects.filter(
                client=client_id,
                client__customer=customer
            ).order_by('-created_at')

        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return FactAICMonthlyAccounting.objects.filter(
                client=client_id,
                client__customer=accountant.customer,
                client__assigned_accountants=accountant
            ).order_by('-created_at')

        return FactAICMonthlyAccounting.objects.none()

    def get(self, request, client_id, *args, **kwargs):
        """
        List all monthly accounting sessions for a specific client.
        Returns only basic monthly accounting information without snapshots.

        GET /api/clients/{client_id}/accounting/monthly/

        Query parameters:
        - year: Filter by year
        - status: Filter by status
        """
        try:
            # Verify client exists and user has access
            user = request.user
            if hasattr(user, 'customer_profile'):
                customer = user.customer_profile
                client = get_object_or_404(
                    DimAICClient, id=client_id, customer=customer)
            elif hasattr(user, 'accountant_profile'):
                accountant = user.accountant_profile
                client = get_object_or_404(
                    DimAICClient,
                    id=client_id,
                    customer=accountant.customer,
                    assigned_accountants=accountant
                )
            else:
                return create_api_response(
                    status.HTTP_403_FORBIDDEN,
                    "Access denied."
                )

            queryset = self.get_queryset(client_id)

            # Filter by year
            year = request.query_params.get('year')
            if year:
                try:
                    year = int(year)
                    queryset = queryset.filter(year=year)
                except ValueError:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Invalid year parameter."
                    )

            # Filter by status
            status_filter = request.query_params.get('status')
            if status_filter:
                valid_statuses = [choice[0]
                                  for choice in FactAICMonthlyAccounting.STATUS_CHOICES]
                if status_filter in valid_statuses:
                    queryset = queryset.filter(status=status_filter)
                else:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        f"Invalid status. Valid options: {', '.join(valid_statuses)}"
                    )

            # Serialize the queryset manually
            monthly_accounting_data = []
            for accounting in queryset:
                monthly_accounting_data.append({
                    'id': accounting.id,
                    'month': accounting.get_month_name(),
                    'year': accounting.year,
                    'status': accounting.status,
                    'created_by': accounting.created_by.username if accounting.created_by else None,
                    'created_at': accounting.created_at.isoformat() if accounting.created_at else None,
                    'completed_at': accounting.completed_at.isoformat() if accounting.completed_at else None
                })

            return create_api_response(
                status.HTTP_200_OK,
                f"Monthly accounting sessions retrieved successfully for client {client.client_name}.",
                data={
                    'client': client.id,
                    'client_name': client.client_name,
                    'total_sessions': queryset.count(),
                    'monthly_accounting': monthly_accounting_data
                }
            )

        except Exception as e:
            logger.error(
                f"Error listing monthly accounting sessions for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving monthly accounting sessions.",
                data={"error": str(e)}
            )


class MonthlyAccountingCreateView(generics.GenericAPIView):
    """Create a new monthly accounting session for a specific client"""

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]

    def validate_create_data(self, data):
        """Validate the create data manually"""
        errors = {}

        # Validate month
        month = data.get('month')
        if not month:
            errors['month'] = ['This field is required.']
        elif not isinstance(month, int) or month < 1 or month > 12:
            errors['month'] = ['Month must be an integer between 1 and 12.']

        # Validate year
        year = data.get('year')
        if not year:
            errors['year'] = ['This field is required.']
        elif not isinstance(year, int) or year < 2000 or year > 2100:
            errors['year'] = ['Year must be an integer between 2000 and 2100.']

        if errors:
            return {'errors': errors}

        return {'month': month, 'year': year}

    def post(self, request, client_id, *args, **kwargs):
        """
        Create a new monthly accounting session.
        Snapshots are created automatically in the background for reference.

        POST /api/clients/{client_id}/accounting/monthly/create/

        Body:
        {
            "month": 8,
            "year": 2025
        }
        """
        try:
            # Verify client exists and user has access
            user = request.user
            if hasattr(user, 'customer_profile'):
                customer = user.customer_profile
                client = get_object_or_404(
                    DimAICClient, id=client_id, customer=customer)
            elif hasattr(user, 'accountant_profile'):
                accountant = user.accountant_profile
                client = get_object_or_404(
                    DimAICClient,
                    id=client_id,
                    customer=accountant.customer,
                    assigned_accountants=accountant
                )
            else:
                return create_api_response(
                    status.HTTP_403_FORBIDDEN,
                    "Access denied."
                )

            serializer = self.validate_create_data(request.data)

            if 'errors' in serializer:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Monthly accounting creation failed due to validation errors.",
                    data=serializer['errors']
                )

            month = serializer['month']
            year = serializer['year']

            # Check if accounting for this month/year already exists
            if FactAICMonthlyAccounting.objects.filter(
                client=client,
                month=month,
                year=year
            ).exists():
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Monthly accounting for {month}/{year} already exists for this client."
                )

            with transaction.atomic():
                # Create monthly accounting with snapshots (snapshots created automatically)
                monthly_accounting = FactAICMonthlyAccounting.create_monthly_accounting_with_snapshots(
                    client=client,
                    month=month,
                    year=year,
                    created_by=request.user
                )

                # Serialize the response (basic details only)
                response_data = {
                    'id': monthly_accounting.id,
                    'month': monthly_accounting.get_month_name(),
                    'year': monthly_accounting.year,
                    'status': monthly_accounting.status,
                    'created_by': monthly_accounting.created_by.username if monthly_accounting.created_by else None,
                    'created_at': monthly_accounting.created_at.isoformat() if monthly_accounting.created_at else None,
                    'completed_at': monthly_accounting.completed_at.isoformat() if monthly_accounting.completed_at else None
                }

                return create_api_response(
                    status.HTTP_201_CREATED,
                    f"Monthly accounting for {client.client_name} - {monthly_accounting.get_month_name()} {year} has been initiated successfully.",
                    data=response_data
                )

        except DjangoValidationError as e:
            logger.error(
                f"Validation error creating monthly accounting for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Validation error occurred while creating monthly accounting.",
                data={"error": str(e)}
            )

        except Exception as e:
            logger.error(
                f"Error creating monthly accounting for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while creating monthly accounting.",
                data={"error": str(e)}
            )


class MonthlyAccountingDetailView(generics.GenericAPIView):
    """Retrieve detailed information about a monthly accounting session"""

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]

    def get_object(self, client_id, accounting_id):
        """Get monthly accounting session with proper authorization checks"""
        user = self.request.user

        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related(
                    'client', 'created_by'),
                id=accounting_id,
                client=client_id,
                client__customer=customer
            )
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related(
                    'client', 'created_by'),
                id=accounting_id,
                client=client_id,
                client__customer=accountant.customer,
                client__assigned_accountants=accountant
            )
        else:
            return None

    def get(self, request, client_id, accounting_id, *args, **kwargs):
        """
        Retrieve monthly accounting details with input files and JE templates from snapshots.
        Returns the accounting information and its associated snapshot data.
        """
        try:
            accounting_id = int(accounting_id)
        except ValueError:
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Invalid accounting ID."
            )

        try:
            monthly_accounting = self.get_object(client_id, accounting_id)
            if not monthly_accounting:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Monthly accounting session not found or access denied."
                )

            # Get documents for upload (replacing input file snapshots)
            documents = MonthlyAccountingDocument.objects.filter(
                monthly_accounting=monthly_accounting
            ).select_related('input_file_snapshot')

            input_documents = []
            for document in documents:
                input_documents.append({
                    "id": document.id,
                    "doc_id": str(document.id),
                    "input_file_name": document.input_file_snapshot.name if document.input_file_snapshot else None,
                    "doc_type": document.doc_type,
                    "doc_type_display": document.get_doc_type_display(),
                    "status": document.status,
                    "status_display": document.get_status_display(),
                    "file_url": document.file_url,
                    "created_at": document.created_at.isoformat(),
                    "updated_at": document.updated_at.isoformat()
                })

            # Get JE template snapshots (basic info only)
            je_template_snapshots = monthly_accounting.je_template_snapshots.select_related(
                'original_template'
            ).prefetch_related(
                'input_files'
            )

            # Get monthly accounting documents for status checking
            documents_map = {}

            # Create map of input file snapshot ID to document for quick lookup
            monthly_docs = MonthlyAccountingDocument.objects.filter(
                monthly_accounting=monthly_accounting
            ).select_related('input_file_snapshot')

            for doc in monthly_docs:
                if doc.input_file_snapshot:
                    documents_map[doc.input_file_snapshot.id] = doc

            je_templates = []
            for template_snapshot in je_template_snapshots:
                # Get all input files associated with this template
                input_files = []
                all_verified = True
                for input_file in template_snapshot.input_files.all():
                    # Find the document status for this input file
                    is_verified = False
                    doc_status = None
                    doc_id = None

                    if input_file.id in documents_map:
                        doc = documents_map[input_file.id]
                        doc_status = doc.status
                        doc_id = doc.id
                        is_verified = doc.status == 'verified'

                    # If any input file is not verified, the template is not fully verified
                    if not is_verified:
                        all_verified = False

                    input_files.append({
                        "file_name": input_file.name,
                        "type": input_file.file_type if hasattr(input_file, 'file_type') else None,
                        "type_display": input_file.get_file_type_display() if hasattr(input_file, 'get_file_type_display') else None,
                        "verified": is_verified,
                        "document_id": doc_id,
                        "document_status": doc_status
                    })

                # Check if the template has an export file generated (which happens after verification)
                has_export = template_snapshot.je_export_file is not None
                je_templates.append({
                    "id": template_snapshot.id,  # Snapshot ID
                    "name": template_snapshot.je_name,
                    "input_files": input_files,  # List of associated input files with verification status
                    "created_at": template_snapshot.original_created_at.isoformat() if template_snapshot.original_created_at else None,
                    "updated_at": template_snapshot.original_updated_at.isoformat() if template_snapshot.original_updated_at else None,
                    "is_ready": all_verified,
                    "verified_count": sum(1 for f in input_files if f['verified']),
                    # Verified if all files are verified and export exists
                    "is_verified": (template_snapshot.status == 'verified' and all_verified and has_export),
                    "export_file": template_snapshot.je_export_file.url if template_snapshot.je_export_file else None
                })

            # Build the response data
            data = {
                "id": monthly_accounting.id,
                "month": monthly_accounting.get_month_name(),
                "year": monthly_accounting.year,
                "status": monthly_accounting.status,
                "status_display": monthly_accounting.get_status_display(),
                "created_by": monthly_accounting.created_by.username if monthly_accounting.created_by else None,
                "created_at": monthly_accounting.created_at.isoformat() if monthly_accounting.created_at else None,
                "completed_at": monthly_accounting.completed_at.isoformat() if monthly_accounting.completed_at else None,
                "documents": input_documents,
                "je_templates": je_templates
            }

            return create_api_response(
                status.HTTP_200_OK,
                "Monthly accounting details retrieved successfully.",
                data=data
            )

        except Exception as e:
            logger.error(
                f"Error retrieving monthly accounting {accounting_id} for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving monthly accounting details.",
                data={"error": str(e)}
            )

    def patch(self, request, client_id, accounting_id, *args, **kwargs):
        """
        Update the status of a monthly accounting session.

        PATCH /api/clients/{client_id}/accounting/monthly/{accounting_id}/

        Body:
        {
            "status": "in_progress" | "completed" | "failed"
        }
        """
        try:
            accounting_id = int(accounting_id)
        except ValueError:
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Invalid accounting ID."
            )

        try:
            monthly_accounting = self.get_object(client_id, accounting_id)
            if not monthly_accounting:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Monthly accounting session not found or access denied."
                )

            new_status = request.data.get('status')
            if not new_status:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Status is required."
                )

            valid_statuses = [choice[0]
                              for choice in FactAICMonthlyAccounting.STATUS_CHOICES]
            if new_status not in valid_statuses:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid status. Valid options: {', '.join(valid_statuses)}"
                )

            with transaction.atomic():
                monthly_accounting.status = new_status

                # Set completed_at timestamp if status is completed
                if new_status == 'completed':
                    monthly_accounting.completed_at = timezone.now()

                monthly_accounting.save()

                # Create response data manually
                response_data = {
                    'id': monthly_accounting.id,
                    'month': monthly_accounting.get_month_name(),
                    'year': monthly_accounting.year,
                    'status': monthly_accounting.status,
                    'created_by': monthly_accounting.created_by.username if monthly_accounting.created_by else None,
                    'created_at': monthly_accounting.created_at.isoformat() if monthly_accounting.created_at else None,
                    'completed_at': monthly_accounting.completed_at.isoformat() if monthly_accounting.completed_at else None
                }

                return create_api_response(
                    status.HTTP_200_OK,
                    f"Status updated to '{new_status}' successfully.",
                    data=response_data
                )

        except Exception as e:
            logger.error(
                f"Error updating status for accounting {accounting_id}, client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while updating status.",
                data={"error": str(e)}
            )

    def delete(self, request, client_id, accounting_id, *args, **kwargs):
        """
        Delete a monthly accounting session.
        Only accounting sessions with 'initiated' or 'failed' status can be deleted.

        DELETE /api/clients/{client_id}/accounting/monthly/{accounting_id}/
        """
        try:
            accounting_id = int(accounting_id)
        except ValueError:
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Invalid accounting ID."
            )

        try:
            monthly_accounting = self.get_object(client_id, accounting_id)
            if not monthly_accounting:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Monthly accounting session not found or access denied."
                )

            # Only allow deletion of certain statuses
            if monthly_accounting.status not in ['initiated', 'failed']:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Only accounting sessions with 'initiated' or 'failed' status can be deleted."
                )

            client_name = monthly_accounting.client.client_name
            month_name = monthly_accounting.get_month_name()
            year = monthly_accounting.year

            monthly_accounting.delete()

            return create_api_response(
                status.HTTP_200_OK,
                f"Monthly accounting for {client_name} - {month_name} {year} has been deleted successfully."
            )

        except Exception as e:
            logger.error(
                f"Error deleting monthly accounting {accounting_id} for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while deleting monthly accounting.",
                data={"error": str(e)}
            )


class MonthlyAccountingDocumentUploadView(generics.GenericAPIView):
    """Upload a file for a specific monthly accounting document (by PK) within an accounting session."""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountant]

    def post(self, request, client_id, accounting_id, document_id, *args, **kwargs):
        """POST /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/upload/"""
        # Validate integers
        for var_name, value in [("client ID", client_id), ("accounting ID", accounting_id), ("document ID", document_id)]:
            try:
                int(value)
            except ValueError:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid {var_name}."
                )
        try:

            # Authorize access similarly to other views
            user = request.user
            if hasattr(user, 'customer_profile'):
                monthly_accounting = get_object_or_404(
                    FactAICMonthlyAccounting.objects.select_related('client'),
                    id=accounting_id,
                    client_id=client_id,
                    client__customer=user.customer_profile
                )
            elif hasattr(user, 'accountant_profile'):
                monthly_accounting = get_object_or_404(
                    FactAICMonthlyAccounting.objects.select_related('client'),
                    id=accounting_id,
                    client_id=client_id,
                    client__customer=user.accountant_profile.customer,
                    client__assigned_accountants=user.accountant_profile
                )
            else:
                return create_api_response(status.HTTP_403_FORBIDDEN, "Access denied.")

            # Fetch the document by PK (document_id) and ensure it belongs to the session
            try:
                document = MonthlyAccountingDocument.objects.select_related('monthly_accounting').get(
                    id=document_id,
                    monthly_accounting=monthly_accounting
                )
            except MonthlyAccountingDocument.DoesNotExist:
                return create_api_response(status.HTTP_404_NOT_FOUND, "Document not found or access denied.")

            # Disallow re-upload if a file already exists (first upload is final)
            if document.file:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "A file has already been uploaded for this document and cannot be replaced."
                )

            if 'file' not in request.FILES:
                return create_api_response(status.HTTP_400_BAD_REQUEST, "No file provided.")

            uploaded_file = request.FILES['file']

            # Assign file and save
            document.file = uploaded_file
            document.uploaded_by = request.user
            document.save()

            logger.info(
                f"Starting processing for document {document.id} of type {document.doc_type}.")

            try:
                service = DocumentProcessingService(document)
                task_id = service.start_processing()
                logger.info(
                    f"Started processing task {task_id} for document {document.id}")

                document.status = "extracting"
                document.save()

            except UnsupportedDocTypeError as e:
                logger.warning(
                    f"Document type {document.doc_type} does not require processing: {e}")

            data = {
                "doc_id": str(document.id),
                "input_file_name": document.input_file_snapshot.name if document.input_file_snapshot else None,
                "id": document.id,
                "doc_type": document.doc_type,
                "status": document.status,
                "file_url": document.file_url,
                "created_at": document.created_at.isoformat(),
                "updated_at": document.updated_at.isoformat()
            }
            return create_api_response(status.HTTP_200_OK, "File uploaded successfully.", data=data)

        except Exception as e:
            logger.error(
                f"Error uploading file for document {document_id} in accounting {accounting_id}, client {client_id}: {str(e)}")

            return create_api_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "An error occurred while uploading the file.", data={"error": str(e)})


class MonthlyAccountingDocumentStatusUpdateView(generics.GenericAPIView):
    """
    Update document status from 'classified' to 'verified'.

    Note: Export file generation has been moved to JEAccountingVerifyView.
    Users should now verify the JE template directly instead of the document.
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountant]

    def post(self, request, client_id, accounting_id, document_id, *args, **kwargs):
        """POST /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/"""
        # Validate integers
        for var_name, value in [("client ID", client_id), ("accounting ID", accounting_id), ("document ID", document_id)]:
            try:
                int(value)
            except ValueError:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid {var_name}."
                )

        # Authorize access similarly to other views
        user = request.user
        if hasattr(user, 'customer_profile'):
            monthly_accounting = get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related('client'),
                id=accounting_id,
                client_id=client_id,
                client__customer=user.customer_profile
            )
        elif hasattr(user, 'accountant_profile'):
            monthly_accounting = get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related('client'),
                id=accounting_id,
                client_id=client_id,
                client__customer=user.accountant_profile.customer,
                client__assigned_accountants=user.accountant_profile
            )
        else:
            return create_api_response(status.HTTP_403_FORBIDDEN, "Access denied.")

        # Fetch the document by PK (document_id) and ensure it belongs to the session
        try:
            document = MonthlyAccountingDocument.objects.select_related('monthly_accounting').get(
                id=document_id,
                monthly_accounting=monthly_accounting
            )
        except MonthlyAccountingDocument.DoesNotExist:
            return create_api_response(status.HTTP_404_NOT_FOUND, "Document not found or access denied.")

        if document.status != 'classified':
            return create_api_response(
                message='Status can only be changed from classified to verified.',
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if request.data.get('status') != "verified":
            return create_api_response(
                message='Status not provided.',
                status_code=status.HTTP_400_BAD_REQUEST
            )

        document.status = 'verified'
        document.save(update_fields=['status'])

        # For bank statements and credit cards, also mark the JE template as verified and generate export file
        if document.doc_type in BANKING_DOCS:
            # Get the input file snapshot
            input_file_snapshot = document.input_file_snapshot

            if input_file_snapshot:
                # Get associated JE template snapshots
                je_template_snapshots = input_file_snapshot.factaicjetemplateheadersnapshot_set.all()

                # Mark templates as verified and generate export files
                for template_snapshot in je_template_snapshots:
                    template_snapshot.status = 'verified'
                    template_snapshot.save(update_fields=['status'])

                    # Generate export file for the template
                    try:
                        from account.accounting.monthly_accounting_views import JEAccountingVerifyView
                        JEAccountingVerifyView.generate_export_file(
                            template_snapshot)
                        logger.error(
                            f"Generated export file for JE template {template_snapshot.id}")
                    except Exception as e:
                        logger.error(
                            f"Error generating export file for JE template {template_snapshot.id}: {str(e)}")
                        # Don't fail the whole operation if export generation fails
                        pass

        return create_api_response(
            message='Document verified successfully. Export file has been generated for bank statement/credit card templates.' if document.doc_type in BANKING_DOCS else 'Document verified successfully. Please proceed to verify the JE Template.',
            status_code=status.HTTP_200_OK
        )


class MonthlyAccountingDocumentLineItemListCreateView(generics.GenericAPIView):
    """List & Create line items for a processed monthly accounting document (bank_statement/credit_card)."""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountantOrReviewer]

    def _get_document(self, client_id, accounting_id, document_id, request):
        user = request.user
        if hasattr(user, 'customer_profile'):
            monthly_accounting = get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related('client'),
                id=accounting_id,
                client_id=client_id,
                client__customer=user.customer_profile
            )
        elif hasattr(user, 'accountant_profile'):
            monthly_accounting = get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related('client'),
                id=accounting_id,
                client_id=client_id,
                client__customer=user.accountant_profile.customer,
                client__assigned_accountants=user.accountant_profile
            )
        else:
            return None, create_api_response(status.HTTP_403_FORBIDDEN, "Access denied.")
        document = get_object_or_404(
            MonthlyAccountingDocument.objects.select_related(
                'monthly_accounting'),
            id=document_id,
            monthly_accounting=monthly_accounting
        )

        # Remove the document type restriction - now we support all document types
        return document, None

    def get(self, request, client_id, accounting_id, document_id, *args, **kwargs):
        """
        Retrieve line items for a processed monthly accounting document.
        Supports both bank statement/credit card line items and attribute items for other document types.

        GET /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/lines/
        """
        try:
            document, error_response = self._get_document(
                client_id, accounting_id, document_id, request)
            if error_response:
                return error_response

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
                "Line items retrieved successfully.",
                data=response_data
            )
        except Exception as e:
            logger.error(
                f"Error retrieving line items for document {document_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving line items.",
                data={"error": str(e)}
            )

    def post(self, request, client_id, accounting_id, document_id, *args, **kwargs):
        """
        Create a new line item for a monthly accounting document.
        For bank/credit card: create bank line items
        For other types: create attribute items (only for missing attributes)

        POST /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/lines/

        For bank/credit card:
        {
            "page_number": 1,
            "line_number": 5,  // optional - will append if not provided
            "date": "2025-01-15",
            "description": "Office supplies purchase",
            "debit": "125.50",  // either debit OR credit, not both
            "gl_account_id": 123
        }

        For other document types:
        {
            "page_number": 1,
            "attribute_id": 456,  // must be an attribute not yet extracted
            "value": "some value",
            "gl_account_id": 123
        }
        """
        try:
            document, error_response = self._get_document(
                client_id, accounting_id, document_id, request)
            if error_response:
                return error_response

            if document.doc_type in BANKING_DOCS:
                # Create bank line item
                serializer = MonthlyDocumentBankLineItemSerializer(
                    data=request.data,
                    context={'request': request, 'document': document}
                )
            else:
                # Create attribute item - check if attribute is already extracted
                attribute_id = request.data.get('attribute_id')
                if not attribute_id:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "attribute_id is required for non-bank documents."
                    )

                # Check if this attribute already has an extracted item
                existing_item = MonthlyDocumentAttributeItem.objects.filter(
                    document=document,
                    attribute_id=attribute_id
                ).first()

                if existing_item:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        f"Attribute item for this attribute already exists. Use PATCH to update it."
                    )

                # Verify attribute belongs to the input file snapshot
                if not document.input_file_snapshot:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Document has no input file snapshot."
                    )

                attribute_exists = document.input_file_snapshot.attribute_snapshots.filter(
                    id=attribute_id
                ).exists()

                if not attribute_exists:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Invalid attribute_id. Attribute does not belong to this document's template."
                    )

                serializer = MonthlyDocumentAttributeItemSerializer(
                    data=request.data,
                    context={'request': request, 'document': document}
                )

            if serializer.is_valid():
                item = serializer.save()

                # Use the appropriate serializer for output
                if document.doc_type in BANKING_DOCS:
                    output_serializer = MonthlyDocumentBankLineItemSerializer(
                        item, context={'request': request})
                else:
                    output_serializer = MonthlyDocumentAttributeItemSerializer(
                        item, context={'request': request})

                return create_api_response(
                    status.HTTP_201_CREATED,
                    "Line item created successfully.",
                    data=output_serializer.data
                )

            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Validation failed.",
                data=serializer.errors
            )

        except Exception as e:
            logger.error(
                f"Error creating line item for document {document_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while creating line item.",
                data={"error": str(e)}
            )


class MonthlyAccountingDocumentLineItemDetailView(generics.GenericAPIView):
    """Retrieve, Update, or Delete a specific line item."""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountantOrReviewer]

    def _get_line_item(self, client_id, accounting_id, document_id, line_item_id, request):
        """Helper method to get line item with proper authorization - supports both BankLineItem and AttributeItem"""

        user = request.user
        if hasattr(user, 'customer_profile'):
            monthly_accounting = get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related('client'),
                id=accounting_id,
                client_id=client_id,
                client__customer=user.customer_profile
            )
        elif hasattr(user, 'accountant_profile'):
            monthly_accounting = get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related('client'),
                id=accounting_id,
                client_id=client_id,
                client__customer=user.accountant_profile.customer,
                client__assigned_accountants=user.accountant_profile
            )
        else:
            return None, None, create_api_response(status.HTTP_403_FORBIDDEN, "Access denied.")

        document = get_object_or_404(
            MonthlyAccountingDocument,
            id=document_id,
            monthly_accounting=monthly_accounting
        )

        # Try to fetch the appropriate line item based on document type
        if document.doc_type in BANKING_DOCS:
            line_item = get_object_or_404(
                MonthlyDocumentBankLineItem,
                id=line_item_id,
                document=document
            )
            item_type = 'banking_type'
        else:
            line_item = get_object_or_404(
                MonthlyDocumentAttributeItem,
                id=line_item_id,
                document=document
            )
            item_type = 'kv_type'

        return line_item, item_type, None

    def patch(self, request, client_id, accounting_id, document_id, line_item_id, *args, **kwargs):
        """
        Update a specific line item. Supports both bank line items and attribute items.

        PATCH /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/lines/{line_item_id}/

        For bank/credit card:
        {
            "description": "Updated description",
            "credit": "150.00",  // will change from debit to credit
            "gl_account_id": 456
        }

        For other document types:
        {
            "value": "updated value",
            "gl_account_id": 456
        }
        """
        try:
            line_item, item_type, error_response = self._get_line_item(
                client_id, accounting_id, document_id, line_item_id, request
            )
            if error_response:
                return error_response

            # Use appropriate serializer based on item type
            if item_type == 'banking_type':
                serializer = MonthlyDocumentBankLineItemSerializer(
                    line_item,
                    data=request.data,
                    partial=True,
                    context={'request': request}
                )
            else:
                serializer = MonthlyDocumentAttributeItemSerializer(
                    line_item,
                    data=request.data,
                    partial=True,
                    context={'request': request}
                )

            if serializer.is_valid():
                updated_item = serializer.save()

                # Use appropriate output serializer
                if item_type == 'banking_type':
                    output_serializer = MonthlyDocumentBankLineItemSerializer(
                        updated_item, context={'request': request}
                    )
                else:
                    output_serializer = MonthlyDocumentAttributeItemSerializer(
                        updated_item, context={'request': request}
                    )

                return create_api_response(
                    status.HTTP_200_OK,
                    "Line item updated successfully.",
                    data=output_serializer.data
                )

            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Validation failed.",
                errors=serializer.errors
            )

        except Exception as e:
            logger.error(f"Error updating line item {line_item_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while updating line item.",
                data={"error": str(e)}
            )

    def delete(self, request, client_id, accounting_id, document_id, line_item_id, *args, **kwargs):
        """
        Delete a specific line item.
        For bank items: renumber subsequent lines.
        For attribute items: just delete (no renumbering needed).

        DELETE /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/lines/{line_item_id}/
        """
        try:
            line_item, item_type, error_response = self._get_line_item(
                client_id, accounting_id, document_id, line_item_id, request
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
                    ).update(line_number=models.F('line_number') - 1)

                    logger.error(
                        f"Deleted line {deleted_line_number} and renumbered {updated_count} subsequent lines")

                return create_api_response(
                    status.HTTP_200_OK,
                    f"Line item deleted successfully. Renumbered {updated_count} subsequent lines."
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
                "An error occurred while deleting line item.",
                data={"error": str(e)}
            )


class MonthlyAccountingYearsListView(generics.GenericAPIView):
    """List distinct years for which accounting records exist for a client"""

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]

    def get(self, request, client_id, *args, **kwargs):
        """
        List distinct years that have monthly accounting records for a client.

        GET /api/clients/{client_id}/accounting/monthly/years/
        """
        try:
            user = request.user
            if hasattr(user, 'customer_profile'):
                customer = user.customer_profile
                client = get_object_or_404(
                    DimAICClient, id=client_id, customer=customer)
            elif hasattr(user, 'accountant_profile'):
                accountant = user.accountant_profile
                client = get_object_or_404(
                    DimAICClient,
                    id=client_id,
                    customer=accountant.customer,
                    assigned_accountants=accountant
                )
            else:
                return create_api_response(
                    status.HTTP_403_FORBIDDEN,
                    "Access denied."
                )

            years = (
                FactAICMonthlyAccounting.objects
                .filter(client=client, is_deleted=False)
                .values_list('year', flat=True)
                .distinct()
                .order_by('-year')
            )

            return create_api_response(
                status.HTTP_200_OK,
                f"Years retrieved successfully for client {client.client_name}.",
                data={
                    'client': client.id,
                    'client_name': client.client_name,
                    'years': list(years)
                }
            )

        except Exception as e:
            logger.error(
                f"Error listing accounting years for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving accounting years.",
                data={"error": str(e)}
            )


class MonthlyAccountingDeleteView(generics.GenericAPIView):
    """Soft-delete a monthly accounting session"""

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]

    def delete(self, request, client_id, accounting_id, *args, **kwargs):
        """
        Soft-delete a monthly accounting session.
        Sets is_deleted=True and deleted_at to the current timestamp.

        DELETE /api/clients/{client_id}/accounting/monthly/{accounting_id}/soft-delete/
        """
        try:
            accounting_id = int(accounting_id)
        except ValueError:
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Invalid accounting ID."
            )

        try:
            user = request.user
            if hasattr(user, 'customer_profile'):
                customer = user.customer_profile
                monthly_accounting = get_object_or_404(
                    FactAICMonthlyAccounting.objects.select_related('client'),
                    id=accounting_id,
                    client_id=client_id,
                    client__customer=customer,
                    is_deleted=False
                )
            elif hasattr(user, 'accountant_profile'):
                accountant = user.accountant_profile
                monthly_accounting = get_object_or_404(
                    FactAICMonthlyAccounting.objects.select_related('client'),
                    id=accounting_id,
                    client_id=client_id,
                    client__customer=accountant.customer,
                    client__assigned_accountants=accountant,
                    is_deleted=False
                )
            else:
                return create_api_response(
                    status.HTTP_403_FORBIDDEN,
                    "Access denied."
                )

            client_name = monthly_accounting.client.client_name
            month_name = monthly_accounting.get_month_name()
            year = monthly_accounting.year

            monthly_accounting.is_deleted = True
            monthly_accounting.deleted_at = timezone.now()
            monthly_accounting.save(update_fields=['is_deleted', 'deleted_at'])

            return create_api_response(
                status.HTTP_200_OK,
                f"Monthly accounting for {client_name} - {month_name} {year} has been soft-deleted successfully."
            )

        except Exception as e:
            logger.error(
                f"Error soft-deleting monthly accounting {accounting_id} for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while soft-deleting monthly accounting.",
                data={"error": str(e)}
            )
