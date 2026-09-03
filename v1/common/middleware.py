"""Request-level user resolution for a session-less, bearer-token API."""

import logging

from django.contrib.auth.models import AnonymousUser
from django.utils.deprecation import MiddlewareMixin
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

logger = logging.getLogger(__name__)


class JWTUserMiddleware(MiddlewareMixin):
    """
    Resolve the bearer token onto ``request.user`` before the view runs.

    Two reasons this exists rather than ``django.contrib.auth``'s
    AuthenticationMiddleware:

    * That one hard-requires SessionMiddleware, and this API has no cookie
      session.
    * auditlog reads ``request.user`` in its own middleware, which runs before
      DRF authenticates inside the view. Without this, every audit entry would
      record an anonymous actor.

    An unusable token leaves the user anonymous; DRF returns the 401.
    """

    def process_request(self, request):
        request.user = AnonymousUser()

        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer "):
            return

        raw_token = header.partition(" ")[2].strip()
        if not raw_token:
            return

        try:
            authenticator = JWTAuthentication()
            request.user = authenticator.get_user(
                authenticator.get_validated_token(raw_token)
            )
        except (InvalidToken, TokenError) as e:
            logger.debug(f"Rejected bearer token: {e}")
