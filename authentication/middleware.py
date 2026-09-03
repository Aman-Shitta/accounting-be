from django.contrib.auth.models import AnonymousUser
from django.utils.deprecation import MiddlewareMixin
from rest_framework.exceptions import AuthenticationFailed

from authentication.authenticate import JSONWebTokenAuthentication


# Paths that never carry a bearer token.
EXCLUDED_PATHS = [
    "/api/v1/auth/login/",
    "/api/v1/auth/callback/",
    "/health/",
]


class JWTAuthenticationMiddleware(MiddlewareMixin):
    """
    Authenticates the bearer token once and caches the result on the request,
    so DRF's JSONWebTokenAuthentication does not re-verify the same token.

    Also guarantees ``request.user`` exists on every request. The project runs
    without ``django.contrib.auth``'s AuthenticationMiddleware (there is no
    cookie session), and auditlog reads ``request.user`` unconditionally.
    """

    def process_request(self, request):
        request.user = AnonymousUser()

        if any(request.path.startswith(p) for p in EXCLUDED_PATHS):
            return

        if not request.META.get("HTTP_AUTHORIZATION"):
            return

        try:
            user, token = JSONWebTokenAuthentication().authenticate(request)
            request.user = user
            request._jwt_auth_cache = (user, token)
        except (TypeError, AuthenticationFailed):
            # Leave request.user anonymous; DRF returns 401 at the view.
            request._jwt_auth_cache = None
