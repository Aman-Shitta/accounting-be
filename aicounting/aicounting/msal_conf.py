# System imports
import os

# Third-party imports
import jwt
import msal
import requests
from asgiref.sync import async_to_sync


from msgraph.generated.models.invitation import Invitation
from msgraph.generated.models.invited_user_message_info import InvitedUserMessageInfo

class MsalConf:

    TENANT_ID = os.environ.get('AZURE_TENANT_ID')
    CLIENT_ID = os.environ.get('AZURE_CLIENT_ID')
    CLIENT_SECRET = os.environ.get('AZURE_CLIENT_SECRET')

    AUTHORITY= f"https://login.microsoftonline.com/{TENANT_ID}"
    APP_URI= f"https://OnestoneB2C.onmicrosoft.com/{CLIENT_ID}"
    
    JWKS_URI= f"{AUTHORITY}/discovery/v2.0/keys"

    SCOPE = ["User.Read"]
    
    MSAL_APP = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )

    REDIRECT_URI = "https://firm-worm-evolved.ngrok-free.app/api/v1/auth/callback"

    def debug_jwt_token(self, jwt_token):
        """
        Debug method to inspect JWT token without validation.
        Useful for troubleshooting authentication issues.
        """
        try:
            # Get unverified header and payload
            header = jwt.get_unverified_header(jwt_token)
            payload = jwt.decode(jwt_token, options={"verify_signature": False})
            
            return {
                "header": header,
                "payload": payload,
                "kid": header.get('kid'),
                "alg": header.get('alg'),
                "aud": payload.get('aud'),
                "iss": payload.get('iss'),
                "exp": payload.get('exp'),
                "email": payload.get('preferred_username') or payload.get('email')
            }
        except Exception as e:
            return {"error": str(e)}
    
    def clear_cached_keys(self):
        """
        Clear all cached JWKS keys. Useful for troubleshooting or forced refresh.
        """
        from django.core.cache import cache
        # Clear all keys that start with our cache prefix
        cache.delete_many([key for key in cache._cache.keys() if key.startswith('azure_jwk_data_')])
        
    def get_public_key(self, jwt_token):
        public_key = ""
        # Get Azure AD public keys for token signature verification
        jwks_url = self.JWKS_URI
        jwks_response = requests.get(jwks_url)
        jwks = jwks_response.json()
        # Find the appropriate key from the JWKS based on the token's "kid" (Key ID) claim
        header = jwt.get_unverified_header(jwt_token)
        kid = header['kid']

        # Find the key with a matching "kid" in the JWKS
        for key in jwks['keys']:
            if key['kid'] == kid:
                # Use the found key for verification
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break
        else:
            # Handle the case where a matching key was not found
            raise ValueError("Matching key not found in JWKS")
        
        return public_key, self.APP_URI
    
    def refresh_access_token(self, refresh_token):
        """
        This method is used to refresh an access token using a refresh token
        """

        try:
            # Acquire a new token using the refresh token
            response = self.MSAL_APP.acquire_token_by_refresh_token(
                refresh_token=refresh_token,
                scopes=[f"{self.APP_URI}/user_impersonation"]
            )

            # Check if the response contains a new access token
            if "access_token" in response:
                access_token = response["access_token"]
                return access_token
            else:
                return None

        except Exception as e:
            # Handle exceptions and errors
            print(f"An error occurred while refreshing access token: {str(e)}")
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
        invitation.invite_redirect_url = redirect_url or "https://myapps.microsoft.com"
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
        groups_name = {
            'customer': 'e1c94e8c-0f95-4594-8961-8ca9a0d44dc6',
            'accountant':'dbee5e23-aaed-4208-a261-37386dea6821'
        }
        return groups_name.get(user_type, None)
    
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
        
        async_to_sync(graph_client.groups.by_group_id(group_id).members.ref.post)(reference)

    def send_azure_invite_with_group(self, email, first_name, last_name, user_type, redirect_url=None, group_id=None):
        try:
            # Use https://myapps.microsoft.com as default redirect URL to avoid localhost issues
            if not redirect_url:
                redirect_url = "https://myapps.microsoft.com"
            
            invitation = self.create_invitation(email, first_name, last_name, redirect_url)
            response = self.send_invitation(invitation)
            user_id = response.invited_user.id
            
            # Try to assign group, but don't fail the entire operation if it fails
            group_assignment_result = {"success": False, "error": None}
            
            try:
                if not group_id:
                    group_id = self.get_user_type_group(user_type)
                    if not group_id:
                        raise Exception(f"No group mapping found for user_type: {user_type}")
                
                self.add_user_to_group(user_id, group_id)
                group_assignment_result = {"success": True, "group_id": group_id}
                
            except Exception as group_error:
                print(f"Group assignment failed: {str(group_error)}")
                group_assignment_result = {"success": False, "error": str(group_error)}
            
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
            print(f"Error sending Azure invitation: {str(e)}")
            import os, sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)
            
            return {
                "success": False,
                "error": str(e)
            }
    
    def send_simple_azure_invite(self, email, first_name, last_name, user_type="Guest", redirect_url=None):
        """
        Send a simple Azure AD invitation without group assignment.
        Use this to test if basic invitation permissions work.
        """
        try:
            invitation = self.create_invitation(email, first_name, last_name, user_type, redirect_url)
            response = self.send_invitation(invitation)
            
            return {
                "success": True,
                "invitation_id": response.id,
                "invited_user_id": response.invited_user.id,
                "invite_redeem_url": response.invite_redeem_url
            }
        except Exception as e:
            import os, sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)
            print(f"Error sending Azure invitation: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def send_azure_invite_only(self, email, first_name, last_name, user_type, redirect_url=None):
        """
        Send invitation without group assignment to test basic invitation functionality.
        """
        try:
            # Use https://myapps.microsoft.com as default redirect URL
            if not redirect_url:
                redirect_url = "https://myapps.microsoft.com"
            
            invitation = self.create_invitation(email, first_name, last_name, redirect_url)
            response = self.send_invitation(invitation)
            
            return {
                "success": True,
                "invitation_id": response.id,
                "invited_user_id": response.invited_user.id,
                "invite_redeem_url": response.invite_redeem_url,
                "user_type": user_type,
                "message": "Invitation sent successfully (without group assignment)"
            }
        except Exception as e:
            print(f"Error sending Azure invitation: {str(e)}")
            import os, sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)
            
            return {
                "success": False,
                "error": str(e)
            }
