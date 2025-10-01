import uuid
from django.db import models
from django.contrib.auth import get_user_model
from .fact_aic_monthly_accounting import FactAICMonthlyAccounting
from .dim_aic_snapshot_models import FactAICInputFileSnapshot

from aicounting.file_upload_helper import upload_to_montly_accounting_folder
User = get_user_model()


class MonthlyAccountingDocument(models.Model):
    """
    Model for documents to be uploaded for monthly accounting extraction.
    Each document corresponds to an input file snapshot type but allows for separate file uploads.
    """
    
    UPLOAD_STATUS_CHOICES = [
        ('pending', 'Pending Upload'),
        ('pre_processing', 'Pre-processing'),
        ('pre_processed', 'Pre-processed'),
        ('uploaded', 'Uploaded'),
        ('extracting', 'Extracting'),
        ('extracted', 'Extracted'),
        ('classifying', 'Classifying'),
        ('classified', 'Classified'),
        ('verified', 'Verified'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    FILE_TYPE_CHOICES = [
        ('bank_statement', 'Bank Statement'),
        ('credit_card', 'Credit Card'),
        ('sales', 'Sales'),
    ]
    
    doc_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name="Document UUID",
        help_text="Unique identifier for this document"
    )
    
    monthly_accounting = models.ForeignKey(
        FactAICMonthlyAccounting,
        on_delete=models.CASCADE,
        related_name='documents',
        verbose_name="Monthly Accounting Session"
    )
    
    input_file_snapshot = models.ForeignKey(
        FactAICInputFileSnapshot,
        on_delete=models.CASCADE,
        related_name='extraction_documents',
        verbose_name="Input File Snapshot",
        help_text="Reference to the input file snapshot this document is based on"
    )
    
    doc_type = models.CharField(
        max_length=20,
        choices=FILE_TYPE_CHOICES,
        verbose_name="Document Type",
        help_text="Type of document (same as input file type)"
    )
    
    status = models.CharField(
        max_length=20,
        choices=UPLOAD_STATUS_CHOICES,
        default='pending',
        verbose_name="Document Status"
    )
    
    file = models.FileField(
		max_length=500,

        upload_to=upload_to_montly_accounting_folder,
        null=True,
        blank=True,
        verbose_name="Uploaded File",
        help_text="The file uploaded by the user for extraction"
    )
    
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Uploaded By",
        help_text="User who uploaded the file"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At"
    )
    
    # Processing results
    control_item = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Control Totals",
        help_text="Control totals and summary information extracted from document"
    )
    
    # Pre-processed markdown metadata
    markdown_metadata = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Markdown Metadata",
        help_text="Metadata about pre-generated markdown files (page count, Azure paths, URLs)"
    )
    
    class Meta:
        db_table = 'monthly_accounting_document'
        verbose_name = "Monthly Accounting Document"
        verbose_name_plural = "Monthly Accounting Documents"
        ordering = ['-created_at']
        unique_together = ('monthly_accounting', 'input_file_snapshot')
    
    def __str__(self):
        return f"Document {self.doc_id} - {self.get_doc_type_display()} ({self.status})"
    
    @property
    def file_url(self):
        """Get the file URL if file exists"""
        return self.file.url if self.file else None
    
    def get_file_size(self):
        """Get the file size in bytes if file exists"""
        return self.file.size if self.file else None
    
    def mark_as_uploaded(self, uploaded_by_user):
        """Mark document as uploaded and set the user"""
        self.status = 'uploaded'
        self.uploaded_by = uploaded_by_user
        self.save()