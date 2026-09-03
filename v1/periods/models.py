"""
Accounting periods and everything extracted within one.

A period pins the config version it was opened against, so editing
configuration afterwards cannot rewrite a closed month. Extracted rows carry
their own resolved accounts, so they stay meaningful even if the configuration
they came from is later changed or removed.
"""

from auditlog.registry import auditlog
from django.conf import settings
from django.db import models
from django.utils import timezone

from storage.uploads import upload_to_montly_accounting_folder
from v1.common.models import SoftDeleteModel, TimeStampedModel
from v1.common.querysets import tenant_manager
from v1.configuration.models import ConfigVersion, DocumentSource, DocumentType, ExtractionField
from v1.ledger.models import LedgerAccount
from v1.tenancy.models import Client, FirmMembership


class AccountingPeriod(TimeStampedModel, SoftDeleteModel):
    """One month of bookkeeping for one client."""

    class Status(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="periods")
    config_version = models.ForeignKey(
        ConfigVersion,
        on_delete=models.PROTECT,
        related_name="periods",
        help_text="The configuration this period was opened against; never changes",
    )

    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.INITIATED
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opened_periods",
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = tenant_manager("client")()

    class Meta:
        db_table = "accounting_period"
        verbose_name = "Accounting Period"
        verbose_name_plural = "Accounting Periods"
        ordering = ["-year", "-month"]
        constraints = [
            # The old model enforced this in clean(), which DRF never calls.
            models.UniqueConstraint(
                fields=["client", "year", "month"],
                condition=models.Q(is_deleted=False),
                name="uniq_open_period_per_client_month",
            ),
            models.CheckConstraint(
                condition=models.Q(month__gte=1) & models.Q(month__lte=12),
                name="period_month_in_range",
            ),
        ]
        indexes = [models.Index(fields=["client", "year", "month"])]

    def __str__(self):
        return f"{self.client.name} — {self.month:02d}/{self.year} ({self.status})"

    def mark_completed(self):
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])


