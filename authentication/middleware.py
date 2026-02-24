
from django.utils.deprecation import MiddlewareMixin

from authentication.authenticate import JSONWebTokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


# Paths that should skip JWT authentication in middleware
EXCLUDED_PATHS = [
    '/api/auth/login/',
    '/api/auth/callback/',
    '/admin/',
    '/health/',
    '/static/',
]


class JWTAuthenticationMiddleware(MiddlewareMixin):
    """
    Authenticates the user via JWT once and caches the result on the request.
    DRF's JSONWebTokenAuthentication will check for this cache first,
    avoiding a duplicate (expensive) token verification.
    """

    def process_request(self, request):
        # Skip authentication for public/excluded routes
        if any(request.path.startswith(p) for p in EXCLUDED_PATHS):
            return

        # Skip if no Authorization header present
        if not request.META.get('HTTP_AUTHORIZATION'):
            return

        tauth = JSONWebTokenAuthentication()
        try:
            user, token = tauth.authenticate(request)
            request.user = user
            # Cache the result so DRF doesn't re-verify the same token
            request._jwt_auth_cache = (user, token)
        except (TypeError, AuthenticationFailed):
            request._jwt_auth_cache = None