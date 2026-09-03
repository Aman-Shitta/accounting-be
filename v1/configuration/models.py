"""
Per-client extraction configuration, and the immutable versions of it that
accounting periods pin.

The central distinction the old schema could not express: a **transactional**
document is a list of transactions and has nothing to name in advance, while a
**field-configured** document yields a fixed set of named values that must be
declared before extraction can run.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from storage.uploads import upload_to_input_files_folder
from v1.common.models import TimeStampedModel, UUIDPrimaryKeyModel
from v1.common.querysets import tenant_manager
from v1.ledger.models import LedgerAccount
from v1.tenancy.models import Client


class DocumentType(models.TextChoices):
    """What kind of document a source produces, and therefore how it is read."""

    BANK_STATEMENT = "bank_statement", "Bank Statement"
    CREDIT_CARD = "credit_card", "Credit Card"
    CHECK_REGISTER = "check_register", "Check Register"
    PAYROLL = "payroll", "Payroll"
    SALES = "sales", "Sales"
    MISC = "misc", "Misc"

    @classmethod
    def transactional(cls) -> set[str]:
        """Types whose output is a transaction list. No fields configurable."""
        return {cls.BANK_STATEMENT.value, cls.CREDIT_CARD.value, cls.CHECK_REGISTER.value}

    @classmethod
    def field_configured(cls) -> set[str]:
        """Types whose output is a set of named values. Fields required."""
        return {cls.PAYROLL.value, cls.SALES.value, cls.MISC.value}


class DocumentSource(TimeStampedModel):
    """
    A recurring source of documents for a client — "Chase Operating ...1234",
    "ADP Payroll". One document per source is expected each period.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="document_sources"
    )
    name = models.CharField(max_length=255)
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)

    ledger_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_sources",
        help_text="For transactional sources, the account the statement represents",
    )
    default_offset_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offset_document_sources",
        help_text="Where the other side of each entry lands by default",
    )

    extraction_notes = models.TextField(
        blank=True,
        help_text="Free text passed to the classifier as client-specific guidance",
    )
    reference_file = models.FileField(
        upload_to=upload_to_input_files_folder,
        max_length=500,
        null=True,
        blank=True,
        help_text="An example document, for reference only — never extracted",
    )

    is_active = models.BooleanField(default=True)

    objects = tenant_manager("client")()

    class Meta:
        db_table = "document_source"
        verbose_name = "Document Source"
        verbose_name_plural = "Document Sources"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "name"], name="uniq_source_name_per_client"
            ),
        ]
        indexes = [models.Index(fields=["client", "is_active"])]

    def __str__(self):
        return f"{self.name} ({self.get_document_type_display()})"

    @property
    def is_transactional(self) -> bool:
        return self.document_type in DocumentType.transactional()

    @property
    def is_field_configured(self) -> bool:
        return self.document_type in DocumentType.field_configured()

    def clean(self):
        if self.is_transactional and self.pk and self.fields.exists():
            raise ValidationError(
                {
                    "document_type": (
                        f"{self.get_document_type_display()} produces a transaction "
                        f"list, so it cannot have extraction fields. Remove them first."
                    )
                }
            )


class ExtractionField(TimeStampedModel):
    """
    One named value to pull out of a field-configured document, and where it
    books.

    ``key`` becomes a property name in the JSON schema handed to the extractor,
    and ``prompt_hint`` becomes that property's description — see
    ``extractor/pipelines/kv/landing_pipeline.py:build_dynamic_extraction_model``.
    """

    class Direction(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    document_source = models.ForeignKey(
        DocumentSource, on_delete=models.CASCADE, related_name="fields"
    )
    key = models.SlugField(
        max_length=128, help_text="Identifier used in the extraction schema"
    )
    label = models.CharField(max_length=255, help_text="Human name shown in the UI")
    prompt_hint = models.TextField(
        blank=True,
        help_text="Tells the extractor what to look for, e.g. 'Total employer taxes, "
        "bottom of the summary page'",
    )

    direction = models.CharField(max_length=10, choices=Direction.choices)
    ledger_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extraction_fields",
    )
    offset_ledger_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offset_extraction_fields",
    )

    position = models.PositiveIntegerField(default=0)

    objects = tenant_manager("document_source__client")()

    class Meta:
        db_table = "extraction_field"
        verbose_name = "Extraction Field"
        verbose_name_plural = "Extraction Fields"
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["document_source", "key"], name="uniq_field_key_per_source"
            ),
        ]

    def __str__(self):
        return f"{self.label} ({self.key})"

    def clean(self):
        if self.document_source_id and self.document_source.is_transactional:
            raise ValidationError(
                "Extraction fields cannot be configured on a transactional "
                "document type; its output is a transaction list."
            )


