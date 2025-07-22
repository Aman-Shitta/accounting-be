# Third-party imports

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.generics import GenericAPIView

# Local imports
from aicounting.msal_conf import MsalConf
from aicounting.response import create_api_response
from user.models import DimAICCustomer, DimAICUser

msal = MsalConf()

class SSOLoginView(GenericAPIView):
    def get(self, request):        
        auth_url = msal.MSAL_APP.get_authorization_request_url(
            msal.SCOPE,
            redirect_uri=msal.REDIRECT_URI
        )
        
        return create_api_response(
            status_code=status.HTTP_200_OK,
            message="Authorization URL generated successfully.",
            data={"auth_url": auth_url}
        )

class SSOGenerateTokenView(GenericAPIView):
    def get(self, request):
        try:
            code = request.GET.get('code')
            if not code:
                return create_api_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    data=None,
                    message='No code provided in callback.'
                )

            try:
                result = msal.MSAL_APP.acquire_token_by_authorization_code(
                    code,
                    scopes=msal.SCOPE,
                    redirect_uri=msal.REDIRECT_URI
                )
            except Exception as e:
                return create_api_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    data=None,
                    message=f'Failed to acquire token: {str(e)}'
                )

            # Get ID token instead of access token for user authentication
            id_token = result.get('id_token')
            if not id_token:
                return create_api_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    data=None,
                    message='No ID token received from Azure AD.'
                )

            email = result.get('id_token_claims', {}).get('preferred_username')
            if not email:
                return create_api_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    data=None,
                    message='Email not found in token claims.'
                )

            domain = email.split('@')[1].lower()
            cust_name = domain.split('.')[0].capitalize()
            print(f"Customer Name: {cust_name}")    

            customer = DimAICCustomer.objects.filter(customer_name=cust_name).first()
            if not customer:
                return create_api_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    data=None,
                    message='Unauthorized Customer. Please contact admin.'
                )

            UserModel = get_user_model()
            system_user, _ = UserModel.objects.get_or_create(
                email=email,
                defaults={"username": email.split("@")[0]}
            )
            name = email.split("@")[0]
            DimAICUser.objects.get_or_create(
                system_user=system_user,
                defaults={
                    "cust_id": customer,
                    "username": email.split("@")[0],
                    "first_name": f"{name[0]}",
                    "last_name": f"{name}",
                    "email": email,
                }
            )

            # Return the ID token for client-side storage and future API calls
            token_response = {
                "access_token": id_token,  # This is what the client should use in Authorization header
                # "access_token": result.get('access_token'),  # Optional: for accessing other APIs
                # "refresh_token": result.get('refresh_token'),
                "expires_in": result.get('expires_in'),
                # "token_type": "Bearer",
                "user_info": {
                    "email": email,
                    "customer": cust_name
                }
            }
            
            return create_api_response(
                status_code=status.HTTP_200_OK,
                message="Authentication successful.",
                data=token_response,
            )
        except Exception as e:
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data=None,
                message=f'Internal server error: {str(e)}'
            )