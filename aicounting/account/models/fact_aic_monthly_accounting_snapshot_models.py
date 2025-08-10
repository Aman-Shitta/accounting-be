from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

User = get_user_model()


class FactAICMonthlyAccounting(models.Model):
    """
    Model for managing monthly accounting sessions for a client.
    """
    
    STATUS_CHOICES = [
        ('initiated', 'Initiated'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.AutoField(primary_key=True, verbose_name="Monthly Accounting ID")
    
    client = models.ForeignKey(
        'user.DimAICClient',
        on_delete=models.CASCADE,
        verbose_name="Client",
        related_name="monthly_accounting"
    )
    
    month = models.IntegerField(
        verbose_name="Month",
        help_text="Month (1-12)"
    )
    
    year = models.IntegerField(
        verbose_name="Year",
        help_text="Year (e.g., 2025)"
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='initiated',
        verbose_name="Status"
    )
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Created By",
        help_text="User who initiated this accounting session"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )
    
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Completed At"
    )
    
    class Meta:
        db_table = 'fact_aic_monthly_accounting'
        verbose_name = "Monthly Accounting"
        verbose_name_plural = "Monthly Accounting Sessions"
        unique_together = ('client', 'month', 'year')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.client.client_name} - {self.get_month_name()} {self.year} ({self.status})"
    
    def get_month_name(self):
        """Get the full month name"""
        month_names = {
            1: 'January', 2: 'February', 3: 'March', 4: 'April',
            5: 'May', 6: 'June', 7: 'July', 8: 'August',
            9: 'September', 10: 'October', 11: 'November', 12: 'December'
        }
        return month_names.get(self.month, 'Unknown')
    
    def clean(self):
        """Validate that accounting for this client/month/year doesn't already exist"""
        if FactAICMonthlyAccounting.objects.filter(
            client=self.client,
            month=self.month,
            year=self.year
        ).exclude(id=self.id).exists():
            raise ValidationError(
                f"Accounting for {self.get_month_name()} {self.year} already exists for this client."
            )
    
    @classmethod
    def create_monthly_accounting_with_snapshots(cls, client, month, year, created_by):
        """
        Create a new monthly accounting session with snapshots of current configuration
        """
        # Create the monthly accounting session
        monthly_accounting = cls.objects.create(
            client=client,
            month=month,
            year=year,
            created_by=created_by
        )

        
        # Create snapshots
        monthly_accounting.create_snapshots()
        
        return monthly_accounting
    
    def create_snapshots(self):
        """Create snapshots of current templates and input files configuration"""
        from .dim_aic_je_template_header_model import DimAICJETemplateHeader
        from .dim_aic_input_files import DimAicInputFiles
        from .dim_aic_je_freq_model import DimAICJEFreq
        
        # Get monthly frequency templates
        try:
            monthly_freq = DimAICJEFreq.objects.get(je_freq__icontains='monthly')
        except DimAICJEFreq.DoesNotExist:
            monthly_freq = None
        
        try:
            # Create input files snapshots
            input_files = DimAicInputFiles.objects.filter(client=self.client)
            for input_file in input_files:
                self._create_input_file_snapshot(input_file)
            
            # Create template snapshots (only monthly frequency)
            if monthly_freq:
                templates = DimAICJETemplateHeader.objects.filter(
                    client=self.client,
                    je_freq=monthly_freq
                )
                for template in templates:
                    self._create_template_snapshot(template)
        except Exception as e:
            import os, sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)
    
    def _create_input_file_snapshot(self, input_file):
        """Create snapshot of an input file and its attributes"""
        # Create input file snapshot
        file_snapshot = FactAICInputFileSnapshot.objects.create(
            monthly_accounting=self,
            original_input_file=input_file,
            client=input_file.client,
            name=input_file.name,
            file_type=input_file.file_type,
            file=input_file.file.name if input_file.file else '',
            description=input_file.description,
            input_user=input_file.input_user,
            original_created_at=input_file.created_at,
            original_updated_at=input_file.updated_at
        )
        
        # Create attribute snapshots
        for attribute in input_file.attributes.all():
            FactAICInputFileAttributeSnapshot.objects.create(
                input_file_snapshot=file_snapshot,
                original_attribute=attribute,
                name=attribute.name,
                gl_account=attribute.gl_account,
                type=attribute.type,
                offset_gl_account=attribute.offset_gl_account,
                input_user=attribute.input_user,
                comments=attribute.comments,
                original_created_at=attribute.created_at,
                original_updated_at=attribute.updated_at
            )
        
        return file_snapshot
    
    def _create_template_snapshot(self, template):
        """Create snapshot of a JE template and its attributes"""
        # Find the corresponding input file snapshot if exists
        input_file_snapshot = None
        if template.input_file:
            try:
                input_file_snapshot = FactAICInputFileSnapshot.objects.get(
                    monthly_accounting=self,
                    original_input_file=template.input_file
                )
            except FactAICInputFileSnapshot.DoesNotExist:
                pass
        
        # Create template snapshot
        template_snapshot = FactAICJETemplateHeaderSnapshot.objects.create(
            monthly_accounting=self,
            original_template=template,
            customer=template.customer,
            client=template.client,
            je_name=template.je_name,
            je_refrence=template.je_refrence,
            je_freq=template.je_freq,
            je_type=template.je_type,
            is_object=template.is_object,
            input_file=input_file_snapshot,
            description=template.description,
            original_created_at=template.created_at,
            original_updated_at=template.updated_at
        )
        
        # Create template attribute snapshots
        for attribute in template.template_attributes.all():
            # Find corresponding input file attribute snapshot if exists
            input_file_attribute_snapshot = None
            if attribute.input_file_attribute:
                try:
                    # Find the input file snapshot first
                    input_file_snap = FactAICInputFileSnapshot.objects.get(
                        monthly_accounting=self,
                        original_input_file=attribute.input_file_attribute.input_file
                    )
                    # Find the attribute snapshot
                    input_file_attribute_snapshot = FactAICInputFileAttributeSnapshot.objects.get(
                        input_file_snapshot=input_file_snap,
                        original_attribute=attribute.input_file_attribute
                    )
                except (FactAICInputFileSnapshot.DoesNotExist, FactAICInputFileAttributeSnapshot.DoesNotExist):
                    pass
            
            FactAICJETemplateAttributeSnapshot.objects.create(
                je_template_snapshot=template_snapshot,
                original_attribute=attribute,
                input_file_attribute=input_file_attribute_snapshot,
                gl_account=attribute.gl_account,
                debit=attribute.debit,
                credit=attribute.credit,
                attribute_name=attribute.attribute_name,
                input_user=attribute.input_user,
                original_created_at=attribute.created_at,
                original_updated_at=attribute.updated_at
            )
        
        return template_snapshot


class FactAICInputFileSnapshot(models.Model):
    """
    Snapshot model that mirrors DimAicInputFiles exactly
    """
    
    FILE_TYPE_CHOICES = [
        ('bank_statement', 'Bank Statement'),
        ('credit_card', 'Credit Card'),
        ('sales', 'Sales'),
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
    
    file = models.CharField(
        max_length=500,
        verbose_name="File Path",
        help_text="Path to the input file at time of snapshot"
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
    
    is_object = models.BooleanField(
        default=False,
        verbose_name="Is Object",
        help_text="Indicates if the template is an object template or not"
    )
    
    input_file = models.ForeignKey(
        FactAICInputFileSnapshot,  # Reference to snapshot instead of original
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="Input File Snapshot",
        db_column='input_file_id',
        help_text="The input file snapshot associated with this JE template"
    )
    
    description = models.TextField(
        null=True,
        blank=True,
        verbose_name="Description",
        help_text="Additional description or comments about the Template"
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
