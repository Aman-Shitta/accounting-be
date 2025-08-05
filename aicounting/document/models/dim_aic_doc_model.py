# System imports
import uuid

# Third-party imports
from django.contrib.auth import get_user_model
from django.db import models
from aicounting.model_file_upload_helper import upload_to_documents_folder

class DimAICDocument(models.Model):
    """
    Django model for the dim_AIC_Doc table, representing document information.
    """
    doc_id = models.CharField(
        max_length=72,
        default=uuid.uuid4,
        verbose_name="UUID",
	)
    doc_typ = models.CharField(
        max_length=50,
        verbose_name="Document Type",
	)
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
	)
    file_format = models.CharField(
        max_length=8,
        verbose_name="File Format",
	)
    upload_stat = models.CharField(
        max_length=25,
        verbose_name="Upload Status",
	)

    input_user = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Input User"
    )

    file = models.FileField(
        upload_to=upload_to_documents_folder,
        verbose_name="Document File",
        help_text="File stored in Azure Blob Storage",
        max_length=500  # Increased from default 100 to accommodate Azure paths
    )
    control_item = models.JSONField(null=True, blank=True)

    class Meta:
        # Define the table name in the database
        db_table = 'dim_aic_doc'
        # Set the verbose name for the model, used in the Django admin interface
        verbose_name = "AIC Document"
        verbose_name_plural = "AIC Documents"

    def __str__(self):
        # String representation of the object, useful for the Django admin
        return f"Document ID: {self.doc_id} - Type: {self.doc_typ}"
    
    def get_azure_file_path(self):
        """
        Get the full Azure blob path for this document
        Structure: documents/doc_type/doc_id/filename
        """
        if not self.file:
            return ""
        
        # Get just the filename from the stored path
        filename = self.file.name.split('/')[-1] if '/' in self.file.name else self.file.name
        return f"documents/{self.doc_typ}/{self.doc_id}/{filename}"
    
    def get_secure_url(self, expire_minutes=10):
        """
        Get a secure temporary URL for the document file with 10-minute expiry
        """
        if not self.file:
            return ""
        
        # Use the full Azure path for generating the SAS URL
        azure_path = self.get_azure_file_path()
        
        # Generate Azure SAS URL with 10-minute expiry (no permission checks)
        from django.core.files.storage import default_storage
        if hasattr(default_storage, 'url'):
            return default_storage.url(azure_path, expire_minutes=expire_minutes)
        return ""


class FactAICDocKeyItem(models.Model):
    """
    Fact table to store extracted key-value pairs from a document.
    """
    doc = models.ForeignKey(
        DimAICDocument,
        on_delete=models.CASCADE,
        related_name="key_items"
    )
    line_number = models.IntegerField(
        verbose_name="Line Number",
	)
    page_number = models.IntegerField(
        verbose_name="Page Number",
	)
    key = models.CharField(
        max_length=100,
        verbose_name="Key",
	)
    value = models.CharField(
        max_length=1000,
        verbose_name="Value",
        null=True,
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
        db_table = 'fact_aic_doc_key_item'
        verbose_name = "AIC Document Key Item"
        verbose_name_plural = "AIC Document Key Items"


class FactAICDocLine(models.Model):
    """
    Fact table for each line item row extracted from a document (1 row = 1 item).
    """
    doc = models.ForeignKey(
        DimAICDocument,
        on_delete=models.CASCADE,
        related_name="line_rows"
    )
    page_number = models.IntegerField(
        verbose_name="Page Number",
	)
    line_number = models.IntegerField(
        verbose_name="Line Number",
	)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fact_aic_doc_line'
        verbose_name = "AIC Document Line Row"
        verbose_name_plural = "AIC Document Line Rows"


class FactAICDocLineItem(models.Model):
    """
    Fact table to store key-value columns for each line item row.
    """
    line = models.ForeignKey(
        FactAICDocLine,
        on_delete=models.CASCADE,
        related_name="values"
    )
    key = models.CharField(
        max_length=100,
        verbose_name="Column Name"
    )
    value = models.TextField(
        verbose_name="Value",
        null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fact_aic_doc_line_value'
        verbose_name = "AIC Document Line Item Value"
        verbose_name_plural = "AIC Document Line Item Values"


class FactAICDocCheckItem(models.Model):
    """
    Fact table to store extracted check information from a document.
    """
    doc = models.ForeignKey(
        DimAICDocument,
        on_delete=models.CASCADE,
        related_name="check_items"
    )
    amount = models.CharField(
        max_length=100,
        verbose_name="Amount"
    )
    payee = models.TextField(
        verbose_name="Payee",
        null=True,
        blank=True
    )
    memo = models.TextField(
        verbose_name="Memo",
        null=True,
        blank=True
    )
    clearing_date = models.CharField(
        max_length=50,
        verbose_name="Clearing Date",
        null=True,
        blank=True
    )
    passing_date = models.CharField(
        max_length=50,
        verbose_name="Passing Date",
        null=True,
        blank=True
    )
    check_number = models.CharField(
        max_length=50,
        verbose_name="Check Number",
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fact_aic_doc_check_items'
        verbose_name = "AIC Document Check Item"
        verbose_name_plural = "AIC Document Check Items"