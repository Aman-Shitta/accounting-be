from django.shortcuts import get_object_or_404
from rest_framework import generics, status, permissions
from rest_framework.views import APIView

from .models import (
    DimAICJETemplateHeader, 
    DimAICJETemplateAttribute, 
    DimAicInputFileAttributes,
    DimAICJEFreq
)
from .je_template_serializers import (
    JETemplateListSerializer,
    JETemplateDetailSerializer,
    JETemplateCreateSerializer,
    JETemplateUpdateSerializer,
    AvailableAttributeSerializer,
    JETemplateAttributeSerializer,
    JETemplateAttributeCreateSerializer,
    JEFreqListSerializer,
)
from user.models import DimAICClient
from authentication import authenticate
from authentication.permissions import IsCustomerOrAccountant
from aicounting.response import create_api_response

import logging
logger = logging.getLogger(__name__)

class JEFreqListView(generics.GenericAPIView):
    """List all available JE Frequencies"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = JEFreqListSerializer

    def get(self, request):
        """Get all available JE frequencies"""
        try:
            # Get all JE frequencies
            frequencies = DimAICJEFreq.objects.all().order_by('je_freq')
            
            # Serialize the data
            serializer = self.serializer_class(frequencies, many=True)
            
            return create_api_response(
                status.HTTP_200_OK,
                "JE frequencies retrieved successfully",
                data=serializer.data
            )
            
        except Exception as e:
            logger.error(f"Error retrieving JE frequencies: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving JE frequencies.",
                data={"error": str(e)}
            )


class JETemplateListView(generics.GenericAPIView):
    """List all JE Templates for a specific client"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = JETemplateListSerializer

    def get_queryset(self, client_id):
        """Get JE Templates for a client with proper authorization checks"""
        user = self.request.user
        
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return DimAICJETemplateHeader.objects.filter(
                client=client_id,
                customer=customer
            ).order_by('-created_at')
        
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return DimAICJETemplateHeader.objects.filter(
                client=client_id,
                customer=accountant.customer,
                client__assigned_accountants=accountant
            ).order_by('-id')
        
        return DimAICJETemplateHeader.objects.none()

    def get(self, request, client_id, *args, **kwargs):
        """Get all JE Templates for a specific client"""
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
                f"JE Templates retrieved successfully for client {client.client_name}.",
                data={
                    'client': client.id,
                    'client_name': client.client_name,
                    'total_templates': queryset.count(),
                    'je_templates': serializer.data
                }
            )
        
        except Exception as e:
            logger.error(f"Error retrieving JE Templates for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving JE Templates.",
                data={"error": str(e)}
            )


class JETemplateCreateView(generics.GenericAPIView):
    """Create a new JE Template for a specific client"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = JETemplateCreateSerializer

    def post(self, request, client_id, *args, **kwargs):
        """Create a new JE Template"""
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
                je_template = serializer.save()
                
                # Return detailed view of created template
                detail_serializer = JETemplateDetailSerializer(
                    je_template, 
                    context={'request': request}
                )
                
                return create_api_response(
                    status.HTTP_201_CREATED,
                    "JE Template created successfully.",
                    data=detail_serializer.data
                )
            
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "JE Template creation failed due to validation errors.",
                data=serializer.errors
            )
        
        except Exception as e:
            logger.error(f"Error creating JE Template for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while creating the JE Template.",
                data={"error": str(e)}
            )


class JETemplateDetailView(generics.GenericAPIView):
    """Retrieve, update, or delete a specific JE Template"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]

    def get_object(self, client_id, template_id):
        """Get JE Template with proper authorization checks"""
        user = self.request.user
        
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return get_object_or_404(
                DimAICJETemplateHeader,
                id=template_id,
                client=client_id,
                customer=customer
            )
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return get_object_or_404(
                DimAICJETemplateHeader,
                id=template_id,
                client=client_id,
                customer=accountant.customer,
                client__assigned_accountants=accountant
            )
        else:
            return None

    def get(self, request, client_id, template_id, *args, **kwargs):
        """Retrieve a specific JE Template"""
        try:
            je_template = self.get_object(client_id, template_id)
            if not je_template:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "JE Template not found or access denied."
                )
            
            serializer = JETemplateDetailSerializer(
                je_template, 
                context={'request': request}
            )
            
            return create_api_response(
                status.HTTP_200_OK,
                "JE Template retrieved successfully.",
                data=serializer.data
            )
        
        except Exception as e:
            logger.error(f"Error retrieving JE Template {template_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving the JE Template.",
                data={"error": str(e)}
            )

    def put(self, request, client_id, template_id, *args, **kwargs):
        """Update a specific JE Template"""
        try:
            je_template = self.get_object(client_id, template_id)
            if not je_template:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "JE Template not found or access denied."
                )
            
            serializer = JETemplateUpdateSerializer(
                je_template,
                data=request.data,
                context={'request': request},
                partial=True
            )
            
            if serializer.is_valid():
                updated_template = serializer.save()
                
                # Return detailed view of updated template
                detail_serializer = JETemplateDetailSerializer(
                    updated_template,
                    context={'request': request}
                )
                
                return create_api_response(
                    status.HTTP_200_OK,
                    "JE Template updated successfully.",
                    data=detail_serializer.data
                )
            
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "JE Template update failed due to validation errors.",
                data=serializer.errors
            )
        
        except Exception as e:
            logger.error(f"Error updating JE Template {template_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while updating the JE Template.",
                data={"error": str(e)}
            )

    def delete(self, request, client_id, template_id, *args, **kwargs):
        """Delete a specific JE Template"""
        try:
            je_template = self.get_object(client_id, template_id)
            if not je_template:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "JE Template not found or access denied."
                )
            
            template_name = je_template.je_name
            je_template.delete()
            
            return create_api_response(
                status.HTTP_200_OK,
                f"JE Template '{template_name}' deleted successfully."
            )
        
        except Exception as e:
            logger.error(f"Error deleting JE Template {template_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while deleting the JE Template.",
                data={"error": str(e)}
            )


