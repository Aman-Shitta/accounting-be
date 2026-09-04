"""
Identity: per-user state and the tokens that back invite and password reset.

Auth is email + password. There is no SSO — see
``documentation/02-decisions.md``.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from v1.common.models import TimeStampedModel, UUIDPrimaryKeyModel

INVITE_TOKEN_TTL = timedelta(hours=48)
RESET_TOKEN_TTL = timedelta(hours=1)


class UserProfile(TimeStampedModel):
    """
    Per-user state that does not belong on a membership.

    Replaces the ``verified`` / ``azure_id`` / ``refresher_token`` triplet that
    was duplicated across the customer, accountant and reviewer models.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    is_verified = models.BooleanField(
        default=False, help_text="True once the user has set a password"
    )
    is_platform_staff = models.BooleanField(
        default=False,
        help_text="Operates the platform itself, not any one firm — belongs to "
        "no FirmMembership and sees the cross-firm /platform/ surface instead "
        "of a firm's own dashboard.",
    )
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "user_profile"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"Profile for {self.user}"


class PasswordSetToken(UUIDPrimaryKeyModel):
    """
    A single-use, expiring token backing both the invite and the reset flow.

    Only the SHA-256 hash is stored: a database leak does not hand out
    working links.
    """

    class Purpose(models.TextChoices):
        INVITE = "invite", "Invite"
        RESET = "reset", "Password reset"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="password_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    purpose = models.CharField(max_length=16, choices=Purpose.choices)

    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "password_set_token"
        verbose_name = "Password Set Token"
        verbose_name_plural = "Password Set Tokens"
        indexes = [models.Index(fields=["user", "purpose", "used_at"])]

    def __str__(self):
        return f"{self.get_purpose_display()} token for {self.user}"

    # ---- issuing and redeeming -----------------------------------------

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def issue(cls, user, purpose: str) -> tuple["PasswordSetToken", str]:
        """
        Mint a token for ``user``, invalidating any outstanding one for the
        same purpose. Returns the row and the raw token — the raw value is
        never recoverable afterwards, so it must be emailed now.
        """
        cls.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(
            used_at=timezone.now()
        )

        raw_token = secrets.token_urlsafe(48)
        ttl = INVITE_TOKEN_TTL if purpose == cls.Purpose.INVITE else RESET_TOKEN_TTL

        token = cls.objects.create(
            user=user,
            token_hash=cls.hash_token(raw_token),
            purpose=purpose,
            expires_at=timezone.now() + ttl,
        )
        return token, raw_token

    @classmethod
    def redeem(cls, raw_token: str) -> "PasswordSetToken | None":
        """Return the usable token matching ``raw_token``, or ``None``."""
        token = cls.objects.filter(token_hash=cls.hash_token(raw_token)).first()
        if token is None or not token.is_usable:
            return None
        return token

    @property
    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()

    def mark_used(self) -> None:
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])
