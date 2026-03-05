
from django.conf import settings
from django.db import transaction

from rest_framework import generics, permissions, status

from user.models import DimAICClient
from .client_serializers import (
    ClientCreateUpdateSerializer,
    ClientRetrieveSerializer,
    ContactSerializer,
    ClientDocumentUploadSerializer,
    ClientAccountantAssignmentSerializer,
    DimAICAccountantSerializer,
)

from authentication import authenticate
from authentication.permissions import IsCustomer, IsCustomerOrAccountant
from aicounting.response import create_api_response

from .utils import OpenAIAssistant
from .constants import (
    ClientCreateViewMessages,
    ClientUpdateViewMessages,
    ClientRetrieveViewMessages,
    ClientListViewMessages,
    ClientDocumentUploadMessages,
    ContactCreateViewMessages,
)

import logging
logger = logging.getLogger(__name__)


class ClientCreateView(generics.GenericAPIView):
    """
    Create a new client with associated contacts and documents.
    Supports nested creation of contacts and documents in a single request.
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = ClientCreateUpdateSerializer
    queryset = DimAICClient.objects.all()

    def post(self, request, *args, **kwargs):
        try:
            # Use atomic transaction for all operations
            with transaction.atomic():

                serializer = self.get_serializer(data=request.data, context={
                                                 "request": self.request})
                if not serializer.is_valid():
                    logger.error(
                        f"Client creation validation failed: {serializer.errors}")
                    return create_api_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ClientCreateViewMessages["validation_error"],
                        errors=serializer.errors
                    )
                # Create the client and related objects
                client = serializer.save()

                client_assistant = OpenAIAssistant(
                    customer=client.customer,
                    client_obj=client,
                    api_key=settings.OPENAI_API_KEY,
                    client_id=client.client_id,
                    special_rules=serializer.validated_data.get(
                        'special_rules', None)
                )
                # Provision the client GPT assistant
                client_assistant.provison_client_assistant()

                # Return success response with created client data
                response_serializer = ClientRetrieveSerializer(client)
                logger.error(
                    f"Client created successfully: {client.client_id}")

                return create_api_response(
                    status_code=status.HTTP_201_CREATED,
                    message=ClientCreateViewMessages["success"],
                    data=response_serializer.data
                )
        except Exception as e:
            import os
            import sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)

            logger.error(f"Unexpected error during client creation: {str(e)}")
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ClientCreateViewMessages["server_error"]
            )


class ClientListView(generics.GenericAPIView):
    """List all clients for the authenticated customer or accountant"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = ClientRetrieveSerializer

    def get_queryset(self):
        customer = getattr(self.request.user, 'customer_profile', None)
        accountant = getattr(self.request.user, 'accountant_profile', None)
        if customer:
            return DimAICClient.objects.filter(customer=customer)
        elif accountant:
            # Adjust this to your accountant-client relationship
            return DimAICClient.objects.filter(assigned_accountants=accountant)
        return DimAICClient.objects.none()

    def get(self, request, *args, **kwargs):
        """
        Override get method to handle custom response structure
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        return create_api_response(
            status_code=status.HTTP_200_OK,
            message=ClientListViewMessages["success"],
            data=serializer.data
        )


class ClientRetrieveView(generics.GenericAPIView):
    """Retrieve a specific client by ID"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = ClientRetrieveSerializer

    def get_queryset(self, id):
        customer = getattr(self.request.user, 'customer_profile', None)
        accountant = getattr(self.request.user, 'accountant_profile', None)

        if customer:
            return DimAICClient.objects.filter(customer=customer, id=id)
        elif accountant:
            # Return clients assigned to this accountant
            return DimAICClient.objects.filter(assigned_accountants=accountant, id=id)
        return DimAICClient.objects.none()

    def get(self, request, *args, **kwargs):
        """
        Override get method to handle custom response structure
        """
        assigned_id = kwargs.get('id')
        queryset = self.get_queryset(assigned_id)

        if not queryset.exists():
            return create_api_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ClientRetrieveViewMessages["not_found"],
                data=None
            )

        client = queryset.first()
        serializer = self.get_serializer(client)

        return create_api_response(
            status_code=status.HTTP_200_OK,
            message=ClientRetrieveViewMessages["success"],
            data=serializer.data
        )


