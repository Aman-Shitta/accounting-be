
from django.utils.deprecation import MiddlewareMixin

from authentication.authenticate import JSONWebTokenAuthentication
from rest_framework.exceptions import AuthenticationFailed



class JWTAuthenticationMiddleware(MiddlewareMixin):
    """
    Authenticates the user via JWT once and caches the result on the request.
    DRF's JSONWebTokenAuthentication will check for this cache first,
    avoiding a duplicate (expensive) token verification.
    """

    def process_request(self, request):
        tauth = JSONWebTokenAuthentication()
        try:
            user, token = tauth.authenticate(request)
            request.user = user
            # Cache the result so DRF doesn't re-verify the same token
            request._jwt_auth_cache = (user, token)
        except (TypeError, AuthenticationFailed):
            request._jwt_auth_cache = None