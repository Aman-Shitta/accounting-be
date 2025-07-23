
from django.conf import settings
from django.db import transaction

from rest_framework import generics, permissions, status

from .models import DimAICClient
from .serializers import (
    ClientSerializer, 
    ClientRetrieveSerializer,
    ClientUpdateSerializer,
    ContactSerializer,
    ClientDocumentUploadSerializer,
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
    serializer_class = ClientSerializer
    queryset = DimAICClient.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context

    def post(self, request, *args, **kwargs):
        try:

            # Use atomic transaction for all operations
            with transaction.atomic():
                serializer = self.get_serializer(data=request.data)
                if not serializer.is_valid():
                    logger.error(f"Client creation validation failed: {serializer.errors}")
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Client creation failed due to validation errors.",
                        data=serializer.errors
                    )

                # Create the client and related objects
                client = serializer.save()

                client_assistant = OpenAIAssistant(
                    api_key=settings.OPENAI_API_KEY,
                    client_id=client.client_id,
                    special_rules=serializer.validated_data.get('special_rules', None)
                )
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
    """Update client basic information"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication] 
    permission_classes = [permissions.IsAuthenticated, IsCustomer] 
    serializer_class = ClientUpdateSerializer

    def get_object(self, client_id):
        # For testing - using static user, remove in production
        customer = self.request.user.customer_profile
        if customer:
            try:
                return DimAICClient.objects.get(customer=customer, id=client_id)
            except DimAICClient.DoesNotExist:
                logger.error("Client not found for update.")
                return DimAICClient.objects.none()
        return DimAICClient.objects.none()

    def put(self, request, *args, **kwargs):
        try:
            # Use atomic transaction for update
            with transaction.atomic():
                partial = kwargs.pop('partial', False)
                instance = self.get_object(kwargs.get('id'))
                if not instance:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Client does not exist or you don't have permission."
                    )
                serializer = self.get_serializer(instance, data=request.data, partial=partial)
                
                if not serializer.is_valid():
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Client update failed due to validation errors.",
                        error=serializer.errors
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
