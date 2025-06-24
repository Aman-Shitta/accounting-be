from django.db import models
import random # Added for potential future use or if custom ID generation is needed again
import string # Added for potential future use or if custom ID generation is needed again



class DimAICJETemplateHeader(models.Model):
    """
    Django model for the dim_AIC_JE_Template_Header table.
    Represents header information for Journal Entry Templates.
    """
    je_template_id = models.AutoField(
        primary_key=True,
        verbose_name="JE Template ID",
	)
    cust_id = models.ForeignKey(
        'user.DimAICCustomer',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending on desired behavior
        verbose_name="Customer ID",
	)
    client_id = models.ForeignKey(
        'user.DimAICClient',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending on desired behavior
        verbose_name="Client ID",
	)
    je_name = models.CharField(
        max_length=500,
        verbose_name="JE Name",
	)
    je_ref = models.CharField(
        max_length=255,
        verbose_name="JE Reference",
	)
    je_freq_id = models.ForeignKey(
        'DimAICJEFreq',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending on desired behavior
        verbose_name="JE Frequency ID",
	)
    je_type_id = models.ForeignKey(
        'DimAICJEType',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending on desired behavior
        verbose_name="JE Type ID",
	)


    class Meta:
        db_table = 'dim_AIC_JE_Template_Header'
        verbose_name = "AIC JE Template Header"
        verbose_name_plural = "AIC JE Template Headers"

    def __str__(self):
        return f"Template {self.je_template_id} - {self.je_name}"

