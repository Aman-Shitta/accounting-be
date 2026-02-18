import logging
from datetime import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.encoding import force_str
from django.utils.translation import gettext as _
from auditlog.context import set_actor

import jwt
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from user.models import DimAICAccountant, DimAICCustomer, DimAICReviewer
User = get_user_model()


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

    def _try_refresh_token(self, azure_id, email):
        """
        Attempt to refresh the token using stored refresh token.
        Returns new id_token or None if refresh failed.
        """
        try:
            from aicounting.msal_conf import MsalConf
            from user.models import DimAICCustomer, DimAICAccountant

            msal_conf = MsalConf()

            # Find user's refresh token
            customer = DimAICCustomer.objects.filter(azure_id=azure_id).first()
            accountant = DimAICAccountant.objects.filter(
                azure_id=azure_id).first()

            user_profile = customer or accountant
            if not user_profile or not user_profile.refresher_token:
                return None

            # Attempt refresh
            new_tokens = msal_conf.refresh_access_token(
                user_profile.refresher_token)

            if new_tokens and new_tokens.get('id_token'):
                # Update stored refresh token (rotation)
                user_profile.refresher_token = new_tokens.get('refresh_token')
                user_profile.save()
                return new_tokens.get('id_token')

            return None
        except Exception as e:
            logger.error(f"Auto-refresh failed: {e}")
            return None

    def authenticate(self, request):
        """
        Authenticate the user based on the provided JSON Web Token (JWT).
        """
        # If the middleware already verified this token, reuse the result
        cached = getattr(request, '_jwt_auth_cache', None)
        if cached is not None:
            return cached

        jwt_token = self.get_jwt_token(request)
        if jwt_token is None:
            return None

        try:
            from aicounting.msal_conf import MsalConf
            msal_conf = MsalConf()

            # Debug: Check token type and contents
            logger.debug("Inspecting JWT token")
            try:
                unverified_header = jwt.get_unverified_header(jwt_token)
                unverified_payload = jwt.decode(
                    jwt_token, options={"verify_signature": False})

                logger.debug(
                    f"Token type (typ): {unverified_header.get('typ')}")
                logger.debug(
                    f"Token algorithm: {unverified_header.get('alg')}")
                logger.debug(f"Token issuer: {unverified_payload.get('iss')}")
                logger.debug(
                    f"Token audience: {unverified_payload.get('aud')}")
                logger.debug(f"Token version: {unverified_payload.get('ver')}")

                # Check if this is an ID token
                if unverified_payload.get('ver') == '2.0':
                    logger.debug("Detected Azure AD v2.0 ID token")

            except Exception as debug_error:
                logger.warning(f"Could not inspect token: {debug_error}")
            # Get the public key and audience for verification
            logger.debug("Fetching public key for JWT verification")
            public_key = msal_conf.get_public_key(jwt_token)

            # print(f"Public key: {public_key}")
            # print(f"Expected audience: {audience}"
            audience = [msal_conf.CLIENT_ID]
            logger.debug(f"Expected audience: {audience}")

            # Try to decode with proper audience validation
            try:
                decoded_token = jwt.decode(
                    jwt_token,
                    public_key,
                    algorithms=['RS256'],
                    audience=audience,
                    issuer=f"https://login.microsoftonline.com/{msal_conf.TENANT_ID}/v2.0"
                )
                logger.debug("JWT successfully decoded with full validation")
            except jwt.InvalidAudienceError as aud_error:
                logger.warning(f"Audience validation failed: {aud_error}")
                logger.warning(
                    "Retrying without audience validation for debugging")
                # Retry without audience validation for debugging
                decoded_token = jwt.decode(
                    jwt_token,
                    public_key,
                    algorithms=['RS256'],
                    options={"verify_aud": False},
                    issuer=f"https://login.microsoftonline.com/{msal_conf.TENANT_ID}/v2.0"
                )
                logger.debug("JWT decoded without audience validation")
            except jwt.InvalidIssuerError as iss_error:
                logger.warning(f"Issuer validation failed: {iss_error}")
                # Retry without issuer validation
                decoded_token = jwt.decode(
                    jwt_token,
                    public_key,
                    algorithms=['RS256'],
                    options={"verify_aud": False, "verify_iss": False}
                )
                logger.debug("JWT decoded without issuer/audience validation")

            logger.debug(
                f"Token successfully decoded. Claims: {list(decoded_token.keys())}")

            # Check if the token has expired (JWT library already checks this, but let's be explicit)
            current_time = datetime.now()
            expiration_time = datetime.fromtimestamp(decoded_token["exp"])

            if current_time > expiration_time:
                logger.warning("Token has expired")
                raise CustomAuthenticationFailed('error', _(
                    "Expired token. Please re-authenticate."))

            # Get user email from ID token claims
            # ID tokens typically have these email fields
            email = (decoded_token.get('preferred_username') or
                     decoded_token.get('email') or
                     decoded_token.get('upn'))

            if not email:
                logger.error("No email found in token claims")
                logger.info(f"Available claims: {list(decoded_token.keys())}")
                raise CustomAuthenticationFailed(
                    'error', _('No email in token claims.'))

            logger.debug(f"Processing authentication for email: {email}")

            azure_id = decoded_token.get("oid")
            cust_id = DimAICCustomer.objects.filter(azure_id=azure_id).first()

            if not cust_id:
                logger.warning(f"Unauthorized customer")
                accountant_id = DimAICAccountant.objects.filter(
                    azure_id=azure_id)
                if not accountant_id:
                    logger.warning(f"Unauthorized accountant")
                    reviewer_id = DimAICReviewer.objects.filter(
                        azure_id=azure_id)
                    if not reviewer_id:
                        logger.warning(f"Unauthorized reviewer")
                        raise CustomAuthenticationFailed('error', _(
                            'Unauthorized User. Please contact admin.'))

            UserModel = get_user_model()
            django_user, created = UserModel.objects.get_or_create(
                email=email,
                defaults={"username": email.split("@")[0]}
            )

            logger.debug(f"Authentication successful for user: {email}")
            set_actor(django_user)  # Set the actor for audit logging

            # msal_conf.refresh_access_token(django_user.customer_profile.refresher_token)
            return (django_user, jwt_token)

        except jwt.InvalidSignatureError as e:
            logger.error(f"JWT signature verification failed: {e}")
            raise CustomAuthenticationFailed('error', _(
                'Invalid token signature. Please re-authenticate.'))
        except jwt.ExpiredSignatureError as e:
            logger.warning(f"JWT token expired, attempting refresh")
            # Try to get azure_id from expired token
            try:
                expired_payload = jwt.decode(
                    jwt_token, options={"verify_signature": False})
                azure_id = expired_payload.get('oid')
                email = expired_payload.get('preferred_username')

                # Attempt automatic refresh
                new_token = self._try_refresh_token(azure_id, email)
                if new_token:
                    # Return a special response indicating token was refreshed
                    # The frontend should update its stored token
                    raise CustomAuthenticationFailed(
                        'token_refreshed',
                        _('Token was refreshed. Please retry with new token.')
                    )
            except Exception:
                pass

            raise CustomAuthenticationFailed('error', _(
                'Token has expired. Please re-authenticate.'))
        except jwt.InvalidAudienceError as e:
            logger.error(f"JWT audience validation failed: {e}")
            raise CustomAuthenticationFailed('error', _(
                'Token audience validation failed. Please re-authenticate.'))
        except jwt.DecodeError as e:
            logger.error(f"JWT decode error: {e}")
            raise CustomAuthenticationFailed(
                'error', _('Invalid or expired token.'))
        except ValueError as e:
            logger.error(f"JWT validation error: {e}")
            raise CustomAuthenticationFailed('error', _(
                'Token validation failed. Please re-authenticate.'))
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise CustomAuthenticationFailed(
                'error', _('Authentication failed.'))

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
            raise exceptions.AuthenticationFailed(
                detail={'status': 'error', 'message': msg})
        elif len(auth) > 2:
            msg = _(
                "Invalid Authorization header. Credentials string should not contain spaces.")
            raise exceptions.AuthenticationFailed(
                detail={'status': 'error', 'message': msg})

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


class AdminJWTAuthentication(BaseAuthentication):
    """
    Custom JWT authentication backend.
    """

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION')

        if not auth_header or not auth_header.startswith('Bearer '):
            return None

        token = auth_header.split(' ')[1]

        try:
            # Decode JWT token
            secret_key = getattr(settings, 'SECRET_KEY', 'your-secret-key')
            payload = jwt.decode(token, secret_key, algorithms=['HS256'])

            # Get user from payload
            user_id = payload.get('user_id')
            if not user_id:
                raise exceptions.AuthenticationFailed('Invalid token payload')

            user = User.objects.get(id=user_id)

            # Verify superuser status
            if not user.is_superuser:
                raise exceptions.AuthenticationFailed(
                    'Superuser privileges required')

            return (user, token)

        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed('Token has expired')
        except jwt.InvalidTokenError:
            raise exceptions.AuthenticationFailed('Invalid token')
        except User.DoesNotExist:
            raise exceptions.AuthenticationFailed('User not found')
        except Exception as e:
            raise exceptions.AuthenticationFailed(
                f'Authentication failed: {str(e)}')

    def authenticate_header(self, request):
        return 'Bearer'
