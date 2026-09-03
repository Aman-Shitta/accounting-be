import logging
import os
import sys

import jwt
from jwt import PyJWKClient
import msal
import requests
from asgiref.sync import async_to_sync
from msgraph.generated.models.invitation import Invitation
from msgraph.generated.models.invited_user_message_info import InvitedUserMessageInfo

from authentication.constants import ACCOUNTANT, CUSTOMER, REVIEWER

logger = logging.getLogger(__name__)


class MsalConf:

    TENANT_ID = os.environ.get('AZURE_TENANT_ID')
    CLIENT_ID = os.environ.get('AZURE_CLIENT_ID')
    CLIENT_SECRET = os.environ.get('AZURE_CLIENT_SECRET')
    AUTH_REDIRECT_URI = os.environ.get('AUTH_REDIRECT_URI')

    APP_REDIRECT_URI = os.environ.get('APP_REDIRECT_URI')

    AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
    APP_URI = f""

    JWKS_URI = f"{AUTHORITY}/discovery/v2.0/keys"

    SCOPE = ["User.Read"]

    MSAL_APP = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )

    GROUPS = {
        CUSTOMER: os.environ.get('CUSTOMER_GROUP_ID'),
        ACCOUNTANT: os.environ.get('ACCOUNTANT_GROUP_ID'),
        REVIEWER: os.environ.get('REVIEWER_GROUP_ID')
    }

    # Cached JWKS client — keys are fetched once and cached for 1 hour
    _jwk_client = None

    @classmethod
    def get_jwk_client(cls):
        """Get or create a cached PyJWKClient instance."""
        if cls._jwk_client is None:
            cls._jwk_client = PyJWKClient(
                cls.JWKS_URI,
                cache_jwk_set=True,
                lifespan=3600  # cache for 1 hour
            )
        return cls._jwk_client

    def get_public_key(self, jwt_token):
        """
        Get the public key for JWT verification using cached JWKS keys.
        Keys are cached for 1 hour via PyJWKClient to avoid HTTP calls per request.
        """
        signing_key = self.get_jwk_client().get_signing_key_from_jwt(jwt_token)
        return signing_key.key

    def refresh_access_token(self, refresh_token):
        """
        Refresh an access token using a refresh token.

        Args:
            refresh_token: The stored refresh token from the database

        Returns:
            dict with new tokens or None if refresh failed
            {
                'id_token': str,
                'refresh_token': str,  # New refresh token (tokens rotate)
                'expires_in': int
            }
        """
        if not refresh_token:
            logger.warning("No refresh token provided")
            return None

        try:
            # MSAL doesn't have a direct refresh_token method in ConfidentialClientApplication
            # We need to use the OAuth2 token endpoint directly
            token_url = f"{self.AUTHORITY}/oauth2/v2.0/token"

            data = {
                'client_id': self.CLIENT_ID,
                'client_secret': self.CLIENT_SECRET,
                'refresh_token': refresh_token,
                'grant_type': 'refresh_token',
                'scope': ' '.join(self.SCOPE) + ' offline_access openid profile'
            }

            response = requests.post(token_url, data=data)

            if response.status_code == 200:
                result = response.json()
                logger.info("Successfully refreshed access token")
                return {
                    'id_token': result.get('id_token'),
                    'access_token': result.get('access_token'),
                    # New rotated refresh token
                    'refresh_token': result.get('refresh_token'),
                    'expires_in': result.get('expires_in')
                }
            else:
                logger.error(
                    f"Token refresh failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error refreshing token: {str(e)}")
            return None


class MsalGraphConf(MsalConf):
    """
    Handles Azure AD B2C invitations using Microsoft Graph SDK.
    Inherits MSAL config from MsalConf.
    Modular approach for invitation, group fetch, and assignment.
    """

    def get_graph_client(self):
        from azure.identity import ClientSecretCredential
        from msgraph import GraphServiceClient

        credential = ClientSecretCredential(
            tenant_id=self.TENANT_ID,
            client_id=self.CLIENT_ID,
            client_secret=self.CLIENT_SECRET
        )

        scopes = ['https://graph.microsoft.com/.default']
        return GraphServiceClient(credentials=credential, scopes=scopes)

    def create_invitation(self, email, first_name, last_name, redirect_url=None, message_body=None):
        invitation = Invitation()
        invitation.invited_user_email_address = email
        invitation.invited_user_display_name = f"{first_name} {last_name}"
        invitation.invited_user_type = "Guest"
        # Use https://myapps.microsoft.com as default - Microsoft Graph doesn't accept localhost
        invitation.invite_redirect_url = redirect_url or self.APP_REDIRECT_URI
        invitation.send_invitation_message = True
        invited_user_message_info = InvitedUserMessageInfo()
        invited_user_message_info.message_language = "en-US"
        invited_user_message_info.customized_message_body = message_body or f"Hello {first_name}, you have been invited to join our organization."
        invitation.invited_user_message_info = invited_user_message_info
        return invitation

    def send_invitation(self, invitation):
        graph_client = self.get_graph_client()
        response = async_to_sync(graph_client.invitations.post)(invitation)
        return response

    def get_user_type_group(self, user_type):
        """
        Maps user type to a specific group ID.
        This is a placeholder for actual mapping logic.
        """
        return self.GROUPS.get(user_type, None)

    def get_group(self, user_type):
        graph_client = self.get_graph_client()
        groups = async_to_sync(graph_client.groups.get)()
        azure_groups = groups.value if hasattr(groups, 'value') else []

        return azure_groups

    def add_user_to_group(self, user_id, group_id):
        from msgraph.generated.models.reference_create import ReferenceCreate

        graph_client = self.get_graph_client()

        # Create a proper reference object instead of a dictionary
        reference = ReferenceCreate()
        reference.odata_id = f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"

        async_to_sync(graph_client.groups.by_group_id(
            group_id).members.ref.post)(reference)

    def send_azure_invite_with_group(self, email, first_name, last_name, user_type, redirect_url=None, group_id=None, message_body=None):
        try:
            # Use https://myapps.microsoft.com as default redirect URL to avoid localhost issues
            if not redirect_url:
                redirect_url = self.APP_REDIRECT_URI or "https://myapps.microsoft.com"

            invitation = self.create_invitation(
                email, first_name, last_name, redirect_url, message_body)
            response = self.send_invitation(invitation)
            user_id = response.invited_user.id

            # Try to assign group, but don't fail the entire operation if it fails
            group_assignment_result = {"success": False, "error": None}

            try:
                if not group_id:
                    group_id = self.get_user_type_group(user_type)
                    if not group_id:
                        raise Exception(
                            f"No group mapping found for user_type: {user_type}")

                self.add_user_to_group(user_id, group_id)
                group_assignment_result = {
                    "success": True, "group_id": group_id}

            except Exception as group_error:
                logger.error(f"Group assignment failed: {str(group_error)}")
                group_assignment_result = {
                    "success": False, "error": str(group_error)}

            return {
                "success": True,
                "invitation_id": response.id,
                "invited_user_id": user_id,
                "invite_redeem_url": response.invite_redeem_url,
                "assigned_group_id": group_id if group_assignment_result["success"] else None,
                "group_assignment": group_assignment_result,
                "message": "Invitation sent successfully" + (" with group assignment" if group_assignment_result["success"] else " but group assignment failed")
            }
        except Exception as e:
            logger.error(f"Error sending Azure invitation: {str(e)}")

            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(f"{exc_type} in {fname}:{exc_tb.tb_lineno}")

            return {
                "success": False,
                "error": str(e)
            }