class AvailableAttributesView(generics.GenericAPIView):
    """List available input file attributes for JE Template configuration"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = AvailableAttributeSerializer

    def get(self, request, client_id, *args, **kwargs):
        """Get all available attributes (excluding bank_statement and credit_card)"""
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
            
            # Get available attributes excluding bank_statement and credit_card
            available_attributes = DimAicInputFileAttributes.objects.filter(
                input_file__client=client
            ).exclude(
                input_file__file_type__in=['bank_statement', 'credit_card']
            ).select_related(
                'input_file', 'gl_account', 'offset_gl_account'
            ).order_by('input_file__name', 'name')
            
            serializer = self.get_serializer(available_attributes, many=True)
            
            return create_api_response(
                status.HTTP_200_OK,
                f"Available attributes retrieved successfully for client {client.client_name}.",
                data={
                    'client': client.id,
                    'client_name': client.client_name,
                    'total_attributes': available_attributes.count(),
                    'available_attributes': serializer.data
                }
            )
        
        except Exception as e:
            logger.error(f"Error retrieving available attributes for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving available attributes.",
                data={"error": str(e)}
            )


class JETemplateAttributeConfigView(generics.GenericAPIView):
    """Configure attributes for a JE Template"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]

    def get_template(self, client_id, template_id):
        """Get JE Template with proper authorization checks"""
        user = self.request.user
        
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return get_object_or_404(
                DimAICJETemplateHeader,
                id=template_id,
                client=client_id,
                customer=customer
            )
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return get_object_or_404(
                DimAICJETemplateHeader,
                id=template_id,
                client=client_id,
                customer=accountant.customer,
                client__assigned_accountants=accountant
            )
        else:
            return None

    def get(self, request, client_id, template_id, *args, **kwargs):
        """Get configured attributes for a JE Template"""
        try:
            je_template = self.get_template(client_id, template_id)
            if not je_template:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "JE Template not found or access denied."
                )
            
            configured_attributes = je_template.template_attributes.all().select_related(
                'input_file_attribute',
                # 'gl_acct_id',
                # 'offset_gl_acct_id'
            )
            
            serializer = JETemplateAttributeSerializer(configured_attributes, many=True)
            
            return create_api_response(
                status.HTTP_200_OK,
                f"Configured attributes retrieved successfully for template {je_template.je_name}.",
                data={
                    'template_id': je_template.id,
                    'template_name': je_template.je_name,
                    'total_attributes': configured_attributes.count(),
                    'configured_attributes': serializer.data
                }
            )
        
        except Exception as e:
            logger.error(f"Error retrieving configured attributes for template {template_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving configured attributes.",
                data={"error": str(e)}
            )

    def post(self, request, client_id, template_id, *args, **kwargs):
        """
        Add attributes to a JE Template (bulk create)
        
        Expected payload format:
        {
            "input_file_attribute_ids": [1, 2, 3, 4]
        }
        
        The input_file_attribute_ids should be a list of valid attribute IDs 
        that belong to the client and are not from bank_statement or credit_card files.
        """
        try:
            je_template = self.get_template(client_id, template_id)
            if not je_template:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "JE Template not found or access denied."
                )
            
            serializer = JETemplateAttributeCreateSerializer(
                data=request.data,
                context={
                    'request': request, 
                    'template_id': template_id,
                    'client_id': client_id
                }
            )
            
            if serializer.is_valid():
                created_attributes = serializer.save()
                
                response_serializer = JETemplateAttributeSerializer(created_attributes, many=True)
                
                return create_api_response(
                    status.HTTP_201_CREATED,
                    f"Successfully added {len(created_attributes)} attribute(s) to template {je_template.je_name}.",
                    data=response_serializer.data
                )
            
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Attribute configuration failed due to validation errors.",
                data=serializer.errors
            )
        
        except Exception as e:
            logger.error(f"Error configuring attributes for template {template_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while configuring attributes.",
                data={"error": str(e)}
            )


class JETemplateAttributeDetailView(generics.GenericAPIView):
    """Remove specific attribute from JE Template"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]

    def get_object(self, client_id, template_id, attr_id):
        """Get template attribute with proper authorization checks"""
        user = self.request.user
        
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return get_object_or_404(
                DimAICJETemplateAttribute,
                id=attr_id,
                je_template_id=template_id,
                je_template_id__client=client_id,
                je_template_id__customer=customer
            )
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return get_object_or_404(
                DimAICJETemplateAttribute,
                id=attr_id,
                je_template_id=template_id,
                je_template_id__client=client_id,
                je_template_id__customer=accountant.customer,
                je_template_id__client__assigned_accountants=accountant
            )
        else:
            return None

    def delete(self, request, client_id, template_id, attr_id, *args, **kwargs):
        """Remove an attribute from JE Template"""
        try:
            template_attribute = self.get_object(client_id, template_id, attr_id)
            if not template_attribute:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Template attribute not found or access denied."
                )
            
            attribute_name = template_attribute.input_file_attribute.name
            template_name = template_attribute.je_template_id.je_name
            template_attribute.delete()
            
            return create_api_response(
                status.HTTP_200_OK,
                f"Attribute '{attribute_name}' removed from template '{template_name}' successfully."
            )
        
        except Exception as e:
            logger.error(f"Error removing attribute {attr_id} from template {template_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while removing the attribute.",
                data={"error": str(e)}
            )
