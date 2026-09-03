"""
Account lifecycle: invite, set password, reset.

There is no self-service signup. A firm owner invites by email; the invitee
receives a link and chooses a password. The same machinery serves password
reset, with a shorter token lifetime.
"""

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from v1.identity.models import PasswordSetToken, UserProfile
from v1.tenancy.models import FirmMembership

logger = logging.getLogger(__name__)
User = get_user_model()


class InviteError(Exception):
    """The invite cannot be issued as requested."""


def _set_password_url(raw_token: str) -> str:
    base = getattr(settings, "APP_BASE_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/set-password?{urlencode({'token': raw_token})}"


def _send(subject: str, body: str, to_email: str) -> None:
    """
    Deliver a transactional email.

    Failures are logged, not raised: an invite row that exists with an
    undelivered email can be re-sent, but a half-rolled-back invite cannot.
    """
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@aicounting.app"),
            recipient_list=[to_email],
            fail_silently=False,
        )
    except Exception:
        logger.exception(f"Failed to send '{subject}' to {to_email}")


@transaction.atomic
def invite_member(
    *, email: str, role: str, firm, invited_by=None, first_name: str = "", last_name: str = ""
) -> tuple[FirmMembership, str]:
    """
    Create (or reuse) a user, give them a membership, and email a set-password
    link. Returns the membership and the raw token.

    Every role belongs to a firm, reviewers included.
    """
    email = email.strip().lower()
    if not email:
        raise InviteError("An email address is required.")

    if firm is None:
        raise InviteError(f"A firm is required to invite a {role}.")

    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "username": email,
            "first_name": first_name,
            "last_name": last_name,
            "is_active": False,
        },
    )
    UserProfile.objects.get_or_create(user=user)

    membership, membership_created = FirmMembership.objects.get_or_create(
        user=user,
        firm=firm,
        role=role,
        defaults={"invited_by": invited_by},
    )
    if not membership_created and membership.is_active:
        raise InviteError(f"{email} already has that role.")

    if not membership.is_active:
        membership.is_active = True
        membership.save(update_fields=["is_active", "updated_at"])

    _, raw_token = PasswordSetToken.issue(user, PasswordSetToken.Purpose.INVITE)

    _send(
        subject=f"You have been invited to {firm.name}",
        body=(
            f"You have been invited to join {firm.name} on aicounting.\n\n"
            f"Set your password to get started:\n{_set_password_url(raw_token)}\n\n"
            f"This link expires in 48 hours."
        ),
        to_email=email,
    )

    return membership, raw_token


def request_password_reset(*, email: str) -> None:
    """
    Email a reset link if the address belongs to an account.

    Always returns without indicating whether the address exists — the caller
    responds identically either way, so the endpoint cannot be used to
    enumerate users.
    """
    user = User.objects.filter(email__iexact=email.strip()).first()
    if user is None:
        logger.info(f"Password reset requested for unknown address: {email}")
        return

    _, raw_token = PasswordSetToken.issue(user, PasswordSetToken.Purpose.RESET)
    _send(
        subject="Reset your aicounting password",
        body=(
            f"Use this link to choose a new password:\n{_set_password_url(raw_token)}\n\n"
            f"This link expires in 1 hour. If you did not ask for it, ignore this email."
        ),
        to_email=user.email,
    )


@transaction.atomic
def set_password(*, raw_token: str, new_password: str):
    """
    Consume a token and set the password. Returns the user, or ``None`` when
    the token is unknown, expired or already used.
    """
    token = PasswordSetToken.redeem(raw_token)
    if token is None:
        return None

    user = token.user
    user.set_password(new_password)
    user.is_active = True
    user.save(update_fields=["password", "is_active"])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.is_verified = True
    profile.save(update_fields=["is_verified", "updated_at"])

    token.mark_used()
    return user


def record_login(user) -> None:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.last_login_at = timezone.now()
    profile.save(update_fields=["last_login_at", "updated_at"])
