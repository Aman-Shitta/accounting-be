
from aicounting.response import create_api_response
from rest_framework.generics import GenericAPIView
from .accountant_serializers import AzureInviteAccountantSerializer
from .client_serializers import DimAICAccountantSerializer
from rest_framework import status
from aicounting.msal_conf import MsalGraphConf

from user.services import create_user_for_accountant
from .constants import AccountantInviteViewMessages, AccountantListViewMessages

from authentication.permissions import IsCustomer
from authentication.authenticate import JSONWebTokenAuthentication


import logging
logger = logging.getLogger(__name__)


class AzureAccountantInviteView(GenericAPIView):
    """
    Invite an accountant to Azure AD B2C and create a local accountant record in non-verified state.
    """

    serializer_class = AzureInviteAccountantSerializer
    authentication_classes = [JSONWebTokenAuthentication]
    permission_classes = [IsCustomer]
    
    msal_graph = MsalGraphConf()

    def post(self, request):
        data = request.data

        user_email = data.get("email")
        user_name = data.get("user_name")
        first_name = data.get("first_name")
        last_name = data.get("last_name")
        user_type = 'accountant'

        # Get the requesting user (authenticated superuser)
        request_user = request.user
        customer = request_user.customer_profile

        # Validate the serializer
        serializer = self.serializer_class(data=data, context={'request': request})
        if not serializer.is_valid():
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=AccountantInviteViewMessages["validation_error"],
                errors=serializer.errors
            )
        
        # Check if accountant already exists
        accountant, error_message = create_user_for_accountant(
            user_email=user_email,
            user_name=user_name,
            first_name=first_name,
            last_name=last_name,
            request_user=request_user,
            customer=customer,
        )

        if error_message:
            # Determine if it's an "already exists" error
            if "already exists" in error_message.lower():
                message = AccountantInviteViewMessages["already_exists"]
            else:
                message = error_message
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=message
            )

        # Send Azure AD B2C invite
        invite_result = self.msal_graph.send_azure_invite_with_group(
            email=user_email, 
            first_name=first_name, 
            last_name=last_name, 
            user_type=user_type
        )

        if not invite_result.get("success"):
            logger.error("[DEBUG] Azure invite failed:", invite_result.get("error"))
            # If Azure invite fails, we should clean up the created accountant
            accountant.system_user.delete()
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=AccountantInviteViewMessages["azure_error"]
            )

        return create_api_response(
            status_code=status.HTTP_201_CREATED,
            message=AccountantInviteViewMessages["success"],
            data={
                "accountant": DimAICAccountantSerializer(accountant).data,
                "customer_id": customer.id,
                "customer_name": customer.customer_name,
                "email": user_email,
                "verification_status": "pending",
                "azure_invite": invite_result
            }
        )

class AccountantListView(GenericAPIView):
    """
    List all accountants associated with the authenticated customer.
    """
    serializer_class = DimAICAccountantSerializer
    authentication_classes = [JSONWebTokenAuthentication]
    permission_classes = [IsCustomer]

    def get_queryset(self):
        request_user = self.request.user
        customer = request_user.customer_profile
        return customer.accountants.all()

    def get(self, request):
        accountants = self.get_queryset()
        serializer = self.serializer_class(accountants, many=True)
        return create_api_response(
            status_code=status.HTTP_200_OK,
            message=AccountantListViewMessages["success"],
            data=serializer.data
        )