
from django.conf import settings
from django.db import transaction

from rest_framework import generics, permissions, status

from .models import DimAICClient
from .client_serializers import (
    ClientCreateUpdateSerializer, 
    ClientRetrieveSerializer,
    ContactSerializer,
    ClientDocumentUploadSerializer,
    ClientAccountantAssignmentSerializer,
    DimAICAccountantSerializer,
)

from authentication import authenticate
from authentication.permissions import IsCustomer
from aicounting.response import create_api_response

from .utils import OpenAIAssistant

import logging
logger = logging.getLogger(__name__)


class ClientCreateView(generics.GenericAPIView):
    """
    Create a new client with associated contacts and documents.
    Supports nested creation of contacts and documents in a single request.
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication] 
    permission_classes = [permissions.IsAuthenticated, IsCustomer] 
    serializer_class = ClientCreateUpdateSerializer
    queryset = DimAICClient.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context

    
    def _parse_contacts_data(self, data):
        """
        Parse form data to handle nested structures like contacts[0][contact_name]
        """
        import re
        from collections import defaultdict
        
        parsed_data = {}
        contacts_data = defaultdict(dict)
        
        # Regular expression to match nested form data patterns
        contact_pattern = re.compile(r'contacts\[(\d+)\]\[(\w+)\]')
        
        for key, value in data.items():
            # Check if this is a contact field
            contact_match = contact_pattern.match(key)
            if contact_match:
                index = int(contact_match.group(1))
                field_name = contact_match.group(2)
                contacts_data[index][field_name] = value
            else:
                # Regular field
                parsed_data[key] = value
        
        # Convert contacts defaultdict to list
        if contacts_data:
            contacts_list = []
            for i in sorted(contacts_data.keys()):
                contacts_list.append(contacts_data[i])
            parsed_data['contacts'] = contacts_list
        
        return parsed_data

    def post(self, request, *args, **kwargs):
        try:

            # Use atomic transaction for all operations
            with transaction.atomic():
                parsed_data = self._parse_contacts_data(request.data)

                serializer = self.get_serializer(data=parsed_data)
                if not serializer.is_valid():
                    logger.error(f"Client creation validation failed: {serializer.errors}")
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Client creation failed due to validation errors.",
                        data=serializer.errors
                    )

                # Create the client and related objects
                client = serializer.save()

                # client_assistant = OpenAIAssistant(
                #     api_key=settings.OPENAI_API_KEY,
                #     client_id=client.client_id,
                #     special_rules=serializer.validated_data.get('special_rules', None)
                # )
                # Provision the client GPT assistant
                # client_assistant.provison_client_assistant()

                # Return success response with created client data
                response_serializer = ClientRetrieveSerializer(client)
                logger.info(f"Client created successfully: {client.client_id}")
                
                return create_api_response(
                    status.HTTP_201_CREATED,
                    "Client created successfully.",
                    data=response_serializer.data
                )
            
        except Exception as e:
            import os, sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)

            logger.error(f"Unexpected error during client creation: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred during client creation.",
                data={"error": str(e)}
            )

class ClientListView(generics.GenericAPIView):
    """List all clients for the authenticated customer"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication] 
    permission_classes = [permissions.IsAuthenticated, IsCustomer] 
    serializer_class = ClientRetrieveSerializer

    def get_queryset(self):
        customer = self.request.user.customer_profile
        if customer:
            return DimAICClient.objects.filter(customer=customer)
        return DimAICClient.objects.none()

    def get(self, request, *args, **kwargs):
        """
        Override get method to handle custom response structure
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        
        return create_api_response(
            status.HTTP_200_OK,
            "Client list retrieved successfully.",
            data=serializer.data
        )

class ClientRetrieveView(generics.GenericAPIView):
    """Retrieve a specific client by ID"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication] 
    permission_classes = [permissions.IsAuthenticated, IsCustomer] 
    serializer_class = ClientRetrieveSerializer

    def get_queryset(self, id):
        customer = self.request.user.customer_profile
        if customer:
            return DimAICClient.objects.filter(customer=customer, id=id)
        return DimAICClient.objects.none()

    def get(self, request, *args, **kwargs):
        """
        Override get method to handle custom response structure
        """
        assigned_id = kwargs.get('id')
        queryset = self.get_queryset(assigned_id)
        
        if not queryset.exists():
            return create_api_response(
                status.HTTP_404_NOT_FOUND,
                "Client not found.",
                data={}
            )
        
        client = queryset.first()
        serializer = self.get_serializer(client)
        
        return create_api_response(
            status.HTTP_200_OK,
            "Client retrieved successfully.",
            data=serializer.data
        )

