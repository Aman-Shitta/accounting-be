from aicounting.response import create_api_response

from rest_framework.generics import GenericAPIView

from user.invite_serializers import AzureInviteCustomerSerializer
# Create your views here.
from rest_framework import status

from aicounting.msal_conf import  MsalGraphConf

from rest_framework import permissions

class AzureInviteView(GenericAPIView):
    """
    Invite an external user to Azure AD B2C and create a local user record.
    """

    serializer_class = AzureInviteCustomerSerializer
    # permission_classes = [permissions.IsAdminUser]  
    
    msal_grpah = MsalGraphConf()

    def post(self, request):
        data = request.data
        email = data.get("email")
        user_type = 'customer'

        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        request.user = UserModel.objects.get(username='admin')

        serializer = self.serializer_class(data=data, context={'request': request})

        if not serializer.is_valid():

            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid data",
                errors=serializer.errors
            )

        username_part = email.split('@')[0]
        if '.' in username_part:
            first_name, last_name = username_part.split('.', 1)
        else:
            first_name = username_part
            last_name = ''

        # Send Azure AD B2C invite
        invite_sent = self.msal_grpah.send_azure_invite_with_group(email, first_name, last_name, user_type)

        if not invite_sent:
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to send Azure invite.",
            )
        # Create local user record
        serializer.save(context={'request': request})    

        return create_api_response(
            status_code=status.HTTP_201_CREATED,
            message="Invite sent and user created.",
            data=invite_sent
        )