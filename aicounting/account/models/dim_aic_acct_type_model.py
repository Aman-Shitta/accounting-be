from django.db import models

class DimAICAcctType(models.Model):
    """
    Django model for the dim_aic_Acct_Type table, representing Account Type information.
    """
    account_type_id = models.AutoField(
        primary_key=True,
        verbose_name="Account Type ID",
    )
    account_type = models.CharField(
        max_length=255,
        verbose_name="Account Type",
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
        db_table = 'dim_aic_acct_type'
        verbose_name = "AIC Account Type"
        verbose_name_plural = "AIC Account Types"

    def __str__(self):
        return self.account_type