class JournalTemplate(TimeStampedModel):
    """The journal entry to produce from one or more document sources."""

    class Frequency(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        ANNUAL = "annual", "Annual"
        ADHOC = "adhoc", "Ad hoc"

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="journal_templates"
    )
    name = models.CharField(max_length=255)
    reference = models.CharField(max_length=255, blank=True)
    frequency = models.CharField(
        max_length=16, choices=Frequency.choices, default=Frequency.MONTHLY
    )
    entry_type = models.CharField(max_length=64, blank=True)

    uses_extracted_fields = models.BooleanField(
        default=False,
        help_text="True when lines draw their amounts from extracted fields rather "
        "than fixed ledger accounts",
    )
    description = models.TextField(blank=True)

    sources = models.ManyToManyField(
        DocumentSource, related_name="journal_templates", blank=True
    )

    objects = tenant_manager("client")()

    class Meta:
        db_table = "journal_template"
        verbose_name = "Journal Template"
        verbose_name_plural = "Journal Templates"
        constraints = [
            models.UniqueConstraint(
                fields=["client", "frequency", "name"],
                name="uniq_template_name_per_client_frequency",
            ),
        ]
        indexes = [models.Index(fields=["client", "frequency"])]

    def __str__(self):
        return f"{self.name} ({self.get_frequency_display()})"


class JournalTemplateLine(TimeStampedModel):
    """
    One line of a journal template.

    The old model encoded the amount as two free-text columns holding "a
    number, an attribute id, or the string 'manual'". Here the side and the
    source of the amount are separate, typed columns.
    """

    class Side(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    class AmountSource(models.TextChoices):
        EXTRACTED_FIELD = "extracted_field", "From an extracted field"
        FIXED = "fixed", "Fixed amount"
        MANUAL = "manual", "Entered each period"

    template = models.ForeignKey(
        JournalTemplate, on_delete=models.CASCADE, related_name="lines"
    )

    side = models.CharField(max_length=10, choices=Side.choices)
    amount_source = models.CharField(max_length=20, choices=AmountSource.choices)

    extraction_field = models.ForeignKey(
        ExtractionField,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="template_lines",
        help_text="Required when amount_source is extracted_field",
    )
    fixed_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Required when amount_source is fixed",
    )
    ledger_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="template_lines",
    )

    label = models.CharField(max_length=255, blank=True)
    comment = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)

    objects = tenant_manager("template__client")()

    class Meta:
        db_table = "journal_template_line"
        verbose_name = "Journal Template Line"
        verbose_name_plural = "Journal Template Lines"
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.template.name} — {self.get_side_display()} {self.label}".strip()

    def clean(self):
        if self.amount_source == self.AmountSource.EXTRACTED_FIELD and not self.extraction_field_id:
            raise ValidationError(
                {"extraction_field": "Required when the amount comes from an extracted field."}
            )
        if self.amount_source == self.AmountSource.FIXED and self.fixed_amount is None:
            raise ValidationError(
                {"fixed_amount": "Required when the amount is fixed."}
            )


class ConfigVersion(UUIDPrimaryKeyModel):
    """
    An immutable snapshot of a client's configuration, as one JSONB document.

    Replaces four mirror tables that duplicated every source, field, template
    and template line on every period open — and copied the source files
    alongside them. The payload is only ever read whole, at period open and at
    journal-entry generation, so a document beats a join.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="config_versions"
    )
    version = models.PositiveIntegerField()
    payload = models.JSONField(
        help_text="Frozen document sources, extraction fields, journal templates and lines"
    )

    published_at = models.DateTimeField(auto_now_add=True, db_index=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_config_versions",
    )

    objects = tenant_manager("client")()

    class Meta:
        db_table = "config_version"
        verbose_name = "Config Version"
        verbose_name_plural = "Config Versions"
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "version"], name="uniq_config_version_per_client"
            ),
        ]

    def __str__(self):
        return f"{self.client.name} config v{self.version}"

    @property
    def sources(self) -> list[dict]:
        return self.payload.get("document_sources", [])

    def source_by_key(self, key: str) -> dict | None:
        return next((s for s in self.sources if s.get("key") == key), None)
