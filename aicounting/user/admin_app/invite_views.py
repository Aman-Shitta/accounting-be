from aicounting.response import create_api_response
from rest_framework.generics import GenericAPIView
from .invite_serializers import AzureInviteCustomerSerializer
from rest_framework import status
from aicounting.msal_conf import MsalGraphConf

from user.services import create_user_for_customer

from .permissions import IsSuperUser
from .jwt_auth import AdminJWTAuthentication

class AzureInviteView(GenericAPIView):
    """
    Invite a customer to Azure AD B2C and create a local customer record in non-verified state.
    """

    serializer_class = AzureInviteCustomerSerializer
    permission_classes = [IsSuperUser]
    authentication_classes = [AdminJWTAuthentication]
    
    msal_graph = MsalGraphConf()

    def post(self, request):
        data = request.data
        email = data.get("email")
        # customer_name = data.get("customer_name", "")
        street = data.get("street", "")
        city = data.get("city", "")
        state_abrevation = data.get("state_abrevation", "")
        zip_code = data.get("zip_code", None)
        user_type = 'customer'

        # Get the requesting user (authenticated superuser)
        request_user = request.user

        # Validate the serializer
        serializer = self.serializer_class(data=data, context={'request': request})
        if not serializer.is_valid():
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid data",
                errors=serializer.errors
            )

        # Generate customer name from email domain if not provided
        # domain is ths customer name
        if not customer_name:
            customer_name = email.split('@')[1].replace('.', ' ').title()
        
        # Check if customer already exists
        customer, error_message = create_user_for_customer(
            request_user=request_user,
            customer_name=customer_name,
            email=email,
            street=street,
            city=city,
            state_abrevation=state_abrevation,
            zip_code=zip_code
        )

        if error_message:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=error_message
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
            user_type=user_type
        )

        if not invite_result.get("success"):
            print("[DEBUG] Azure invite failed:", invite_result.get("error"))
            # If Azure invite fails, we should clean up the created customer
            customer.system_user.delete()
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to send Azure invite.",
            )

        return create_api_response(
            status_code=status.HTTP_201_CREATED,
            message="Customer invite sent successfully. Customer created in non-verified state.",
            data={
                "customer_id": customer.customer_id,
                "customer_name": customer.customer_name,
                "email": email,
                "verification_status": "pending",
                "azure_invite": invite_result
            }
        )