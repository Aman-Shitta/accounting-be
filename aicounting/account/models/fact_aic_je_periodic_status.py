from django.db import models



class FactAICJEMonthlyStat(models.Model):
    """
    Django model for the fact_AIC_JE_Trans table.
    Represents Journal Entry Transaction facts.
    """
    je_trans_id = models.AutoField(
        primary_key=True,
        verbose_name="JE Transaction ID",
    )
    je_template_id = models.ForeignKey(
        'DimAICJETemplateHeader',
        on_delete=models.CASCADE,
        verbose_name="JE Template ID",
    )
    je_mth = models.IntegerField(
        verbose_name="JE Month",
    )
    je_yr = models.IntegerField(
        verbose_name="JE Year",
    )
    is_processed = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
    )
    

    class Meta:
        db_table = 'fact_aic_je_monthly_stat'
        verbose_name = "AIC JE Transaction"
        verbose_name_plural = "AIC JE Transactions"

    def __str__(self):
        return f"JE Trans {self.je_trans_id} for {self.je_mth}/{self.je_yr}"
