"""Auth endpoints: login, refresh, invite redemption, password reset, whoami."""

import logging

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from v1.common.envelope import EnvelopeMixin
from v1.common.permissions import IsFirmOwner
from v1.common.querysets import accessible_clients
from v1.common.responses import create_api_response
from v1.identity import services
from v1.identity.serializers import (
    ForgotPasswordSerializer,
    InviteSerializer,
    LoginSerializer,
    MembershipSerializer,
    SetPasswordSerializer,
)
from v1.tenancy.models import FirmMembership

logger = logging.getLogger(__name__)


def _token_pair(user) -> dict:
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class LoginView(EnvelopeMixin, GenericAPIView):
    """Exchange email and password for an access/refresh pair."""

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = LoginSerializer
    throttle_scope = "login"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return create_api_response(
                status.HTTP_400_BAD_REQUEST, "Login failed.", errors=serializer.errors
            )

        user = serializer.validated_data["user"]
        services.record_login(user)

        return create_api_response(
            status.HTTP_200_OK, "Signed in.", data=_token_pair(user)
        )


class RefreshTokenView(EnvelopeMixin, GenericAPIView):
    """Exchange a refresh token for a fresh access token."""

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = None

    def post(self, request):
        raw = (request.data or {}).get("refresh")
        if not raw:
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "A refresh token is required.",
                errors={"refresh": ["This field is required."]},
            )

        try:
            refresh = RefreshToken(raw)
        except TokenError:
            return create_api_response(
                status.HTTP_401_UNAUTHORIZED, "That refresh token is not valid."
            )

        return create_api_response(
            status.HTTP_200_OK, "Token refreshed.", data={"access": str(refresh.access_token)}
        )


class SetPasswordView(EnvelopeMixin, GenericAPIView):
    """Consume an invite or reset token and set a password."""

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = SetPasswordSerializer
    throttle_scope = "set_password"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Could not set your password.",
                errors=serializer.errors,
            )

        user = services.set_password(
            raw_token=serializer.validated_data["token"],
            new_password=serializer.validated_data["password"],
        )
        if user is None:
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "That link has expired or has already been used. Ask for a new one.",
            )

        return create_api_response(
            status.HTTP_200_OK, "Password set. You are signed in.", data=_token_pair(user)
        )


class ForgotPasswordView(EnvelopeMixin, GenericAPIView):
    """Send a reset link, if the address belongs to an account."""

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = ForgotPasswordSerializer
    throttle_scope = "set_password"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return create_api_response(
                status.HTTP_400_BAD_REQUEST, "Invalid request.", errors=serializer.errors
            )

        services.request_password_reset(email=serializer.validated_data["email"])

        # Identical response whether or not the account exists.
        return create_api_response(
            status.HTTP_200_OK,
            "If that address has an account, a reset link is on its way.",
        )


class WhoAmIView(EnvelopeMixin, GenericAPIView):
    """The caller's identity, roles and how many clients they can reach."""

    permission_classes = [IsAuthenticated]
    serializer_class = None

    def get(self, request):
        user = request.user
        memberships = FirmMembership.objects.filter(
            user=user, is_active=True
        ).select_related("firm")

        return create_api_response(
            status.HTTP_200_OK,
            "Current user.",
            data={
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_verified": getattr(getattr(user, "profile", None), "is_verified", False),
                "memberships": MembershipSerializer(memberships, many=True).data,
                "client_count": accessible_clients(user).count(),
            },
        )


class MemberInviteView(EnvelopeMixin, GenericAPIView):
    """Invite someone into the caller's firm."""

    permission_classes = [IsAuthenticated, IsFirmOwner]
    serializer_class = InviteSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return create_api_response(
                status.HTTP_400_BAD_REQUEST, "Invalid invite.", errors=serializer.errors
            )

        owner_membership = FirmMembership.objects.filter(
            user=request.user, role=FirmMembership.Role.OWNER, is_active=True
        ).first()

        try:
            membership, _ = services.invite_member(
                email=serializer.validated_data["email"],
                role=serializer.validated_data["role"],
                firm=owner_membership.firm if owner_membership else None,
                invited_by=request.user,
                first_name=serializer.validated_data.get("first_name", ""),
                last_name=serializer.validated_data.get("last_name", ""),
            )
        except services.InviteError as e:
            return create_api_response(status.HTTP_400_BAD_REQUEST, str(e))

        return create_api_response(
            status.HTTP_201_CREATED,
            "Invitation sent.",
            data=MembershipSerializer(membership).data,
        )