class ClientUpdateView(generics.GenericAPIView):
    """Update client information with support for contacts and documents"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication] 
    permission_classes = [permissions.IsAuthenticated, IsCustomer] 
    serializer_class = ClientCreateUpdateSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context

    def get_object(self, client_id):
        customer = self.request.user.customer_profile
        if customer:
            try:
                return DimAICClient.objects.get(customer=customer, id=client_id)
            except DimAICClient.DoesNotExist:
                logger.error("Client not found for update.")
                return None
        return None

    def _parse_contacts_data(self, data):
        """
        Parse form data to handle nested structures like contacts[0][contact_name]
        """
        import re
        from collections import defaultdict
        
        parsed_data = {}
        contacts_data = defaultdict(dict)
        
        # Regular expression to match nested form data patterns
        contact_pattern = re.compile(r'contacts\[(\d+)\]\[(\w+)\]')
        
        for key, value in data.items():
            # Check if this is a contact field
            contact_match = contact_pattern.match(key)
            if contact_match:
                index = int(contact_match.group(1))
                field_name = contact_match.group(2)
                contacts_data[index][field_name] = value
            else:
                # Regular field
                parsed_data[key] = value
        
        # Convert contacts defaultdict to list
        if contacts_data:
            contacts_list = []
            for i in sorted(contacts_data.keys()):
                contacts_list.append(contacts_data[i])
            parsed_data['contacts'] = contacts_list
        
        return parsed_data

    def put(self, request, *args, **kwargs):
        try:
            # Use atomic transaction for update
            with transaction.atomic():
                instance = self.get_object(kwargs.get('id'))
                if not instance:
                    return create_api_response(
                        status.HTTP_404_NOT_FOUND,
                        "Client not found or you don't have permission to update it."
                    )

                # Check if data is sent as JSON in 'data' field (recommended approach)
                if 'data' in request.data:
                    import json
                    try:
                        json_data = json.loads(request.data['data'])
                        # Merge JSON data with files
                        combined_data = json_data.copy()
                        # Add files to the data
                        for key, file in request.FILES.items():
                            combined_data[key] = file
                        serializer_data = combined_data
                    except json.JSONDecodeError:
                        return create_api_response(
                            status.HTTP_400_BAD_REQUEST,
                            "Invalid JSON in 'data' field.",
                            data={}
                        )
                else:
                    # Fallback to old form-data parsing
                    serializer_data = self._parse_contacts_data(request.data)
                    # Add files to parsed data
                    for key, file in request.FILES.items():
                        serializer_data[key] = file
                
                serializer = self.get_serializer(instance, data=serializer_data, partial=True)
                
                if not serializer.is_valid():
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Client update failed due to validation errors.",
                        data=serializer.errors
                    )

                client = serializer.save()
                response_serializer = ClientRetrieveSerializer(client)
                
                return create_api_response(
                    status.HTTP_200_OK,
                    "Client updated successfully.",
                    data=response_serializer.data
                )
            
        except Exception as e:
            logger.error(f"Unexpected error during client update: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred during client update.",
                error={"error": str(e)}
            )

class ContactCreateView(generics.GenericAPIView):
    """Create a new contact for a specific client"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication] 
    permission_classes = [permissions.IsAuthenticated, IsCustomer] 
    serializer_class = ContactSerializer

    def post(self, request, *args, **kwargs):
        try:
            client_id = kwargs.get('id')
            
            # Use atomic transaction for contact creation
            with transaction.atomic():
                # Get the client
                customer = self.request.user.customer_profile
                if not customer:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "No customer found.",
                        data={}
                    )
                    
                try:
                    client = DimAICClient.objects.get(
                        id=client_id, 
                        customer=customer
                    )
                except DimAICClient.DoesNotExist:
                    return create_api_response(
                        status.HTTP_404_NOT_FOUND,
                        "Client not found.",
                        data={}
                    )

                if client.contacts:
                    logger.error(f"Client {client_id} already has contacts.")
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Client already has contacts.",
                        data={}
                    )
                serializer = self.get_serializer(data=request.data)
                if not serializer.is_valid():
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Contact creation failed due to validation errors.",
                        data=serializer.errors
                    )

                # Create the contact
                serializer.save(client=client)
                
                return create_api_response(
                    status.HTTP_201_CREATED,
                    "Contact created successfully.",
                    data=serializer.data
                )
            
        except Exception as e:
            logger.error(f"Unexpected error during contact creation: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred during contact creation.",
                error={"error": str(e)}
            )

