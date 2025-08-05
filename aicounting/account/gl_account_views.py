
from django.conf import settings
from django.db import transaction

from rest_framework import generics,  status
from rest_framework.filters import SearchFilter

from account.models import DimAICGLAcct
from account.serializers import (
    DimAICGLAcctSerializer,
)

from authentication import authenticate
from authentication.permissions import IsAuthenticated, IsCustomerOrAccountant
from aicounting.response import create_api_response


import logging
logger = logging.getLogger(__name__)

# Create your views here.


class ClientGLAccountListView(generics.GenericAPIView):
    """
    View to list all accounts for a specific client.
    
    Authorization rules:
    - Customer can view accounts for their own clients
    - Accountant can view accounts for clients they are assigned to (same customer)
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = DimAICGLAcctSerializer

    filter_backends = [SearchFilter]
    search_fields = ['account_number', 'account_name', 'description']

    def get_queryset(self, client_id):
        """
        Get accounts for a client with proper authorization checks
        """
        user = self.request.user
        
        # Check if user is a customer
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            # Customer can view accounts for their own clients
            return DimAICGLAcct.objects.filter(
                client_id=client_id,
                customer=customer
            )
        
        # Check if user is an accountant
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            # Accountant can view accounts for clients they are assigned to
            # and that belong to the same customer
            return DimAICGLAcct.objects.filter(
                client_id=client_id,
                customer=accountant.customer,
                client_id__assigned_accountants=accountant
            )
        
        # User is neither customer nor accountant
        return DimAICGLAcct.objects.none()

    def get(self, request, *args, **kwargs):
        """
        Get all accounts for a specific client
        """
        try:

            client_id = kwargs.get('client_id')
            # Get filtered queryset based on user permissions
            queryset = self.get_queryset(client_id)

            queryset = self.filter_queryset(queryset)
            
            if not queryset.exists():
                # Client doesn't exist or user doesn't have permission
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Client doesn't exist or user doesn't have permission."
                )

            # Serialize the data
            serializer = self.get_serializer(queryset, many=True)
                    
            return create_api_response(
                status.HTTP_200_OK,
                "Accounts retrieved successfully.",
                data=serializer.data
            )
            
        except Exception as e:
            logger.error(f"Unexpected error retrieving accounts: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected error occurred while retrieving accounts.",
                data={"error": str(e)}
            )
