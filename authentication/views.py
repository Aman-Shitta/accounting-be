from django.contrib.auth import get_user_model

import jwt
from rest_framework import permissions, status
from rest_framework.generics import GenericAPIView

from aicounting.msal_conf import MsalConf
from aicounting.response import create_api_response
from authentication import authenticate
from authentication.constants import *
from authentication.permissions import IsCustomerOrAccountant
from user.models import (
    DimAICAccountant,
    DimAICCustomer,
    DimAICReviewer,
)

from msal import Prompt

msal = MsalConf()


class SSOLoginView(GenericAPIView):
    def get(self, request):
        auth_url = msal.MSAL_APP.get_authorization_request_url(
            msal.SCOPE,
            prompt=Prompt.SELECT_ACCOUNT,
            redirect_uri=msal.AUTH_REDIRECT_URI
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
                    redirect_uri=msal.AUTH_REDIRECT_URI
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

            # Check for customer or accountant groups in priority order
            # Customer has higher priority than accountant
            user_role = None
            for role in USER_GROUPS:
                if msal.GROUPS.get(role) in groups:
                    user_role = role
                    break

            if not user_role:
                return create_api_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    data=None,
                    message='Unauthorized group access. User must be a customer or accountant.'
                )

            user_name = ""
            customer_name = ""

            if user_role == CUSTOMER:
                customer = DimAICCustomer.objects.filter(
                    system_user__email=email).first()

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

                customer.system_user.is_active = True
                customer.system_user.save()

                user_name = customer.customer_name
                customer_name = user_name

            elif user_role == ACCOUNTANT:

                accountant = DimAICAccountant.objects.filter(
                    system_user__email=email).first()
                if not accountant or not user_object_id:
                    return create_api_response(
                        status_code=status.HTTP_403_FORBIDDEN,
                        data=None,
                        message='Unauthorized Accountant. Please contact admin.'
                    )
                if not accountant.verified:
                    accountant.azure_id = user_object_id
                    accountant.verified = True

                accountant.refresher_token = refresh_token
                accountant.save()

                accountant.system_user.is_active = True
                accountant.system_user.save()

                user_name = accountant.username
                customer_name = accountant.customer.customer_name

            elif user_role == REVIEWER:

                reviewer = DimAICReviewer.objects.filter(
                    system_user__email=email).first()
                if not reviewer or not user_object_id:
                    return create_api_response(
                        status_code=status.HTTP_403_FORBIDDEN,
                        data=None,
                        message='Unauthorized Reviewer. Please contact admin.'
                    )
                if not reviewer.verified:
                    reviewer.azure_id = user_object_id
                    reviewer.verified = True

                reviewer.refresher_token = refresh_token
                reviewer.save()

                reviewer.system_user.is_active = True
                reviewer.system_user.save()

                user_name = reviewer.email
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
                "user_info": {
                    "user_type": user_role,
                    "email": email,
                    "name": user_name,
                    "customer_name": f"{customer_name}"
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


class SSORefreshTokenView(GenericAPIView):
    """
    Refresh the user's token using the stored refresh token.
    Frontend should call this endpoint before the token expires or when receiving a 401.
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]

    def post(self, request):
        try:
            # Get the current (possibly expired) token from Authorization header
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if not auth_header.startswith('Bearer '):
                return create_api_response(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    data=None,
                    message='No authorization token provided.'
                )

            current_token = auth_header.split(' ')[1]

            # Decode without verification to get user info (token might be expired)
            try:
                decoded = jwt.decode(current_token, options={
                                     "verify_signature": False})
                azure_id = decoded.get('oid')
                email = decoded.get(
                    'preferred_username') or decoded.get('email')
            except jwt.DecodeError:
                return create_api_response(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    data=None,
                    message='Invalid token format.'
                )

            if not azure_id:
                return create_api_response(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    data=None,
                    message='Could not identify user from token.'
                )

            # Find the user and their stored refresh token
            customer = DimAICCustomer.objects.filter(azure_id=azure_id).first()
            accountant = DimAICAccountant.objects.filter(
                azure_id=azure_id).first()

            user_profile = customer or accountant
            user_type = 'customer' if customer else 'accountant'

            if not user_profile:
                return create_api_response(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    data=None,
                    message='User not found.'
                )

            stored_refresh_token = user_profile.refresher_token

            if not stored_refresh_token:
                return create_api_response(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    data=None,
                    message='No refresh token available. Please login again.'
                )

            # Refresh the token
            new_tokens = msal.refresh_access_token(stored_refresh_token)

            if not new_tokens or not new_tokens.get('id_token'):
                return create_api_response(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    data=None,
                    message='Token refresh failed. Please login again.'
                )

            # Update the stored refresh token (Azure AD rotates refresh tokens)
            user_profile.refresher_token = new_tokens.get('refresh_token')
            user_profile.save()

            # Get user info for response
            if user_type == 'customer':
                user_name = user_profile.customer_name
                customer_name = user_name
            else:
                user_name = user_profile.username
                customer_name = user_profile.customer.customer_name

            return create_api_response(
                status_code=status.HTTP_200_OK,
                message="Token refreshed successfully.",
                data={
                    "access_token": new_tokens.get('id_token'),
                    "expires_in": new_tokens.get('expires_in'),
                    "user_info": {
                        "user_type": user_type,
                        "email": email,
                        "name": user_name,
                        "customer_name": customer_name
                    }
                }
            )

        except Exception as e:
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data=None,
                message=f'Token refresh error: {str(e)}'
            )


class WhoamiView(GenericAPIView):
    """
    Endpoint to return the current authenticated user's information.
    Useful for frontend to check who is logged in and their role.
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):

        user = request.user

        if hasattr(user, 'customer_profile'):
            profile = user.customer_profile
            user_type = 'customer'
            user_name = profile.customer_name
            customer_name = user_name
        elif hasattr(user, 'accountant_profile'):
            profile = user.accountant_profile
            user_type = 'accountant'
            user_name = profile.username
            customer_name = profile.customer.customer_name
        elif hasattr(user, 'reviewer_profile'):
            profile = user.reviewer_profile
            user_type = 'reviewer'
            user_name = profile.email
            customer_name = None
        else:
            return create_api_response(
                status_code=status.HTTP_404_NOT_FOUND,
                data=None,
                message='User profile not found.'
            )

        return create_api_response(
            status_code=status.HTTP_200_OK,
            message='Data retrieved successfully.',
            data={
                "user_type": user_type,
                "email": user.email,
                "name": user_name,
                "customer_name": customer_name
            }
        )
