from django.db import models
import random # Added for potential future use or if custom ID generation is needed again
import string # Added for potential future use or if custom ID generation is needed again



class DimAICJETemplateHeader(models.Model):
    """
    Django model for the dim_AIC_JE_Template_Header table.
    Represents header information for Journal Entry Templates.
    """
    id = models.AutoField(
        primary_key=True,
        verbose_name="JE Template ID",
	)
    customer = models.ForeignKey(
        'user.DimAICCustomer',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending on desired behavior
        verbose_name="Customer ID",
        db_column='customer_id',
	)
    client = models.ForeignKey(
        'user.DimAICClient',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending on desired behavior
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
    je_freq= models.ForeignKey(
        'DimAICJEFreq',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending on desired behavior
        verbose_name="JE Frequency ID",
        db_column='je_freq_id',
	)
    je_type = models.ForeignKey(
        'DimAICJEType',
        on_delete=models.SET_NULL, # Or models.PROTECT, models.SET_NULL, etc., depending on desired behavior
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
    input_files = models.ManyToManyField(
        'DimAicInputFiles',
        verbose_name="Input File",
        help_text="The input file associated with this JE template"
    )
    """
    desc: 
    strictly informational fields
    to show to user.
    """
    description = models.TextField(
        null=True,
        blank=True,
        verbose_name="Description",
        help_text="Additional description or comments about the Template"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
    )


    class Meta:
        db_table = 'dim_aic_je_template_header'
        verbose_name = "AIC JE Template Header"
        verbose_name_plural = "AIC JE Template Headers"
        unique_together = ('customer', 'client', 'je_freq', 'je_name')

    def __str__(self):
        return f"Template {self.id} - {self.je_name}"