class PeriodDocument(TimeStampedModel):
    """The document uploaded for one source in one period."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Upload"
        UPLOADED = "uploaded", "Uploaded"
        EXTRACTING = "extracting", "Extracting"
        EXTRACTED = "extracted", "Extracted"
        PENDING_REVIEW = "pending_review", "Pending Review"
        IN_REVIEW = "in_review", "In Review"
        REVIEWED = "reviewed", "Reviewed"
        CLASSIFYING = "classifying", "Classifying"
        CLASSIFIED = "classified", "Classified"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"

    period = models.ForeignKey(
        AccountingPeriod, on_delete=models.CASCADE, related_name="documents"
    )
    document_source = models.ForeignKey(
        DocumentSource,
        on_delete=models.SET_NULL,
        null=True,
        related_name="period_documents",
        help_text="The live source row; may be removed later without losing this document",
    )
    source_key = models.CharField(
        max_length=128,
        help_text="Stable key into the period's frozen config payload",
    )
    source_name = models.CharField(
        max_length=255, help_text="Source name as it stood when the period opened"
    )
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    file = models.FileField(
        upload_to=upload_to_montly_accounting_folder,
        max_length=500,
        null=True,
        blank=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_period_documents",
    )
    failure_reason = models.TextField(blank=True)

    assigned_reviewer = models.ForeignKey(
        FirmMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_documents",
        help_text="Set by round-robin when control totals do not balance",
    )
    review_notes = models.TextField(blank=True)
    balance_mismatch_details = models.JSONField(null=True, blank=True)

    control_totals = models.JSONField(
        null=True,
        blank=True,
        help_text="Opening/closing balances and totals extracted from the document",
    )
    markdown_metadata = models.JSONField(
        null=True, blank=True, help_text="Per-page parsed markdown and artifact paths"
    )

    objects = tenant_manager("period__client")()

    class Meta:
        db_table = "period_document"
        verbose_name = "Period Document"
        verbose_name_plural = "Period Documents"
        ordering = ["source_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["period", "source_key"], name="uniq_document_per_period_source"
            ),
        ]
        indexes = [models.Index(fields=["period", "status"])]

    def __str__(self):
        return f"{self.source_name} — {self.period} ({self.status})"

    @property
    def client(self):
        return self.period.client

    def mark_failed(self, reason: str):
        self.status = self.Status.FAILED
        self.failure_reason = reason
        self.save(update_fields=["status", "failure_reason", "updated_at"])


class PeriodTransaction(TimeStampedModel):
    """
    One transaction extracted from a transactional document.

    ``transaction_date`` is a real date; ``raw_date`` keeps whatever the
    document actually said, because statements are not consistent and the
    original text matters when a parse looks wrong.
    """

    class Direction(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    document = models.ForeignKey(
        PeriodDocument, on_delete=models.CASCADE, related_name="transactions"
    )

    page_number = models.PositiveIntegerField()
    line_number = models.PositiveIntegerField()

    transaction_date = models.DateField(null=True, blank=True)
    raw_date = models.CharField(
        max_length=64, blank=True, help_text="Date exactly as printed on the document"
    )

    description = models.TextField()
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Always positive; direction carries the sign",
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)

    ledger_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        help_text="Assigned by the classifier or edited by a reviewer",
    )
    offset_ledger_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offset_transactions",
    )
    classified_at = models.DateTimeField(null=True, blank=True)
    is_manually_classified = models.BooleanField(default=False)

    is_check = models.BooleanField(default=False)
    check_number = models.CharField(max_length=50, blank=True)

    objects = tenant_manager("document__period__client")()

    class Meta:
        db_table = "period_transaction"
        verbose_name = "Period Transaction"
        verbose_name_plural = "Period Transactions"
        ordering = ["page_number", "line_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "page_number", "line_number"],
                name="uniq_transaction_position_per_document",
            ),
        ]
        indexes = [
            models.Index(fields=["document", "page_number"]),
            models.Index(fields=["document", "ledger_account"]),
        ]

    def __str__(self):
        return f"{self.raw_date or self.transaction_date} {self.description[:40]} {self.amount}"


class PeriodCheckDetail(TimeStampedModel):
    """Payee and memo read off a check image, matched back to a transaction."""

    document = models.ForeignKey(
        PeriodDocument, on_delete=models.CASCADE, related_name="check_details"
    )
    transaction = models.ForeignKey(
        PeriodTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="check_details",
    )

    page_number = models.PositiveIntegerField()
    check_number = models.CharField(max_length=50, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    payee = models.TextField(blank=True)
    memo = models.TextField(blank=True)
    cleared_on = models.DateField(null=True, blank=True)

    objects = tenant_manager("document__period__client")()

    class Meta:
        db_table = "period_check_detail"
        verbose_name = "Period Check Detail"
        verbose_name_plural = "Period Check Details"
        ordering = ["page_number", "check_number"]
        indexes = [models.Index(fields=["document", "check_number"])]

    def __str__(self):
        return f"Check #{self.check_number} — {self.payee} {self.amount}"


class PeriodFieldValue(TimeStampedModel):
    """
    One extracted value for a configured field.

    ``field_key``, ``field_label`` and the resolved accounts are denormalized
    at write time so the row survives the field being edited or deleted. The
    foreign key is a convenience, not the source of truth.
    """

    class Direction(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    document = models.ForeignKey(
        PeriodDocument, on_delete=models.CASCADE, related_name="field_values"
    )
    extraction_field = models.ForeignKey(
        ExtractionField,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="period_values",
    )

    field_key = models.CharField(max_length=128)
    field_label = models.CharField(max_length=255)
    page_number = models.PositiveIntegerField(default=1)

    value = models.CharField(max_length=1000, blank=True)
    direction = models.CharField(max_length=10, choices=Direction.choices, blank=True)

    ledger_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="field_values",
    )
    offset_ledger_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offset_field_values",
    )

    objects = tenant_manager("document__period__client")()

    class Meta:
        db_table = "period_field_value"
        verbose_name = "Period Field Value"
        verbose_name_plural = "Period Field Values"
        ordering = ["field_key", "page_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "field_key", "page_number"],
                name="uniq_field_value_per_document_page",
            ),
        ]

    def __str__(self):
        return f"{self.field_label}: {self.value}"


class PeriodManualJournalLine(TimeStampedModel):
    """
    An amount a person types in for a template line whose ``amount_source`` is
    ``manual`` — not extracted from any document.
    """

    class Direction(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    period = models.ForeignKey(
        AccountingPeriod, on_delete=models.CASCADE, related_name="manual_journal_lines"
    )
    template_line_key = models.CharField(
        max_length=128, help_text="Key into the period's frozen template lines"
    )

    value = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    direction = models.CharField(max_length=10, choices=Direction.choices, blank=True)
    description = models.TextField(blank=True)

    ledger_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manual_journal_lines",
    )
    offset_ledger_account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offset_manual_journal_lines",
    )
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entered_journal_lines",
    )

    objects = tenant_manager("period__client")()

    class Meta:
        db_table = "period_manual_journal_line"
        verbose_name = "Period Manual Journal Line"
        verbose_name_plural = "Period Manual Journal Lines"
        constraints = [
            models.UniqueConstraint(
                fields=["period", "template_line_key"],
                name="uniq_manual_line_per_period_template_line",
            ),
        ]

    def __str__(self):
        return f"{self.template_line_key}: {self.value}"


class ClassificationJob(TimeStampedModel):
    """
    A queued GL classification.

    Processed one at a time per client, because a client's OpenAI assistant and
    vector store cannot safely serve two concurrent runs.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    document = models.ForeignKey(
        PeriodDocument, on_delete=models.CASCADE, related_name="classification_jobs"
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="classification_jobs",
        help_text="Denormalized so the queue can serialize per client without a join",
    )

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    priority = models.IntegerField(default=0)

    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    last_error = models.TextField(blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = tenant_manager("client")()

    class Meta:
        db_table = "classification_job"
        verbose_name = "Classification Job"
        verbose_name_plural = "Classification Jobs"
        ordering = ["-priority", "created_at"]
        indexes = [models.Index(fields=["client", "status", "created_at"])]

    def __str__(self):
        return f"Classification for document {self.document_id} ({self.status})"

    # ---- queue operations ------------------------------------------------

    @classmethod
    def enqueue(cls, document, priority: int = 0) -> "ClassificationJob":
        """Queue a document, or return the job already queued for it."""
        existing = cls.objects.filter(
            document=document, status__in=[cls.Status.PENDING, cls.Status.PROCESSING]
        ).first()
        if existing:
            return existing

        return cls.objects.create(
            document=document, client=document.period.client, priority=priority
        )

    @classmethod
    def next_for_client(cls, client_id: int) -> "ClassificationJob | None":
        """
        Next pending job for a client, or ``None`` when one is already running
        for them.
        """
        if cls.objects.filter(client_id=client_id, status=cls.Status.PROCESSING).exists():
            return None

        return (
            cls.objects.filter(client_id=client_id, status=cls.Status.PENDING)
            .order_by("-priority", "created_at")
            .first()
        )

    @classmethod
    def pending_client_ids(cls) -> list[int]:
        return list(
            cls.objects.filter(status=cls.Status.PENDING)
            .values_list("client_id", flat=True)
            .distinct()
        )

    def mark_processing(self):
        self.status = self.Status.PROCESSING
        self.started_at = timezone.now()
        self.attempts += 1
        self.save(update_fields=["status", "started_at", "attempts", "updated_at"])

    def mark_completed(self):
        self.status = self.Status.COMPLETED
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "finished_at", "updated_at"])

    def mark_failed(self, error: str):
        """Back to pending while attempts remain, otherwise failed for good."""
        self.last_error = error

        if self.attempts < self.max_attempts:
            self.status = self.Status.PENDING
        else:
            self.status = self.Status.FAILED
            self.finished_at = timezone.now()

        self.save(update_fields=["status", "last_error", "finished_at", "updated_at"])

    @property
    def will_retry(self) -> bool:
        return self.status == self.Status.PENDING and self.attempts > 0


# Rows a human edits carry an audit trail; extraction output that nobody has
# touched does not need one.
auditlog.register(
    PeriodTransaction,
    include_fields=[
        "transaction_date",
        "description",
        "amount",
        "direction",
        "ledger_account",
        "offset_ledger_account",
    ],
)
auditlog.register(
    PeriodFieldValue,
    include_fields=["value", "direction", "ledger_account", "offset_ledger_account"],
)
auditlog.register(
    PeriodManualJournalLine,
    include_fields=["value", "direction", "ledger_account", "offset_ledger_account"],
)
