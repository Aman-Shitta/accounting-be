from django.db import models

# Create your models here.

class DimAICDocument(models.Model):
    """
    Django model for the dim_AIC_Doc table, representing document information.
    """
    doc_id = models.CharField(
        verbose_name="UUID",
        help_text="Unique identifier for each document"
    )
    doc_typ = models.CharField(
        max_length=50,
        verbose_name="Document Type",
        help_text="Type of document (template, JE, sales sheet etc.)"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
        help_text="Creation date"
    )
    file_format = models.CharField(
        max_length=8,
        verbose_name="File Format",
        help_text="Format of file"
    )
    upload_stat = models.CharField(
        max_length=25,
        verbose_name="Upload Status",
        help_text="Status of upload (success, error, etc.)"
    )

    input_user = models.IntegerField(
        # FK with the user table
        verbose_name="Input User",
        help_text="User ID of the user that uploaded the document."
    )
    file_loc = models.CharField(
        max_length=1000,
        verbose_name="File Location",
        help_text="Hard location of file"
    )

    class Meta:
        # Define the table name in the database
        db_table = 'dim_AIC_Doc'
        # Set the verbose name for the model, used in the Django admin interface
        verbose_name = "AIC Document"
        verbose_name_plural = "AIC Documents"

    def __str__(self):
        # String representation of the object, useful for the Django admin
        return f"Document ID: {self.doc_id} - Type: {self.doc_typ}"


class FactAICDocKeyItem(models.Model):
    """
    Fact table to store extracted key-value pairs from a document.
    """
    doc = models.ForeignKey(
        DimAICDocument,
        on_delete=models.CASCADE,
        related_name="key_items"
    )
    page_number = models.IntegerField(
        verbose_name="Page Number",
        help_text="Page number where the key-value was extracted from"
    )
    key = models.CharField(
        max_length=100,
        verbose_name="Key",
        help_text="Extracted key from the document"
    )
    value = models.CharField(
        max_length=1000,
        verbose_name="Value",
        help_text="Value corresponding to the extracted key"
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
    line_number = models.IntegerField(
        verbose_name="Line Number",
        help_text="Sequential line item number"
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
    page_number = models.IntegerField(
        verbose_name="Page Number",
        help_text="Page number where this line item appears"
    )
    key = models.CharField(
        max_length=100,
        verbose_name="Column Name"
    )
    value = models.TextField(
        verbose_name="Value"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fact_aic_doc_line_value'
        verbose_name = "AIC Document Line Item Value"
        verbose_name_plural = "AIC Document Line Item Values"
