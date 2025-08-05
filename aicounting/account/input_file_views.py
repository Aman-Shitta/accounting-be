from django.shortcuts import get_object_or_404
from rest_framework import generics, status, permissions
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from account.models import DimAicInputFiles, DimAicInputFileAttributes

from account.input_file_serializers import (
    InputFileListSerializer,
    InputFileBasicCreateSerializer,
    InputFileBasicUpdateSerializer,
    InputFileDetailSerializer,
    AttributeCreateSerializer,
    InputFileAttributeSerializer,
)
from user.models import DimAICClient
from authentication import authenticate
from authentication.permissions import IsCustomerOrAccountant
from aicounting.response import create_api_response

import logging
logger = logging.getLogger(__name__)


class InputFileListView(generics.GenericAPIView):
    """
    List all input files for a specific client.
    
    Authorization rules:
    - Customer can view input files for their own clients
    - Accountant can view input files for clients they are assigned to
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = InputFileListSerializer

    def get_queryset(self, client_id):
        """Get input files for a client with proper authorization checks"""
        user = self.request.user
        
        # Check if user is a customer
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            # Customer can view input files for their own clients
            return DimAicInputFiles.objects.filter(
                client_id=client_id,
                client__customer=customer
            ).order_by('-created_at')
        
        # Check if user is an accountant
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            # Accountant can view input files for clients they are assigned to
            return DimAicInputFiles.objects.filter(
                client_id=client_id,
                client__customer=accountant.customer,
                client__assigned_accountants=accountant
            ).order_by('-created_at')
        
        # User is neither customer nor accountant
        return DimAicInputFiles.objects.none()

    def get(self, request, client_id, *args, **kwargs):
        """Get all input files for a specific client"""
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
            serializer = self.get_serializer(queryset, many=True)
            
            return create_api_response(
                status.HTTP_200_OK,
                f"Input files retrieved successfully for client {client.client_name}.",
                data={
                    'client_id': client.id,
                    'client_name': client.client_name,
                    'total_files': queryset.count(),
                    'input_files': serializer.data
                }
            )
        
        except Exception as e:
            logger.error(f"Error retrieving input files for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving input files.",
                data={"error": str(e)}
            )


class InputFileCreateView(generics.GenericAPIView):
    """Create a new input file without attributes for a specific client"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = InputFileBasicCreateSerializer
    parser_classes = [MultiPartParser, FormParser]
    
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request, client_id, *args, **kwargs):
        """Create a new input file without attributes"""
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
            
            serializer = self.get_serializer(
                data=request.data, 
                context={'request': request, 'client_id': client_id}
            )
            
            if serializer.is_valid():
                input_file = serializer.save()
                
                # Return detailed view of created input file
                detail_serializer = InputFileDetailSerializer(
                    input_file, 
                    context={'request': request}
                )
                
                return create_api_response(
                    status.HTTP_201_CREATED,
                    "Input file created successfully.",
                    data=detail_serializer.data
                )
            
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Input file creation failed due to validation errors.",
                data=serializer.errors
            )
        
        except Exception as e:
            logger.error(f"Error creating input file for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while creating the input file.",
                data={"error": str(e)}
            )


class InputFileDetailView(generics.GenericAPIView):
    """Retrieve, update, or delete a specific input file"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    parser_classes = [MultiPartParser, FormParser]
    
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_object(self, client_id, file_id):
        """Get input file with proper authorization checks"""
        user = self.request.user
        
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return get_object_or_404(
                DimAicInputFiles,
                id=file_id,
                client_id=client_id,
                client__customer=customer
            )
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return get_object_or_404(
                DimAicInputFiles,
                id=file_id,
                client_id=client_id,
                client__customer=accountant.customer,
                client__assigned_accountants=accountant
            )
        else:
            return None

    def get(self, request, client_id, file_id, *args, **kwargs):
        """Retrieve a specific input file with attributes"""
        try:
            input_file = self.get_object(client_id, file_id)
            if not input_file:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Input file not found or access denied."
                )
            
            serializer = InputFileDetailSerializer(
                input_file, 
                context={'request': request}
            )
            
            return create_api_response(
                status.HTTP_200_OK,
                "Input file retrieved successfully.",
                data=serializer.data
            )
        
        except Exception as e:
            logger.error(f"Error retrieving input file {file_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving the input file.",
                data={"error": str(e)}
            )

    def put(self, request, client_id, file_id, *args, **kwargs):
        """Update a specific input file basic information only"""
        try:
            input_file = self.get_object(client_id, file_id)
            if not input_file:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Input file not found or access denied."
                )
            
            serializer = InputFileBasicUpdateSerializer(
                input_file,
                data=request.data,
                context={'request': request},
                partial=True
            )
            
            if serializer.is_valid():
                updated_file = serializer.save()
                
                # Return detailed view of updated input file
                detail_serializer = InputFileDetailSerializer(
                    updated_file,
                    context={'request': request}
                )
                
                return create_api_response(
                    status.HTTP_200_OK,
                    "Input file updated successfully.",
                    data=detail_serializer.data
                )
            
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Input file update failed due to validation errors.",
                data=serializer.errors
            )
        
        except Exception as e:
            logger.error(f"Error updating input file {file_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while updating the input file.",
                data={"error": str(e)}
            )

    def delete(self, request, client_id, file_id, *args, **kwargs):
        """Delete a specific input file"""
        try:
            input_file = self.get_object(client_id, file_id)
            if not input_file:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Input file not found or access denied."
                )
            
            file_name = input_file.file_name
            input_file.delete()
            
            return create_api_response(
                status.HTTP_200_OK,
                f"Input file '{file_name}' deleted successfully."
            )
        
        except Exception as e:
            logger.error(f"Error deleting input file {file_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while deleting the input file.",
                data={"error": str(e)}
            )


class AttributeCreateView(generics.GenericAPIView):
    """Create a new attribute for a specific input file"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = AttributeCreateSerializer
    
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_input_file(self, client_id, file_id):
        """Get input file with proper authorization checks"""
        user = self.request.user
        
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return get_object_or_404(
                DimAicInputFiles,
                id=file_id,
                client_id=client_id,
                client__customer=customer
            )
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return get_object_or_404(
                DimAicInputFiles,
                id=file_id,
                client_id=client_id,
                client__customer=accountant.customer,
                client__assigned_accountants=accountant
            )
        else:
            return None

    def post(self, request, client_id, file_id, *args, **kwargs):
        """Create a new attribute for an input file"""
        try:
            input_file = self.get_input_file(client_id, file_id)
            if not input_file:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Input file not found or access denied."
                )
            
            # Check if file type allows custom attributes
            if input_file.file_type in ['bank_statement', 'credit_card']:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Cannot add custom attributes to {input_file.file_type} files. "
                    "These files use auto-generated attributes."
                )
            
            serializer = self.get_serializer(data=request.data, many=True)
            
            if serializer.is_valid():
                attribute = serializer.save(
                    input_file=input_file,
                    input_user=request.user
                )
                
                response_serializer = InputFileAttributeSerializer(attribute, many=True)
                
                return create_api_response(
                    status.HTTP_201_CREATED,
                    "Attribute created successfully.",
                    data=response_serializer.data
                )
            
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Attribute creation failed due to validation errors.",
                data=serializer.errors
            )
        
        except Exception as e:
            logger.error(f"Error creating attribute for input file {file_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while creating the attribute.",
                data={"error": str(e)}
            )