class ClientUpdateView(generics.GenericAPIView):
    """Update client information with support for contacts and documents"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = ClientCreateUpdateSerializer

    def get_object(self, client_id):
        customer = getattr(self.request.user, 'customer_profile', None)
        accountant = getattr(self.request.user, 'accountant_profile', None)

        if not customer:
            customer = accountant.customer

        try:
            return DimAICClient.objects.get(customer=customer, id=client_id)
        except DimAICClient.DoesNotExist:
            logger.error("Client not found for update.")
        return None

    def put(self, request, *args, **kwargs):
        try:
            # Use atomic transaction for update
            with transaction.atomic():
                instance = self.get_object(kwargs.get('id'))
                if not instance:
                    return create_api_response(
                        status_code=status.HTTP_404_NOT_FOUND,
                        message=ClientUpdateViewMessages["not_found"]
                    )
                serializer = self.get_serializer(
                    instance, data=request.data, partial=True, context={"request": self.request})

                if not serializer.is_valid():
                    return create_api_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ClientUpdateViewMessages["validation_error"],
                        errors=serializer.errors
                    )

                client = serializer.save()

                client_assistant = OpenAIAssistant(
                    customer=client.customer,
                    client_obj=client,
                    api_key=settings.OPENAI_API_KEY,
                    client_id=client.client_id,
                    special_rules=serializer.validated_data.get(
                        'special_rules', None)
                )
                # Provision the client GPT assistant
                client_assistant.update_assistant_with_new_files()

                response_serializer = ClientRetrieveSerializer(client)

                return create_api_response(
                    status_code=status.HTTP_200_OK,
                    message=ClientUpdateViewMessages["success"],
                    data=response_serializer.data
                )

        except Exception as e:
            logger.error(f"Unexpected error during client update: {str(e)}")
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ClientUpdateViewMessages["server_error"]
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
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message="Your account setup is incomplete. Please contact your administrator."
                    )

                try:
                    client = DimAICClient.objects.get(
                        id=client_id,
                        customer=customer
                    )
                except DimAICClient.DoesNotExist:
                    return create_api_response(
                        status_code=status.HTTP_404_NOT_FOUND,
                        message=ClientRetrieveViewMessages["not_found"]
                    )

                if client.contacts:
                    logger.error(f"Client {client_id} already has contacts.")
                    return create_api_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message="This client already has contacts. Please update the existing contacts instead.",
                        errors={"contacts": [
                            "This client already has contacts. Please update existing contacts instead."]}
                    )
                serializer = self.get_serializer(data=request.data)
                if not serializer.is_valid():
                    return create_api_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ContactCreateViewMessages["validation_error"],
                        errors=serializer.errors
                    )

                # Create the contact
                serializer.save(client=client)

                return create_api_response(
                    status_code=status.HTTP_201_CREATED,
                    message=ContactCreateViewMessages["success"],
                    data=serializer.data
                )

        except Exception as e:
            logger.error(f"Unexpected error during contact creation: {str(e)}")
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ContactCreateViewMessages["error"]
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
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message="Your account setup is incomplete. Please contact your administrator."
                    )

                try:
                    client = DimAICClient.objects.get(
                        id=client_id,
                        customer=customer
                    )
                except DimAICClient.DoesNotExist:
                    return create_api_response(
                        status_code=status.HTTP_404_NOT_FOUND,
                        message=ClientRetrieveViewMessages["not_found"]
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
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ClientDocumentUploadMessages["validation_error"],
                        errors=serializer.errors
                    )

                # Create and process the documents
                result = serializer.save()

                client_assistant = OpenAIAssistant(
                    customer=customer,
                    client_obj=client,
                    api_key=settings.OPENAI_API_KEY,
                    client_id=client.client_id,
                    special_rules=serializer.validated_data.get(
                        'special_rules', None)
                )
                # Provision the client GPT assistant
                document_ids = [doc.id for doc in result['documents']]
                client_assistant.update_assistant_with_new_files(
                    new_document_ids=document_ids)

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
                    message = ClientDocumentUploadMessages["success"]
                else:
                    message = "Documents uploaded successfully, but some may require additional processing."

                return create_api_response(
                    status_code=status.HTTP_201_CREATED,
                    message=message,
                    data=response_data
                )

        except Exception as e:
            logger.error(
                f"Unexpected error during multiple document upload: {str(e)}")
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ClientDocumentUploadMessages["error"]
            )


class ClientAssignAccountantsView(generics.GenericAPIView):
    """Append accountants to a client (without replacing existing ones)"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = ClientAccountantAssignmentSerializer

    def get_object(self, client_id):
        """Get client instance for the authenticated customer or accountant"""
        customer = getattr(self.request.user, 'customer_profile', None)
        accountant = getattr(self.request.user, 'accountant_profile', None)

        if customer:
            try:
                return DimAICClient.objects.get(customer=customer, id=client_id)
            except DimAICClient.DoesNotExist:
                return None
        elif accountant:
            try:
                # Return client assigned to this accountant
                return DimAICClient.objects.get(assigned_accountants=accountant, id=client_id)
            except DimAICClient.DoesNotExist:
                return None
        return None

    def post(self, request, *args, **kwargs):
        """Append accountants to a client"""
        try:
            client_id = kwargs.get('id')
            client = self.get_object(client_id)

            if not client:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Client not found or you don't have permission to modify it."
                )

            customer = client.customer
            serializer = self.get_serializer(
                client,
                data=request.data,
                context={'customer': customer}
            )

            if not serializer.is_valid():
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Failed to append accountants due to validation errors.",
                    errors=serializer.errors
                )

            updated_client = serializer.save()

            # Return updated client with all assigned accountants
            response_data = {
                'client_id': updated_client.id,
                'client_name': updated_client.client_name,
                'assigned_accountants': DimAICAccountantSerializer(
                    updated_client.assigned_accountants.all(),
                    many=True
                ).data,
                'total_assigned_accountants': updated_client.assigned_accountants.count()
            }

            return create_api_response(
                status.HTTP_200_OK,
                "Accountants appended successfully.",
                data=response_data
            )

        except Exception as e:
            logger.error(
                f"Unexpected error during accountant append: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred while appending accountants."
            )


