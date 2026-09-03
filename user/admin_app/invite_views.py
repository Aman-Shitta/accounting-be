from aicounting.response import create_api_response
from rest_framework.generics import GenericAPIView
from .invite_serializers import AzureInviteCustomerSerializer
from rest_framework import status
from aicounting.msal_conf import MsalGraphConf

from user.services import (
    create_user_for_customer,
    create_user_for_reviewer
)

from user.constants import AzureInviteViewMessages

from authentication.permissions import IsSuperUser
from authentication.authenticate import AdminJWTAuthentication
from authentication.constants import CUSTOMER, REVIEWER

import logging
logger = logging.getLogger(__name__)


class AzureInviteView(GenericAPIView):
    """
    Invite a customer to Azure AD B2C and create a local customer record in non-verified state.
    """

    serializer_class = AzureInviteCustomerSerializer
    permission_classes = [IsSuperUser]
    authentication_classes = [AdminJWTAuthentication]

    msal_graph = MsalGraphConf()

    def post(self, request, *args, **kwargs):
        data = request.data
        email = data.get("email")
        customer_name = data.get("customer_name", "")
        street = data.get("street", "")
        city = data.get("city", "")
        state_abrevation = data.get("state_abrevation", "")
        zip_code = data.get("zip_code", None)
        user_type = kwargs.get("user_type", "customer")

        # Get the requesting user (authenticated superuser)
        request_user = request.user

        # Validate the serializer
        serializer = self.serializer_class(
            data=data, context={'request': request})
        if not serializer.is_valid():
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=AzureInviteViewMessages["validation_error"],
                errors=serializer.errors
            )

        if user_type not in [CUSTOMER, REVIEWER]:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Please select a valid user type for the invitation."
            )

        if user_type == CUSTOMER:
            # Check if customer already exists
            added_user, error_message = create_user_for_customer(
                request_user=request_user,
                customer_name=customer_name,
                email=email,
                street=street,
                city=city,
                state_abrevation=state_abrevation,
                zip_code=zip_code
            )
            message_body = """Hi there,
                Welcome to AI powered accounting! You now have full access to our document processing suite, designed to streamline your financial workflows."""

        elif user_type == REVIEWER:
            # For reviewer, we don't need to create a customer record, just check if reviewer already exists
            added_user, error_message = create_user_for_reviewer(
                request_user=request_user,
                user_email=email
            )
            message_body = """Hi There, You have been invited to join our platform as a reviewer. Please click the link below to accept the invitation and set up your account. We look forward to having you on board!"""

        if error_message:
            # Determine if it's an "already exists" error
            if "already exists" in error_message.lower():
                message = AzureInviteViewMessages["already_exists"]
            else:
                message = error_message
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=message
            )

        # Extract first and last name from email
        username_part = email.split('@')[0]
        if '.' in username_part:
            first_name, last_name = username_part.split('.', 1)
        else:
            first_name = username_part
            last_name = ''

        # Send Azure AD B2C invite
        invite_result = self.msal_graph.send_azure_invite_with_group(
            email=email,
            first_name=first_name,
            last_name=last_name,
            user_type=user_type,
            redirect_url=self.msal_graph.APP_REDIRECT_URI,
            message_body=message_body
        )

        if not invite_result.get("success"):
            logger.error("[DEBUG] Azure invite failed:",
                         invite_result.get("error"))
            # If Azure invite fails, we should clean up the created customer
            added_user.system_user.delete()
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=AzureInviteViewMessages["azure_error"]
            )

        return create_api_response(
            status_code=status.HTTP_201_CREATED,
            message=AzureInviteViewMessages["success"],
            data={
                "user_id": added_user.id,
                "email": email,
                "verification_status": "pending",
                "azure_invite": invite_result
            }
        )
