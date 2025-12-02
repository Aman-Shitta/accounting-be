from django.db import models
from django.contrib.auth import get_user_model
from .fact_aic_monthly_accounting import FactAICMonthlyAccounting

User = get_user_model()

from aicounting.file_upload_helper import upload_to_je_export_folder, upload_to_monthly_accounting_snapshot_folder

class FactAICInputFileSnapshot(models.Model):
    """
    Snapshot model that mirrors DimAicInputFiles exactly
    """
    
    FILE_TYPE_CHOICES = [
        ('bank_statement', 'Bank Statement'),
        ('credit_card', 'Credit Card'),
        ('sales', 'Sales'),
        ('payroll', 'Payroll'),
        ('misc', 'Misc'),
    ]
    
    id = models.AutoField(primary_key=True, verbose_name="Input File Snapshot ID")
    
    # Link to monthly accounting session
    monthly_accounting = models.ForeignKey(
        FactAICMonthlyAccounting,
        on_delete=models.CASCADE,
        related_name='input_file_snapshots',
        verbose_name="Monthly Accounting"
    )
    
    # Reference to original input file
    original_input_file = models.ForeignKey(
        'DimAicInputFiles',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Original Input File"
    )
    
    # Fields that mirror DimAicInputFiles exactly
    client = models.ForeignKey(
        'user.DimAICClient',
        on_delete=models.CASCADE,
        verbose_name="Client",
        related_name="input_file_snapshots"
    )
    
    name = models.CharField(
        max_length=255,
        verbose_name="Name",
    )
    
    file_type = models.CharField(
        max_length=20,
        choices=FILE_TYPE_CHOICES,
        verbose_name="File Type",
        help_text="Type of the input file"
    )
    
    file = models.FileField(
        upload_to=upload_to_monthly_accounting_snapshot_folder,
        null=True,
        blank=True,
        verbose_name="File",
        help_text="Snapshot copy of the input file",
        max_length=500
    )
    
    description = models.TextField(
        null=True,
        blank=True,
        verbose_name="Description",
        help_text="Additional description or comments about the input file"
    )
    
    input_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Input User",
        help_text="User who uploaded this file"
    )
    
    # Original timestamps
    original_created_at = models.DateTimeField(
        verbose_name="Original Created At"
    )
    
    original_updated_at = models.DateTimeField(
        verbose_name="Original Updated At"
    )
    
    # Snapshot timestamp
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Snapshot Created At"
    )
    
    class Meta:
        db_table = 'fact_aic_input_file_snapshot'
        verbose_name = "Input File Snapshot"
        verbose_name_plural = "Input File Snapshots"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Snapshot: {self.name} - {self.get_file_type_display()}"
    
    @property
    def file_url(self):
        """Get the file URL if file exists"""
        return self.file.url if self.file else None
    
    def get_file_size(self):
        """Get the file size in bytes if file exists"""
        return self.file.size if self.file else None


class FactAICInputFileAttributeSnapshot(models.Model):
    """
    Snapshot model that mirrors DimAicInputFileAttributes exactly
    """
    
    TYPE_CHOICES = [
        ('credit', 'Credit'),
        ('debit', 'Debit'),
    ]
    
    id = models.AutoField(primary_key=True, verbose_name="Attribute Snapshot ID")
    
    # Link to input file snapshot
    input_file_snapshot = models.ForeignKey(
        FactAICInputFileSnapshot,
        on_delete=models.CASCADE,
        verbose_name="Input File Snapshot",
        related_name="attribute_snapshots"
    )
    
    # Reference to original attribute
    original_attribute = models.ForeignKey(
        'DimAicInputFileAttributes',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Original Attribute"
    )
    
    # Fields that mirror DimAicInputFileAttributes exactly
    name = models.CharField(
        max_length=255,
        verbose_name="Attribute Name",
        help_text="Name of the attribute"
    )
    
    gl_account = models.ForeignKey(
        'DimAICGLAcct',
        on_delete=models.CASCADE,
        verbose_name="GL Account",
        related_name="input_file_attribute_snapshots",
        null=True,
        blank=True,
    )
    
    type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        verbose_name="Type",
        help_text="Credit or Debit type"
    )
    
    offset_gl_account = models.ForeignKey(
        'DimAICGLAcct',
        on_delete=models.CASCADE,
        verbose_name="Offset GL Account",
        related_name="offset_input_file_attribute_snapshots",
        null=True,
        blank=True,
    )
    
    input_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Input User",
        help_text="User who created this attribute"
    )
    
    comments = models.TextField(
        blank=True,
        null=True,
        verbose_name="Comments",
        help_text="Additional comments or notes"
    )
    
    # Original timestamps
    original_created_at = models.DateTimeField(
        verbose_name="Original Created At"
    )
    
    original_updated_at = models.DateTimeField(
        verbose_name="Original Updated At"
    )
    
    # Snapshot timestamp
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Snapshot Created At"
    )
    
    class Meta:
        db_table = 'fact_aic_input_file_attribute_snapshot'
        verbose_name = "Input File Attribute Snapshot"
        verbose_name_plural = "Input File Attribute Snapshots"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Snapshot: {self.name} - {self.input_file_snapshot.name}"


