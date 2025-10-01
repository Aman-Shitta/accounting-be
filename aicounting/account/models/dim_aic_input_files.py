from django.db import models
from django.contrib.auth import get_user_model
from aicounting.file_upload_helper import upload_to_input_files_folder

User = get_user_model()


class DimAicInputFiles(models.Model):
    """
    Model for managing input files for a client
    """
    
    FILE_TYPE_CHOICES = [
        ('bank_statement', 'Bank Statement'),
        ('credit_card', 'Credit Card'),
        ('sales', 'Sales'),
    ]
    
    id = models.AutoField(primary_key=True, verbose_name="Input File ID")
    
    client = models.ForeignKey(
        'user.DimAICClient',
        on_delete=models.CASCADE,
        verbose_name="Client",
        related_name="input_files"
    )
    
    name = models.CharField(
        max_length=255,
        verbose_name="Name",
        unique=True,
    )
    
    file_type = models.CharField(
        max_length=20,
        choices=FILE_TYPE_CHOICES,
        verbose_name="File Type",
        help_text="Type of the input file"
    )
    
    file = models.FileField(
		max_length=500,

        upload_to=upload_to_input_files_folder,
        verbose_name="File",
        help_text="Upload the input file"
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
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At"
    )
    
    class Meta:
        db_table = 'dim_aic_input_files'
        verbose_name = "Input File"
        verbose_name_plural = "Input Files"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.get_file_type_display()}"


class DimAicInputFileAttributes(models.Model):
    """
    Model for managing attributes related to input files
    """
    
    TYPE_CHOICES = [
        ('credit', 'Credit'),
        ('debit', 'Debit'),
    ]
    
    id = models.AutoField(primary_key=True, verbose_name="Attribute ID")
    
    input_file = models.ForeignKey(
        DimAicInputFiles,
        on_delete=models.CASCADE,
        verbose_name="Input File",
        related_name="attributes"
    )
    
    name = models.CharField(
        max_length=255,
        verbose_name="Attribute Name",
        help_text="Name of the attribute"
    )
    
    gl_account = models.ForeignKey(
        'DimAICGLAcct',
        on_delete=models.CASCADE,
        verbose_name="GL Account",
        related_name="input_file_attributes",
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
        related_name="offset_input_file_attributes",
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
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At"
    )
    
    class Meta:
        db_table = 'dim_aic_input_file_attributes'
        verbose_name = "Input File Attribute"
        verbose_name_plural = "Input File Attributes"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.input_file.name}"