class DocumentUploadView(generics.GenericAPIView):
    """Upload a document for a specific client"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication] 
    permission_classes = [permissions.IsAuthenticated, IsCustomer] 
    serializer_class = ClientDocumentUploadSerializer

    def post(self, request, *args, **kwargs):
        try:
            client_id = kwargs.get('id')

            # Use atomic transaction for document upload
            with transaction.atomic():
                # Get the customer from the authenticated user
                customer = getattr(request.user, 'customer_profile', None)
                if not customer:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "User must have a customer profile.",
                        data={}
                    )
                    
                try:
                    client = DimAICClient.objects.get(
                        id=client_id, 
                        customer=customer
                    )
                except DimAICClient.DoesNotExist:
                    return create_api_response(
                        status.HTTP_404_NOT_FOUND,
                        "Client not found.",
                        data={}
                    )

                # Prepare the data - extract files from request.FILES based on document types
                document_files = {}
                valid_types = ['gl_history', 'vendor_list']

                for doc_type in valid_types:
                    if doc_type in request.FILES:
                        document_files[doc_type] = request.FILES[doc_type]

                serializer = self.get_serializer(
                    data=document_files,
                    context={
                        'client': client,
                        'uploaded_by': request.user
                    }
                )
                
                if not serializer.is_valid():
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Document upload failed due to validation errors.",
                        data=serializer.errors
                    )

                # Create and process the documents
                result = serializer.save()
                
                client_assistant = OpenAIAssistant(
                    api_key=settings.OPENAI_API_KEY,
                    client_id=client.client_id,
                    special_rules=serializer.validated_data.get('special_rules', None)
                )
                # Provision the client GPT assistant
                document_ids = [doc.id for doc in result['documents']]
                client_assistant.update_assistant_with_new_files(new_document_ids=document_ids)

                # Prepare response data
                response_data = {
                    'uploaded_documents': len(result['documents']),
                    'processing_results': result['processing_results'],
                    'documents': [
                        {
                            'id': doc.id,
                            'document_type': doc.document_type,
                            'file_name': doc.file.name,
                            'created_at': doc.created_at
                        }
                        for doc in result['documents']
                    ]
                }
                
                # Check if all processing was successful
                all_successful = all(
                    res['success'] for res in result['processing_results'].values()
                )
                
                if all_successful:
                    message = f"Successfully uploaded and processed {len(result['documents'])} documents."
                else:
                    message = f"Uploaded {len(result['documents'])} documents with some processing errors. Check processing_results for details."
                
                return create_api_response(
                    status.HTTP_201_CREATED,
                    message,
                    data=response_data
                )
            
        except Exception as e:
            logger.error(f"Unexpected error during multiple document upload: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred during document upload.",
                data={"error": str(e)}
            )


class ClientAssignAccountantsView(generics.GenericAPIView):
    """Assign or update accountants for a specific client"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication] 
    permission_classes = [permissions.IsAuthenticated, IsCustomer] 
    serializer_class = ClientAccountantAssignmentSerializer

    def get_object(self, client_id):
        """Get client instance for the authenticated customer"""
        customer = self.request.user.customer_profile
        if customer:
            try:
                return DimAICClient.objects.get(customer=customer, id=client_id)
            except DimAICClient.DoesNotExist:
                return None
        return None

    def put(self, request, *args, **kwargs):
        """Assign accountants to a client"""
        try:
            client_id = kwargs.get('id')
            client = self.get_object(client_id)
            
            if not client:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Client not found or you don't have permission to modify it."
                )

            # Validate that accountant IDs belong to the same customer
            accountant_ids = request.data.get('assigned_accountants', [])
            customer = request.user.customer_profile
            
            # Check if all provided accountants belong to the customer
            valid_accountants = customer.accountants.filter(id__in=accountant_ids)
            if len(valid_accountants) != len(accountant_ids):
                invalid_ids = set(accountant_ids) - set(valid_accountants.values_list('id', flat=True))
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid accountant IDs: {list(invalid_ids)}. Accountants must belong to your organization."
                )

            serializer = self.get_serializer(client, data=request.data, partial=True)
            
            if not serializer.is_valid():
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Assignment failed due to validation errors.",
                    data=serializer.errors
                )

            updated_client = serializer.save()
            
            # Return updated client with assigned accountants
            response_data = {
                'client_id': updated_client.id,
                'client_name': updated_client.client_name,
                'assigned_accountants': DimAICAccountantSerializer(
                    updated_client.assigned_accountants.all(), 
                    many=True
                ).data
            }
            
            return create_api_response(
                status.HTTP_200_OK,
                "Accountants assigned successfully.",
                data=response_data
            )
            
        except Exception as e:
            logger.error(f"Unexpected error during accountant assignment: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred during accountant assignment.",
                data={"error": str(e)}
            )