class AttributeListView(generics.GenericAPIView):
    """
    List all attributes for a specific input file.
    
    Authorization rules:
    - Customer can view attributes for their own clients' input files
    - Accountant can view attributes for clients they are assigned to
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = InputFileAttributeSerializer

    def get_input_file(self, client_id, file_id):
        """Get input file with proper authorization checks"""
        user = self.request.user
        
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return get_object_or_404(
                DimAicInputFiles,
                id=file_id,
                client_id=client_id,
                client__customer=customer
            )
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return get_object_or_404(
                DimAicInputFiles,
                id=file_id,
                client_id=client_id,
                client__customer=accountant.customer,
                client__assigned_accountants=accountant
            )
        else:
            return None

    def get(self, request, client_id, file_id, *args, **kwargs):
        """Get all attributes for a specific input file"""
        try:
            input_file = self.get_input_file(client_id, file_id)
            if not input_file:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Input file not found or access denied."
                )
            
            attributes = input_file.attributes.all().order_by('created_at')
            serializer = self.get_serializer(attributes, many=True)
            
            return create_api_response(
                status.HTTP_200_OK,
                f"Attributes retrieved successfully for input file {input_file.name}.",
                data={
                    'input_file_id': input_file.id,
                    'input_file_name': input_file.name,
                    'total_attributes': attributes.count(),
                    'attributes': serializer.data
                }
            )
        
        except Exception as e:
            logger.error(f"Error retrieving attributes for input file {file_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving attributes.",
                data={"error": str(e)}
            )


class AttributeBulkDeleteView(generics.GenericAPIView):
    """Delete multiple attributes for a specific input file"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_input_file(self, client_id, file_id):
        """Get input file with proper authorization checks"""
        user = self.request.user
        
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return get_object_or_404(
                DimAicInputFiles,
                id=file_id,
                client_id=client_id,
                client__customer=customer
            )
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return get_object_or_404(
                DimAicInputFiles,
                id=file_id,
                client_id=client_id,
                client__customer=accountant.customer,
                client__assigned_accountants=accountant
            )
        else:
            return None

    def delete(self, request, client_id, file_id, *args, **kwargs):
        """Delete multiple attributes by their IDs"""
        try:
            input_file = self.get_input_file(client_id, file_id)
            if not input_file:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Input file not found or access denied."
                )
            
            attribute_ids = request.data.get('attribute_ids', [])
            
            if not attribute_ids:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "No attribute IDs provided for deletion."
                )
            
            # Check for auto-generated attributes that can't be deleted
            protected_attrs = DimAicInputFileAttributes.objects.filter(
                id__in=attribute_ids,
                input_file=input_file,
                name="*"
            )
            
            if protected_attrs.exists() and input_file.file_type in ['bank_statement', 'credit_card']:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Cannot delete auto-generated attributes for bank statement/credit card files."
                )
            
            # Get attributes that exist and belong to this input file
            attributes_to_delete = DimAicInputFileAttributes.objects.filter(
                id__in=attribute_ids,
                input_file=input_file
            )
            
            deleted_count = attributes_to_delete.count()
            deleted_ids = list(attributes_to_delete.values_list('id', flat=True))
            
            if deleted_count == 0:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "No valid attributes found for deletion."
                )
            
            # Delete the attributes
            attributes_to_delete.delete()
            
            return create_api_response(
                status.HTTP_200_OK,
                f"Successfully deleted {deleted_count} attribute(s).",
                data={
                    'deleted_count': deleted_count,
                    'deleted_ids': deleted_ids
                }
            )
        
        except Exception as e:
            logger.error(f"Error deleting attributes for input file {file_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while deleting attributes.",
                data={"error": str(e)}
            )

