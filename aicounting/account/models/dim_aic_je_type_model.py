from django.db import models

class DimAICJEType(models.Model):
    """
    Django model for the dim_AIC_JE_Type table, representing Journal Entry Type information.
    """
    id = models.AutoField(
        primary_key=True,
        verbose_name="JE Type ID",
	)
    je_type = models.CharField(
        max_length=255,
        verbose_name="JE Type",
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
        db_table = 'dim_aic_je_type'
        verbose_name = "AIC JE Type"
        verbose_name_plural = "AIC JE Types"

    def __str__(self):
        return self.je_type