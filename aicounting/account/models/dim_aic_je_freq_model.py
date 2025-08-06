from django.db import models

class DimAICJEFreq(models.Model):
    """
    Django model for the dim_AIC_JE_Freq table, representing Journal Entry Frequency information.
    """
    id = models.AutoField(
        primary_key=True,
        verbose_name="JE Frequency ID",
	)
    je_freq = models.CharField(
        max_length=255,
        verbose_name="JE Frequency",
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
        db_table = 'dim_aic_je_freq'
        verbose_name = "AIC JE Frequency"
        verbose_name_plural = "AIC JE Frequencies"

    def __str__(self):
        return self.je_freq