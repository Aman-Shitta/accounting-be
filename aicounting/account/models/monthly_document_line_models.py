"""
Models for storing extracted line items from MonthlyAccountingDocument processing.
These models are specifically designed for bank statement and credit card document line items.
"""

from django.db import models
from django.contrib.auth import get_user_model
from .monthly_accounting_document_model import MonthlyAccountingDocument

User = get_user_model()


class MonthlyDocumentBankKeyItem(models.Model):
    """
    Model to store extracted key-value pairs from a monthly document (like totals, dates, etc.).
    """
    document = models.ForeignKey(
        MonthlyAccountingDocument,
        on_delete=models.CASCADE,
        related_name="key_items",
        verbose_name="Monthly Document"
    )
    
    page_number = models.IntegerField(
        verbose_name="Page Number",
        help_text="Page number where this key item was found"
    )
    
    key = models.CharField(
        max_length=100,
        verbose_name="Key",
        help_text="Name of the extracted key (e.g., 'beginning_balance', 'ending_balance')"
    )
    
    value = models.CharField(
        max_length=1000,
        verbose_name="Value",
        null=True,
        blank=True,
        help_text="Value associated with the key"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At"
    )

    class Meta:
        db_table = 'monthly_document_key_item'
        verbose_name = "Monthly Document Key Item"
        verbose_name_plural = "Monthly Document Key Items"
        unique_together = ('document', 'page_number', 'key')

    def __str__(self):
        return f"{self.document.doc_id} - {self.key}: {self.value}"


class MonthlyDocumentBankLineItem(models.Model):
    """
    Model to store individual line items from bank statements and credit cards.
    Each line represents a transaction with all required fields for GL classification.
    """
    
    TRANSACTION_TYPE_CHOICES = [
        ('debit', 'Debit'),
        ('credit', 'Credit'),
    ]
    
    document = models.ForeignKey(
        MonthlyAccountingDocument,
        on_delete=models.CASCADE,
        related_name="line_items",
        verbose_name="Monthly Document"
    )
    
    page_number = models.IntegerField(
        verbose_name="Page Number",
        help_text="Page number where this line item was found"
    )
    
    line_number = models.IntegerField(
        verbose_name="Line Number",
        help_text="Line number within the page"
    )
    
    # Core transaction fields
    date = models.CharField(
        max_length=50,
        verbose_name="Transaction Date",
        null=True,
        blank=True,
        help_text="Date of the transaction as extracted from document"
    )
    
    description = models.TextField(
        verbose_name="Description",
        help_text="Description/narrative of the transaction"
    )
    
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        verbose_name="Amount",
        null=True,
        blank=True,
        help_text="Transaction amount (always positive, type indicates debit/credit)"
    )
    
    transaction_type = models.CharField(
        max_length=10,
        choices=TRANSACTION_TYPE_CHOICES,
        verbose_name="Transaction Type",
        null=True,
        blank=True,
        help_text="Whether this is a debit or credit transaction"
    )
    
    # Raw extracted amounts (for cases where we have separate debit/credit columns)
    debit_amount = models.CharField(
        max_length=50,
        verbose_name="Debit Amount (Raw)",
        null=True,
        blank=True,
        help_text="Raw debit amount as extracted from document"
    )
    
    credit_amount = models.CharField(
        max_length=50,
        verbose_name="Credit Amount (Raw)",
        null=True,
        blank=True,
        help_text="Raw credit amount as extracted from document"
    )
    
    # GL Classification fields (populated after classification pipeline)
    gl_account = models.ForeignKey(
        'DimAICGLAcct',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="GL Account",
        related_name="monthly_document_line_items",
        help_text="GL account assigned through classification pipeline"
    )
    
    offset_gl_account = models.ForeignKey(
        'DimAICGLAcct',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Offset GL Account",
        related_name="monthly_document_offset_line_items",
        help_text="Offset GL account for double-entry booking"
    )
    
    # Check-related fields (for check transactions)
    is_check_transaction = models.BooleanField(
        default=False,
        verbose_name="Is Check Transaction",
        help_text="Whether this line item represents a check transaction"
    )
    
    check_number = models.CharField(
        max_length=50,
        verbose_name="Check Number",
        null=True,
        blank=True,
        help_text="Check number if this is a check transaction"
    )
    
    # Audit fields
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At"
    )

    class Meta:
        db_table = 'monthly_document_line_item'
        verbose_name = "Monthly Document Line Item"
        verbose_name_plural = "Monthly Document Line Items"
        ordering = ['page_number', 'line_number']
        unique_together = ('document', 'page_number', 'line_number')

    def __str__(self):
        return f"{self.document.doc_id} - Page {self.page_number}, Line {self.line_number}: {self.description[:50]}"

    @property
    def formatted_amount(self):
        """Return formatted amount with type"""
        if self.amount:
            return f"{self.transaction_type.upper()}: ${self.amount:,.2f}" if self.transaction_type else f"${self.amount:,.2f}"
        return "N/A"

    def set_gl_classification(self, gl_account, offset_gl_account=None):
        """Helper method to set GL classification"""
        self.gl_account = gl_account
        if offset_gl_account:
            self.offset_gl_account = offset_gl_account
        self.save()


class MonthlyDocumentBankCheckItem(models.Model):
    """
    Model to store check information extracted from check images in documents.
    """
    document = models.ForeignKey(
        MonthlyAccountingDocument,
        on_delete=models.CASCADE,
        related_name="check_items",
        verbose_name="Monthly Document"
    )
    
    page_number = models.IntegerField(
        verbose_name="Page Number",
        help_text="Page number where this check was found"
    )
    
    amount = models.CharField(
        max_length=100,
        verbose_name="Amount",
        help_text="Check amount as extracted from check image"
    )
    
    payee = models.TextField(
        verbose_name="Payee",
        null=True,
        blank=True,
        help_text="Payee name from check"
    )
    
    memo = models.TextField(
        verbose_name="Memo",
        null=True,
        blank=True,
        help_text="Memo line from check"
    )
    
    clearing_date = models.CharField(
        max_length=50,
        verbose_name="Clearing Date",
        null=True,
        blank=True,
        help_text="Date when check cleared"
    )
    
    passing_date = models.CharField(
        max_length=50,
        verbose_name="Passing Date",
        null=True,
        blank=True,
        help_text="Date when check was processed"
    )
    
    check_number = models.CharField(
        max_length=50,
        verbose_name="Check Number",
        null=True,
        blank=True,
        help_text="Check number from check image"
    )
    
    # Link to related line item if applicable
    related_line_item = models.ForeignKey(
        MonthlyDocumentBankLineItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Related Line Item",
        help_text="Line item that corresponds to this check (if found)"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )

    class Meta:
        db_table = 'monthly_document_check_item'
        verbose_name = "Monthly Document Check Item"
        verbose_name_plural = "Monthly Document Check Items"
        ordering = ['page_number', 'check_number']

    def __str__(self):
        return f"{self.document.doc_id} - Check #{self.check_number}: {self.payee} - {self.amount}"
