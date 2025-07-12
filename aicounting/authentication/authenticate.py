import logging
import datetime
from datetime import datetime
import jwt
from jwt import DecodeError

from django.utils.encoding import force_str
from django.utils.translation import gettext as _
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

class CustomAuthenticationFailed(exceptions.AuthenticationFailed):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(detail={'status': status, 'message': message})


class JSONWebTokenAuthentication(BaseAuthentication):
    """
    Token based authentication using the JSON Web Token standard (Azure AD SSO).
    """
    def get_authentication_token(self, request):
        """
        Retrieve the authentication token from the request.

        Parameters:
        - request: The HTTP request object.

        Returns:
        - The authentication token extracted from the request.
        """
        token = ""
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split()[1]
        return token

    
    def authenticate(self, request):
        """
        Authenticate the user based on the provided JSON Web Token (JWT).

        Parameters:
        - request: The HTTP request object.

        Returns:
        - A tuple (user, jwt_token) if authentication is successful, or None.
        """

        jwt_token = self.get_jwt_token(request)
        if jwt_token is None:
            return None

        try:
            from aicounting.aicounting.msal_conf import AzureConf
            azure_conf = AzureConf()

            public_key, audience = azure_conf.get_public_key(jwt_token)

            # Azure AD tokens are RS256 signed
            decoded_token = jwt.decode(
                jwt_token,
                public_key,
                algorithms=['RS256'],
                audience=audience
            )

             # Check if the token has expired
            current_time = datetime.now()
            expiration_time = datetime.fromtimestamp(decoded_token["exp"])

            # Refresh the token if it's about to expire
            if current_time > expiration_time:
                raise CustomAuthenticationFailed('error', _("Expired token. Please re-authenticate."))

            # Get or create user based on claims
            
            email = decoded_token.get('preferred_username') or decoded_token.get('email')
            if not email:
                raise CustomAuthenticationFailed('error', _('No email in token claims.'))

            
            from aicounting.user.models import DimAICUser, DimAICCustomer
            
            domain = email.split('@')[1].lower()

            cust_name = domain.split('.')[0].capitalize()

            cust_id = DimAICCustomer.objects.filter(customer_name=cust_name).first()

            if not cust_id:
                raise CustomAuthenticationFailed('error', _('Unauthorized Customer. Please contact admin.'))

            UserModel = get_user_model()
            django_user, _ = UserModel.objects.get_or_create(
                email=email,
                defaults={"username": email.split("@")[0]}
            )    
            user, _ = DimAICUser.objects.get_or_create(user=django_user, username= email.split("@")[0], cust_id=cust_id)
            return (user, jwt_token)

        except DecodeError   as e:
            logger.error(f"JWT decode error: {e}")
            raise CustomAuthenticationFailed('error', _('Invalid or expired token.'))
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise CustomAuthenticationFailed('error', _('Authentication failed.'))

    def get_jwt_token(self, request):
        """
        Get the JWT token from the request's authorization header.

        Parameters:
        - request: The HTTP request object.

        Returns:
        - The JWT token as a string, or None if not found.
        """
        auth = get_authorization_header(request).split()
        if not auth or force_str(auth[0].lower()) != "bearer":
            return None

        if len(auth) == 1:
            msg = _("Invalid Authorization header. No credentials provided.")
            raise exceptions.AuthenticationFailed(detail={'status': 'error', 'message': msg})
        elif len(auth) > 2:
            msg = _("Invalid Authorization header. Credentials string should not contain spaces.")
            raise exceptions.AuthenticationFailed(detail={'status': 'error', 'message': msg})

        return auth[1]

    def authenticate_header(self, request):
        """
        Define the authentication header for responses in case of authentication failures.

        Parameters:
        - request: The HTTP request object.

        Returns:
        - The authentication header as a string.
        """
        return "Bearer: api"
