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
            refresh_token = result.get('refresh_token')
            if not id_token:
                return create_api_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    data=None,
                    message='No ID token received from Azure AD.'
                )
            token_claims = result.get('id_token_claims', {})
            email = token_claims.get('preferred_username')
            if not email:
                return create_api_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    data=None,
                    message='Email not found in token claims.'
                )

            user_object_id = token_claims.get('oid')
            groups = token_claims.get('groups', [])

            if not groups:
                return create_api_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    data=None,
                    message='User does not belong to any required groups.'
                )
            
            group = groups[0]  # Assuming the first group is the one we care about
            user_assigned_groups = [k for k, v in msal.GROUPS.items() if v == group]

            if not user_assigned_groups:
                return create_api_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    data=None,
                    message='Unauthorized group access.'
                )
            
            user_name = ""
            if user_assigned_groups[0] == 'customer':
                customer = DimAICCustomer.objects.filter(system_user__username=email).first()

                if not customer or not user_object_id:
                    return create_api_response(
                        status_code=status.HTTP_403_FORBIDDEN,
                        data=None,
                        message='Unauthorized Customer. Please contact admin.'
                    )
                if not customer.verified:
                    customer.azure_id = user_object_id
                    customer.verified = True
                
                customer.refresher_token = refresh_token
                customer.save()

                user_name = customer.customer_name

            elif user_assigned_groups[0] == 'accountant':
                user = DimAICUser.objects.filter(system_user__username=email).first()
                if not user or not user_object_id:
                    return create_api_response(
                        status_code=status.HTTP_403_FORBIDDEN,
                        data=None,
                        message='Unauthorized Accountant. Please contact admin.'
                    )
                if not user.verified:
                    user.azure_id = user_object_id
                    user.verified = True
                
                user.refresher_token = refresh_token
                user.save()

                user_name = f"{user.first_name} {user.last_name}"
            else:
                return create_api_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    data=None,
                    message='Unauthorized user type.'
                )

            get_user_model().objects.get_or_create(
                email=email,
                defaults={"username": email.split("@")[0]}
            )

            # Return the ID token for client-side storage and future API calls
            token_response = {
                "access_token": id_token,
                # "access_token": result.get('access_token'),  # Optional: for accessing other APIs
                # "refresh_token": result.get('refresh_token'),
                "expires_in": result.get('expires_in'),
                # "token_type": "Bearer",
                "user_type": 'customer',
                "user_info": {
                    "email": email,
                    "name": user_name
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