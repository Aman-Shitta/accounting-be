from django.shortcuts import get_object_or_404
from django.db import transaction, models
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import generics, status, permissions
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .models import FactAICMonthlyAccounting
from user.models import DimAICClient
from authentication import authenticate
from authentication.permissions import IsCustomerOrAccountant
from aicounting.response import create_api_response
from rest_framework.parsers import JSONParser

import logging
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
                client = get_object_or_404(DimAICClient, id=client_id, customer=customer)
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
                valid_statuses = [choice[0] for choice in FactAICMonthlyAccounting.STATUS_CHOICES]
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
            logger.error(f"Error listing monthly accounting sessions for client {client_id}: {str(e)}")
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
                client = get_object_or_404(DimAICClient, id=client_id, customer=customer)
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
            logger.error(f"Validation error creating monthly accounting for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Validation error occurred while creating monthly accounting.",
                data={"error": str(e)}
            )
        
        except Exception as e:
            logger.error(f"Error creating monthly accounting for client {client_id}: {str(e)}")
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
                FactAICMonthlyAccounting.objects.select_related('client', 'created_by'),
                id=accounting_id,
                client=client_id,
                client__customer=customer
            )
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related('client', 'created_by'),
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
            from .models.monthly_accounting_document_model import MonthlyAccountingDocument
            
            documents = MonthlyAccountingDocument.objects.filter(
                monthly_accounting=monthly_accounting
            ).select_related('input_file_snapshot')
            
            input_documents = []
            for document in documents:
                input_documents.append({
                    "id": document.id,
                    "doc_id": str(document.doc_id),
                    "doc_type": document.doc_type,
                    "status": document.upload_status,
                    "upload_status": document.get_upload_status_display(),
                    "file_url": document.file_url,
                    "created_at": document.created_at.isoformat(),
                    "updated_at": document.updated_at.isoformat()
                })

            # Get JE template snapshots (basic info only)
            je_template_snapshots = monthly_accounting.je_template_snapshots.select_related(
                'original_template', 'je_type'
            )
            
            je_templates = []
            for template_snapshot in je_template_snapshots:
                je_templates.append({
                    "id": template_snapshot.id,  # Snapshot ID
                    "name": template_snapshot.je_name,
                    "je_type": template_snapshot.je_type.je_type if template_snapshot.je_type else None,
                    "created_at": template_snapshot.original_created_at.isoformat() if template_snapshot.original_created_at else None,
                    "updated_at": template_snapshot.original_updated_at.isoformat() if template_snapshot.original_updated_at else None
                })

            # Build the response data
            data = {
                "id": monthly_accounting.id,
                "month": monthly_accounting.get_month_name(),
                "year": monthly_accounting.year,
                "status": monthly_accounting.status,
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
            logger.error(f"Error retrieving monthly accounting {accounting_id} for client {client_id}: {str(e)}")
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
            
            valid_statuses = [choice[0] for choice in FactAICMonthlyAccounting.STATUS_CHOICES]
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
            logger.error(f"Error updating status for accounting {accounting_id}, client {client_id}: {str(e)}")
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
            logger.error(f"Error deleting monthly accounting {accounting_id} for client {client_id}: {str(e)}")
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
            from .models.monthly_accounting_document_model import MonthlyAccountingDocument

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

            # Assign file and mark uploaded
            document.file = uploaded_file
            document.mark_as_uploaded(request.user)

            if document.doc_type in ['bank_statement', 'credit_card']:
                
                from extractor.bank_statement.prompter import Configuration
                config = Configuration(
                    doc_type="bank_statement",
                    extract_line_items=True,
                    line_items=[
                        "date: The date of the transaction.", 
                        "description: A description of the transaction.",
                        "debit amount: The debit amount of the transaction.",
                        "credit amount: The credit amount of the transaction.",
                    ],
                    excluded_fields=[]
                )
                # Trigger document processing task
                from .tasks import process_uploaded_document
                process_uploaded_document.run(document, config)
            else:
                logger.info(f"Document type {document.doc_type} does not require processing.")

            data = {
                "doc_uuid": str(document.doc_id),
                "id": document.id,
                "doc_type": document.doc_type,
                "status": document.upload_status,
                "upload_status": document.get_upload_status_display(),
                "file_url": document.file_url,
                "created_at": document.created_at.isoformat(),
                "updated_at": document.updated_at.isoformat()
            }
            return create_api_response(status.HTTP_200_OK, "File uploaded successfully.", data=data)

        except Exception as e:
            logger.error(f"Error uploading file for document {document_id} in accounting {accounting_id}, client {client_id}: {str(e)}")
            return create_api_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "An error occurred while uploading the file.", data={"error": str(e)})