class FactAICJETemplateHeaderSnapshot(models.Model):
    """
    Snapshot model that mirrors DimAICJETemplateHeader exactly
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('failed', 'Failed'),
    ]

    id = models.AutoField(primary_key=True, verbose_name="JE Template Snapshot ID")
    
    # Link to monthly accounting session
    monthly_accounting = models.ForeignKey(
        FactAICMonthlyAccounting,
        on_delete=models.CASCADE,
        related_name='je_template_snapshots',
        verbose_name="Monthly Accounting"
    )
    
    # Reference to original template
    original_template = models.ForeignKey(
        'DimAICJETemplateHeader',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Original Template"
    )
    
    # Fields that mirror DimAICJETemplateHeader exactly
    customer = models.ForeignKey(
        'user.DimAICCustomer',
        on_delete=models.CASCADE,
        verbose_name="Customer ID",
        db_column='customer_id',
    )
    
    client = models.ForeignKey(
        'user.DimAICClient',
        on_delete=models.CASCADE,
        verbose_name="Client ID",
        db_column='client_id',
    )
    
    je_name = models.CharField(
        max_length=500,
        verbose_name="JE Name",
    )
    
    je_refrence = models.CharField(
        max_length=255,
        verbose_name="JE Reference",
    )
    
    je_freq = models.ForeignKey(
        'DimAICJEFreq',
        on_delete=models.CASCADE,
        verbose_name="JE Frequency ID",
        db_column='je_freq_id',
    )
    
    je_type = models.ForeignKey(
        'DimAICJEType',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="JE Type ID",
        db_column='je_type_id',
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="JE Template Status",
        null=True,
        blank=True
    )
    
    is_object = models.BooleanField(
        default=False,
        verbose_name="Is Object",
        help_text="Indicates if the template is an object template or not"
    )
    
    input_files = models.ManyToManyField(
        FactAICInputFileSnapshot,
        verbose_name="Input File Snapshot",
        help_text="The input file snapshot associated with this JE template"
    )
    
    description = models.TextField(
        null=True,
        blank=True,
        verbose_name="Description",
        help_text="Additional description or comments about the Template"
    )

    je_export_file = models.FileField(
		max_length=500,

        upload_to=upload_to_je_export_folder,
        null=True,
        blank=True,
        verbose_name="JE Export File",
        help_text="Exported JE template file (e.g., CSV)"
    )
    
    # Original timestamps
    original_created_at = models.DateTimeField(
        verbose_name="Original Created At",
    )
    
    original_updated_at = models.DateTimeField(
        verbose_name="Original Updated At",
    )
    
    # Snapshot timestamp
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Snapshot Created At"
    )
    
    class Meta:
        db_table = 'fact_aic_je_template_header_snapshot'
        verbose_name = "JE Template Header Snapshot"
        verbose_name_plural = "JE Template Header Snapshots"
    
    def __str__(self):
        return f"Snapshot: Template {self.id} - {self.je_name}"


class FactAICJETemplateAttributeSnapshot(models.Model):
    """
    Snapshot model that mirrors DimAICJETemplateAttribute exactly
    """
    
    id = models.AutoField(primary_key=True, verbose_name="JE Template Attribute Snapshot ID")
    
    # Link to template snapshot
    je_template_snapshot = models.ForeignKey(
        FactAICJETemplateHeaderSnapshot,
        on_delete=models.CASCADE,
        verbose_name="JE Template Snapshot",
        related_name='attribute_snapshots'
    )
    
    # Reference to original attribute
    original_attribute = models.ForeignKey(
        'DimAICJETemplateAttribute',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Original Template Attribute"
    )
    
    # Fields that mirror DimAICJETemplateAttribute exactly
    input_file_attribute = models.ForeignKey(
        FactAICInputFileAttributeSnapshot,  # Reference to snapshot instead of original
        on_delete=models.CASCADE,
        verbose_name="Input File Attribute Snapshot",
        related_name='je_template_snapshots',
        null=True,
        blank=True,
        help_text="For object templates - the attribute snapshot from input file"
    )
    
    gl_account = models.ForeignKey(
        'DimAICGLAcct',
        on_delete=models.CASCADE,
        verbose_name="GL Account",
        related_name='je_template_attribute_snapshots',
        null=True,
        blank=True,
        help_text="For non-object templates - the GL account"
    )
    
    debit = models.CharField(
        max_length=255,
        verbose_name="Debit",
        null=True,
        blank=True,
        help_text="Debit value: can be null, number as string, attribute_id, or 'manual'"
    )
    
    credit = models.CharField(
        max_length=255,
        verbose_name="Credit",
        null=True,
        blank=True,
        help_text="Credit value: can be null, number as string, attribute_id, or 'manual'"
    )
    
    attribute_name = models.CharField(
        max_length=255,
        verbose_name="Attribute Name",
        null=True,
        blank=True,
        help_text="Name of the attribute when referenced by ID"
    )
    
    input_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Input User"
    )
    
    # Original timestamps
    original_created_at = models.DateTimeField(
        verbose_name="Original Created At",
    )
    
    original_updated_at = models.DateTimeField(
        verbose_name="Original Updated At",
    )
    
    # Snapshot timestamp
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Snapshot Created At"
    )
    
    class Meta:
        db_table = 'fact_aic_je_template_attribute_snapshot'
        verbose_name = "JE Template Attribute Snapshot"
        verbose_name_plural = "JE Template Attribute Snapshots"
    
    def __str__(self):
        if self.input_file_attribute:
            return f"Snapshot: Template {self.je_template_snapshot.je_name} - Attribute {self.input_file_attribute.name}"
        else:
            return f"Snapshot: Template {self.je_template_snapshot.je_name} - GL Account {self.gl_account.account_name if self.gl_account else 'Unknown'}"