class ClientAssignedAccountantsView(generics.GenericAPIView):
    """Retrieve all accountants assigned to a specific client"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = DimAICAccountantSerializer

    def get_object(self, client_id):
        """Get client instance for the authenticated customer or accountant"""
        customer = getattr(self.request.user, 'customer_profile', None)
        accountant = getattr(self.request.user, 'accountant_profile', None)

        if customer:
            try:
                return DimAICClient.objects.get(customer=customer, id=client_id)
            except DimAICClient.DoesNotExist:
                return None
        elif accountant:
            try:
                # Return client assigned to this accountant
                return DimAICClient.objects.get(assigned_accountants=accountant, id=client_id)
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
            logger.error(
                f"Unexpected error retrieving assigned accountants: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred while retrieving assigned accountants."
            )


class ClientUnassignAccountantsView(generics.GenericAPIView):
    """Unassign specific accountants from a client"""
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = DimAICAccountantSerializer

    def get_object(self, client_id):
        """Get client instance for the authenticated customer or accountant"""
        customer = getattr(self.request.user, 'customer_profile', None)
        accountant = getattr(self.request.user, 'accountant_profile', None)

        if customer:
            try:
                return DimAICClient.objects.get(customer=customer, id=client_id)
            except DimAICClient.DoesNotExist:
                return None
        elif accountant:
            try:
                # Return client assigned to this accountant
                return DimAICClient.objects.get(assigned_accountants=accountant, id=client_id)
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
            currently_assigned = client.assigned_accountants.filter(
                id__in=accountant_ids)

            if currently_assigned.count() != len(accountant_ids):
                assigned_ids = set(
                    currently_assigned.values_list('id', flat=True))
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
            logger.error(
                f"Unexpected error during accountant unassignment: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred during accountant unassignment."
            )

    def post(self, request, *args, **kwargs):
        """Alternative method for unassigning (using POST for compatibility)"""
        return self.delete(request, *args, **kwargs)
