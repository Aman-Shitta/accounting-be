"""
The client's chart of accounts, plus the profile used to classify against it.
"""

from django.conf import settings
from django.db import models

from v1.common.models import TimeStampedModel
from v1.common.querysets import tenant_manager
from v1.tenancy.models import Client, Firm


class LedgerAccountType(TimeStampedModel):
    """
    A firm-defined account type. Scoped to the firm — the old table was global,
    so one firm's taxonomy showed up in every other firm's dropdowns.
    """

    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="account_types")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "ledger_account_type"
        verbose_name = "Ledger Account Type"
        verbose_name_plural = "Ledger Account Types"
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "code"], name="uniq_account_type_code_per_firm"
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"


class LedgerAccount(TimeStampedModel):
    """
    One account in a client's chart of accounts.

    Reachable from exactly one client. The old model carried both a
    ``customer`` and a ``client`` foreign key, set independently, so the two
    could disagree about which firm an account belonged to.
    """

    class AccountClass(models.TextChoices):
        ASSET = "asset", "Asset"
        LIABILITY = "liability", "Liability"
        EQUITY = "equity", "Equity"
        REVENUE = "revenue", "Revenue"
        EXPENSE = "expense", "Expense"

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="ledger_accounts"
    )
    account_number = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    account_class = models.CharField(
        max_length=32, choices=AccountClass.choices, blank=True
    )
    sub_class = models.CharField(
        max_length=100, blank=True, help_text="e.g. Cash, Fixed Assets, Current Liabilities"
    )
    account_type = models.ForeignKey(
        LedgerAccountType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accounts",
    )

    is_active = models.BooleanField(default=True)

    objects = tenant_manager("client")()

    class Meta:
        db_table = "ledger_account"
        verbose_name = "Ledger Account"
        verbose_name_plural = "Ledger Accounts"
        ordering = ["account_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "account_number"], name="uniq_account_number_per_client"
            ),
        ]
        indexes = [models.Index(fields=["client", "is_active"])]

    def __str__(self):
        return f"{self.account_number} — {self.name}"


class ClientClassifierProfile(TimeStampedModel):
    """
    The OpenAI assistant and vector store used to classify this client's
    transactions against its chart of accounts.

    Provisioned from the client's uploaded reference documents. Classification
    cannot run without one.
    """

    client = models.OneToOneField(
        Client, on_delete=models.CASCADE, related_name="classifier_profile"
    )
    assistant_id = models.CharField(max_length=128, blank=True)
    vector_store_id = models.CharField(max_length=128, blank=True)
    model_name = models.CharField(max_length=64, default="gpt-4o")
    response_schema = models.JSONField(null=True, blank=True)
    special_rules = models.TextField(
        blank=True, help_text="Client-specific guidance appended to the classifier prompt"
    )
    is_active = models.BooleanField(default=True)

    provisioned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provisioned_classifier_profiles",
    )

    objects = tenant_manager("client")()

    class Meta:
        db_table = "client_classifier_profile"
        verbose_name = "Client Classifier Profile"
        verbose_name_plural = "Client Classifier Profiles"

    def __str__(self):
        return f"Classifier for {self.client.name}"

    @property
    def is_usable(self) -> bool:
        """A profile with no vector store classifies nothing."""
        return bool(self.is_active and self.vector_store_id)