class ClientAssignedAccountantsView(generics.GenericAPIView):
    """Retrieve all accountants assigned to a specific client"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication] 
    permission_classes = [permissions.IsAuthenticated, IsCustomer] 
    serializer_class = DimAICAccountantSerializer

    def get_object(self, client_id):
        """Get client instance for the authenticated customer"""
        customer = self.request.user.customer_profile
        if customer:
            try:
                return DimAICClient.objects.get(customer=customer, id=client_id)
            except DimAICClient.DoesNotExist:
                return None
        return None

    def get(self, request, *args, **kwargs):
        """Get all accountants assigned to a client"""
        try:
            client_id = kwargs.get('id')
            client = self.get_object(client_id)
            
            if not client:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Client not found or you don't have permission to view it."
                )

            # Get all assigned accountants
            assigned_accountants = client.assigned_accountants.all()
            serializer = self.get_serializer(assigned_accountants, many=True)
            
            response_data = {
                'client_id': client.id,
                'client_name': client.client_name,
                'total_assigned_accountants': assigned_accountants.count(),
                'assigned_accountants': serializer.data
            }
            
            return create_api_response(
                status.HTTP_200_OK,
                "Assigned accountants retrieved successfully.",
                data=response_data
            )
            
        except Exception as e:
            logger.error(f"Unexpected error retrieving assigned accountants: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred while retrieving assigned accountants.",
                data={"error": str(e)}
            )


class ClientUnassignAccountantsView(generics.GenericAPIView):
    """Unassign specific accountants from a client"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication] 
    permission_classes = [permissions.IsAuthenticated, IsCustomer] 
    serializer_class = DimAICAccountantSerializer

    def get_object(self, client_id):
        """Get client instance for the authenticated customer"""
        customer = self.request.user.customer_profile
        if customer:
            try:
                return DimAICClient.objects.get(customer=customer, id=client_id)
            except DimAICClient.DoesNotExist:
                return None
        return None

    def delete(self, request, *args, **kwargs):
        """Remove specific accountants from a client"""
        try:
            client_id = kwargs.get('id')
            client = self.get_object(client_id)
            
            if not client:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Client not found or you don't have permission to modify it."
                )

            # Get accountant IDs to remove from request body or query params
            accountant_ids = request.data.get('accountant_ids', [])
            
            if not accountant_ids:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Please provide accountant_ids to unassign."
                )

            # Validate that accountants are currently assigned to this client
            currently_assigned = client.assigned_accountants.filter(id__in=accountant_ids)
            
            if currently_assigned.count() != len(accountant_ids):
                assigned_ids = set(currently_assigned.values_list('id', flat=True))
                invalid_ids = set(accountant_ids) - assigned_ids
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Accountant IDs {list(invalid_ids)} are not currently assigned to this client."
                )

            # Remove the accountants
            client.assigned_accountants.remove(*accountant_ids)
            
            # Get remaining assigned accountants
            remaining_accountants = client.assigned_accountants.all()
            serializer = self.get_serializer(remaining_accountants, many=True)
            
            response_data = {
                'client_id': client.id,
                'client_name': client.client_name,
                'unassigned_accountant_ids': accountant_ids,
                'remaining_accountants': serializer.data,
                'total_remaining_accountants': remaining_accountants.count()
            }
            
            return create_api_response(
                status.HTTP_200_OK,
                f"Successfully unassigned {len(accountant_ids)} accountant(s) from client.",
                data=response_data
            )
            
        except Exception as e:
            logger.error(f"Unexpected error during accountant unassignment: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred during accountant unassignment.",
                data={"error": str(e)}
            )

    def post(self, request, *args, **kwargs):
        """Alternative method for unassigning (using POST for compatibility)"""
        return self.delete(request, *args, **kwargs)
