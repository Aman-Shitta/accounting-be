from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

User = get_user_model()

import logging
logger = logging.getLogger(__name__)

# Import snapshot models - using lazy imports to avoid circular dependencies
def get_snapshot_models():
    from .dim_aic_snapshot_models import (
        FactAICInputFileSnapshot,
        FactAICInputFileAttributeSnapshot,
        FactAICJETemplateHeaderSnapshot,
        FactAICJETemplateAttributeSnapshot
    )
    return {
        'FactAICInputFileSnapshot': FactAICInputFileSnapshot,
        'FactAICInputFileAttributeSnapshot': FactAICInputFileAttributeSnapshot,
        'FactAICJETemplateHeaderSnapshot': FactAICJETemplateHeaderSnapshot,
        'FactAICJETemplateAttributeSnapshot': FactAICJETemplateAttributeSnapshot
    }


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
        
        # Create documents for upload workflow
        monthly_accounting.create_documents_for_upload()
        
        # Trigger prompt generation pipeline
        # monthly_accounting.trigger_prompt_generation()
        
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
            # First, get all templates with monthly frequency
            if monthly_freq:
                templates = DimAICJETemplateHeader.objects.filter(
                    client=self.client,
                    je_freq=monthly_freq
                )
                
                # Create a set of input files referenced by these templates
                relevant_input_files = set()
                for template in templates:
                    # Add all input files used by this template
                    relevant_input_files.update(template.input_files.all())
                
                # Create snapshots only for relevant input files
                for input_file in relevant_input_files:
                    self._create_input_file_snapshot(input_file)
                
                # Create template snapshots
                for template in templates:
                    self._create_template_snapshot(template)
                    
        except Exception as e:
            import os, sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)

    
    def _create_input_file_snapshot(self, input_file):
        """Create snapshot of an input file and its attributes"""
        import os
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        
        # Get snapshot models
        models_dict = get_snapshot_models()
        FactAICInputFileSnapshot = models_dict['FactAICInputFileSnapshot']
        FactAICInputFileAttributeSnapshot = models_dict['FactAICInputFileAttributeSnapshot']
        # Handle file copying if the original file exists
        snapshot_file = None
        if input_file.file:
            try:
                # Create a unique filename for the snapshot
                original_file_name = os.path.basename(input_file.file.name)
                snapshot_file_name = f"snapshot_{self.id}_{input_file.id}_{original_file_name}"
                
                # Copy the file content
                if default_storage.exists(input_file.file.name):
                    original_file = default_storage.open(input_file.file.name)
                    file_content = original_file.read()
                    original_file.close()
                    
                    # Create a ContentFile for the snapshot
                    snapshot_file = ContentFile(file_content, name=snapshot_file_name)
                else:
                    # If original file doesn't exist, log a warning
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Original file {input_file.file.name} not found for snapshot")
                    
            except Exception as e:
                # Log the error but continue with snapshot creation
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to copy file for snapshot: {str(e)}")
        
        # Create input file snapshot
        file_snapshot = FactAICInputFileSnapshot.objects.create(
            monthly_accounting=self,
            original_input_file=input_file,
            client=input_file.client,
            name=input_file.name,
            file=snapshot_file,
            file_type=input_file.file_type,
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
        with transaction.atomic():
            try:
                # Get snapshot models
                models_dict = get_snapshot_models()
                FactAICInputFileSnapshot = models_dict['FactAICInputFileSnapshot']
                FactAICInputFileAttributeSnapshot = models_dict['FactAICInputFileAttributeSnapshot']
                FactAICJETemplateHeaderSnapshot = models_dict['FactAICJETemplateHeaderSnapshot']
                FactAICJETemplateAttributeSnapshot = models_dict['FactAICJETemplateAttributeSnapshot']

                # Create template snapshot first without the input_files
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
                    description=template.description,
                    original_created_at=template.created_at,
                    original_updated_at=template.updated_at
                )
                
                # Add corresponding input file snapshots to the M2M relationship
                for input_file in template.input_files.all():
                    try:
                        input_file_snapshot = FactAICInputFileSnapshot.objects.get(
                            monthly_accounting=self,
                            original_input_file=input_file
                        )
                        # Add the snapshot to the template's input_files M2M field
                        template_snapshot.input_files.add(input_file_snapshot)
                    except FactAICInputFileSnapshot.DoesNotExist:
                        # Skip this input file if no snapshot exists
                        pass
                
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
            except Exception as e:
                import os, sys
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print(exc_type, fname, exc_tb.tb_lineno)
                template_snapshot = None
        
        return template_snapshot
    
    def create_documents_for_upload(self):
        """
        Create MonthlyAccountingDocument records for each input file snapshot
        to enable separate document upload workflow
        """
        from .monthly_accounting_document_model import MonthlyAccountingDocument
        
        models_dict = get_snapshot_models()
        FactAICInputFileSnapshot = models_dict['FactAICInputFileSnapshot']
        
        created_documents = []

        # Get all input file snapshots for this monthly accounting session
        input_file_snapshots = FactAICInputFileSnapshot.objects.filter(
            monthly_accounting=self
        )

        if input_file_snapshots.exists():

            for snapshot in input_file_snapshots:
                # Create a document for each snapshot
                document = MonthlyAccountingDocument.objects.create(
                    monthly_accounting=self,
                    input_file_snapshot=snapshot,
                    doc_type=snapshot.file_type if hasattr(snapshot, 'file_type') else 'bank_statement',
                    status='pending'
                )
                created_documents.append(document)
            
        return created_documents