class MonthlyAccountingDocumentLineItemListCreateView(generics.GenericAPIView):
    """List & Create line items for a processed monthly accounting document (bank_statement/credit_card)."""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountant]

    def _get_document(self, client_id, accounting_id, document_id, request):
        from .models.monthly_accounting_document_model import MonthlyAccountingDocument
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
            MonthlyAccountingDocument.objects.select_related('monthly_accounting'),
            id=document_id,
            monthly_accounting=monthly_accounting
        )
        if document.doc_type not in ['bank_statement', 'credit_card']:
            return None, create_api_response(status.HTTP_400_BAD_REQUEST, "Document type does not support line items interface.")
        return document, None

    def get(self, request, client_id, accounting_id, document_id, *args, **kwargs):
        """
        Retrieve line items for a processed monthly accounting document.
        
        GET /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/lines/
        """
        try:
            from .models.monthly_document_line_models import MonthlyDocumentBankLineItem
            from .monthly_document_line_item_serializers import MonthlyDocumentBankLineItemSerializer
            
            document, error_response = self._get_document(client_id, accounting_id, document_id, request)
            if error_response:
                return error_response
            
            items = MonthlyDocumentBankLineItem.objects.filter(document=document).select_related('gl_account', 'offset_gl_account').order_by('page_number', 'line_number')
            serializer = MonthlyDocumentBankLineItemSerializer(items, many=True, context={'request': request})
            
            return create_api_response(
                status.HTTP_200_OK, 
                "Line items retrieved successfully.", 
                data={
                    'document_id': document.id,
                    'doc_uuid': str(document.doc_id),
                    'doc_type': document.doc_type,
                    'total_line_items': items.count(),
                    'line_items': serializer.data
                }
            )
        except Exception as e:
            logger.error(f"Error retrieving line items for document {document_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving line items.",
                data={"error": str(e)}
            )

    def post(self, request, client_id, accounting_id, document_id, *args, **kwargs):
        """
        Create a new line item for a monthly accounting document.
        
        POST /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/lines/
        
        Body:
        {
            "page_number": 1,
            "line_number": 5,  // optional - will append if not provided
            "date": "2025-01-15",
            "description": "Office supplies purchase",
            "debit": "125.50",  // either debit OR credit, not both
            "gl_account_id": 123
        }
        """
        try:
            from .monthly_document_line_item_serializers import MonthlyDocumentBankLineItemSerializer
            
            document, error_response = self._get_document(client_id, accounting_id, document_id, request)
            if error_response:
                return error_response
            
            serializer = MonthlyDocumentBankLineItemSerializer(
                data=request.data, 
                context={'request': request, 'document': document}
            )
            
            if serializer.is_valid():
                item = serializer.save()
                output_serializer = MonthlyDocumentBankLineItemSerializer(item, context={'request': request})
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
            logger.error(f"Error creating line item for document {document_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while creating line item.",
                data={"error": str(e)}
            )


class MonthlyAccountingDocumentLineItemDetailView(generics.GenericAPIView):
    """Retrieve, Update, or Delete a specific line item."""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountant]

    def _get_line_item(self, client_id, accounting_id, document_id, line_item_id, request):
        """Helper method to get line item with proper authorization"""
        from .models.monthly_accounting_document_model import MonthlyAccountingDocument
        from .models.monthly_document_line_models import MonthlyDocumentBankLineItem
        
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
            MonthlyAccountingDocument, 
            id=document_id, 
            monthly_accounting=monthly_accounting
        )
        
        if document.doc_type not in ['bank_statement', 'credit_card']:
            return None, create_api_response(
                status.HTTP_400_BAD_REQUEST, 
                "Document type does not support line items interface."
            )
        
        line_item = get_object_or_404(
            MonthlyDocumentBankLineItem, 
            id=line_item_id, 
            document=document
        )
        return line_item, None

    def patch(self, request, client_id, accounting_id, document_id, line_item_id, *args, **kwargs):
        """
        Update a specific line item.
        
        PATCH /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/lines/{line_item_id}/
        
        Body:
        {
            "description": "Updated description",
            "credit": "150.00",  // will change from debit to credit
            "gl_account_id": 456
        }
        """
        try:
            from .monthly_document_line_item_serializers import MonthlyDocumentBankLineItemSerializer
            
            line_item, error_response = self._get_line_item(client_id, accounting_id, document_id, line_item_id, request)
            if error_response:
                return error_response
            
            serializer = MonthlyDocumentBankLineItemSerializer(
                line_item, 
                data=request.data, 
                partial=True, 
                context={'request': request}
            )
            
            if serializer.is_valid():
                updated_item = serializer.save()
                output_serializer = MonthlyDocumentBankLineItemSerializer(updated_item, context={'request': request})
                return create_api_response(
                    status.HTTP_200_OK, 
                    "Line item updated successfully.", 
                    data=output_serializer.data
                )
            
            return create_api_response(
                status.HTTP_400_BAD_REQUEST, 
                "Validation failed.", 
                data=serializer.errors
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
        Delete a specific line item and renumber subsequent lines.
        
        DELETE /api/clients/{client_id}/accounting/monthly/{accounting_id}/documents/{document_id}/lines/{line_item_id}/
        """
        try:
            from .models.monthly_document_line_models import MonthlyDocumentBankLineItem
            
            line_item, error_response = self._get_line_item(client_id, accounting_id, document_id, line_item_id, request)
            if error_response:
                return error_response
            
            page_number = line_item.page_number
            document = line_item.document
            deleted_line_number = line_item.line_number
            
            with transaction.atomic():
                # Delete the line item
                line_item.delete()
                
                # Renumber subsequent lines on the same page
                # Use bulk update for efficiency - subtract 1 from all lines after the deleted line
                updated_count = MonthlyDocumentBankLineItem.objects.filter(
                    document=document, 
                    page_number=page_number, 
                    line_number__gt=deleted_line_number
                ).update(line_number=models.F('line_number') - 1)
                
                logger.info(f"Deleted line {deleted_line_number} and renumbered {updated_count} subsequent lines")
            
            return create_api_response(
                status.HTTP_200_OK, 
                f"Line item deleted successfully. Renumbered {updated_count} subsequent lines."
            )
        
        except Exception as e:
            logger.error(f"Error deleting line item {line_item_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while deleting line item.",
                data={"error": str(e)}
            )
