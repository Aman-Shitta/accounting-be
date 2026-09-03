"""
Tenancy: firms, their people, and their clients.

A ``Firm`` is a CPA firm and the tenant boundary. Everything else in the
system hangs off one, directly or through a ``Client``.
"""

import random
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from storage.uploads import upload_to_customer_client_folder
from v1.common.models import SoftDeleteModel, TimeStampedModel
from v1.common.querysets import tenant_manager


class Firm(TimeStampedModel):
    """A CPA firm. The tenant."""

    name = models.CharField(max_length=255)
    public_id = models.CharField(
        max_length=9,
        unique=True,
        editable=False,
        help_text="Human-quotable firm reference, e.g. 1234-5678",
    )

    street = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    postal_code = models.CharField(max_length=16, blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "firm"
        verbose_name = "Firm"
        verbose_name_plural = "Firms"

    def __str__(self):
        return f"{self.name} ({self.public_id})"

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = self._generate_public_id()
        super().save(*args, **kwargs)

    @classmethod
    def _generate_public_id(cls) -> str:
        while True:
            candidate = (
                f"{''.join(random.choices(string.digits, k=4))}-"
                f"{''.join(random.choices(string.digits, k=4))}"
            )
            if not cls.objects.filter(public_id=candidate).exists():
                return candidate


class FirmMembership(TimeStampedModel):
    """
    A user's role within a firm.

    Replaces three near-identical models (customer, accountant, reviewer) that
    each carried their own copy of the linked user, Azure id, refresh token and
    verified flag.

    Every membership belongs to a firm, reviewers included — the firm is the
    tenant boundary and nothing crosses it.
    """

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ACCOUNTANT = "accountant", "Accountant"
        REVIEWER = "reviewer", "Reviewer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="firm_memberships",
    )
    firm = models.ForeignKey(
        Firm,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_memberships",
    )

    review_assigned_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this reviewer was handed a document; drives round-robin",
    )

    class Meta:
        db_table = "firm_membership"
        verbose_name = "Firm Membership"
        verbose_name_plural = "Firm Memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "firm", "role"], name="uniq_membership_user_firm_role"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["firm", "role", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user} — {self.get_role_display()} @ {self.firm.name}"

    @classmethod
    def next_reviewer(cls, firm):
        """
        The firm's least-recently-assigned active reviewer, stamped so the next
        call returns someone else. ``None`` when the firm has no reviewers.

        Scoped to one firm: a reviewer sees the documents of their own firm's
        clients and nobody else's.
        """
        reviewer = (
            cls.objects.filter(firm=firm, role=cls.Role.REVIEWER, is_active=True)
            .order_by(models.F("review_assigned_at").asc(nulls_first=True))
            .first()
        )
        if reviewer is None:
            return None

        reviewer.review_assigned_at = timezone.now()
        reviewer.save(update_fields=["review_assigned_at", "updated_at"])
        return reviewer


class Client(TimeStampedModel, SoftDeleteModel):
    """A firm's client — the business whose books are being kept."""

    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="clients")

    name = models.CharField(max_length=255)
    external_ref = models.CharField(
        max_length=64,
        help_text="The firm's own code for this client. Unique per firm, not globally.",
    )

    street = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    postal_code = models.CharField(max_length=16, blank=True)

    allow_review = models.BooleanField(
        default=False,
        help_text="Route documents to a human reviewer when control totals do not balance",
    )

    objects = tenant_manager("pk")()

    class Meta:
        db_table = "client"
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "external_ref"], name="uniq_client_ref_per_firm"
            ),
        ]
        indexes = [models.Index(fields=["firm", "is_deleted"])]

    def __str__(self):
        return f"{self.name} ({self.external_ref})"


class ClientAssignment(TimeStampedModel):
    """Which firm members may work on a client."""

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="assignments"
    )
    membership = models.ForeignKey(
        FirmMembership, on_delete=models.CASCADE, related_name="client_assignments"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="client_assignments_made",
    )

    objects = tenant_manager("client")()

    class Meta:
        db_table = "client_assignment"
        verbose_name = "Client Assignment"
        verbose_name_plural = "Client Assignments"
        constraints = [
            models.UniqueConstraint(
                fields=["client", "membership"], name="uniq_client_membership"
            ),
        ]

    def __str__(self):
        return f"{self.membership.user} -> {self.client.name}"

    def clean(self):
        if self.membership.firm_id and self.membership.firm_id != self.client.firm_id:
            raise ValidationError(
                "Cannot assign a member of one firm to another firm's client."
            )


class ClientContact(TimeStampedModel):
    """A person to contact at the client."""

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="contacts"
    )
    name = models.CharField(max_length=255)
    title = models.CharField(max_length=128, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_primary = models.BooleanField(default=False)

    objects = tenant_manager("client")()

    class Meta:
        db_table = "client_contact"
        verbose_name = "Client Contact"
        verbose_name_plural = "Client Contacts"

    def __str__(self):
        return f"{self.name} @ {self.client.name}"


class ClientReferenceDocument(TimeStampedModel):
    """
    A document describing the client rather than a period: chart of accounts,
    vendor list, GL history. Feeds the classifier's vector store.
    """

    class Kind(models.TextChoices):
        CHART_OF_ACCOUNTS = "chart_of_accounts", "Chart of Accounts"
        VENDOR_LIST = "vendor_list", "Vendor List"
        GL_HISTORY = "gl_history", "GL History"

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="reference_documents"
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    file = models.FileField(upload_to=upload_to_customer_client_folder, max_length=500)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_reference_documents",
    )

    objects = tenant_manager("client")()

    class Meta:
        db_table = "client_reference_document"
        verbose_name = "Client Reference Document"
        verbose_name_plural = "Client Reference Documents"
        indexes = [models.Index(fields=["client", "kind"])]

    def __str__(self):
        return f"{self.client.name} — {self.get_kind_display()}"
