from django.db import models
from django.contrib.auth import get_user_model


class DimAICGLAcct(models.Model):
    """
    Django model for the dim_AIC_GL_Acct table, representing General Ledger Account information.
    """
    id = models.AutoField(
        primary_key=True,
        verbose_name="GL Account ID",
	)
    customer = models.ForeignKey(
        'user.DimAICCustomer',
        on_delete=models.CASCADE,
        verbose_name="Customer ID",
	)

    client_id = models.ForeignKey(
        'user.DimAICClient',
        on_delete=models.CASCADE,
        verbose_name="Client ID",
	)
    account_number = models.CharField(
        max_length=15,
        verbose_name="GL Account Number",
    )
    account_name = models.CharField(
        max_length=255,
        verbose_name="GL Account Name",
    )
    description = models.TextField(
        verbose_name="GL Account Description",
    )
    account_class = models.CharField(
        max_length=100,
        verbose_name="Account Class",
        help_text="e.g., Asset, Liability, Equity, Revenue, Expense"
    )
    sub_class = models.CharField(
        max_length=100,
        verbose_name="Account Sub Class",
        help_text="e.g., Cash, Fixed Assets, Current Liabilities"
    )
    account_type = models.ForeignKey(
        'DimAICAcctType',
        on_delete=models.CASCADE,
        verbose_name="Account Type ID",
        null=True,
        blank=True,
    )
    input_user = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Input User"
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
        db_table = 'dim_aic_gl_acct'
        verbose_name = "AIC GL Account"
        verbose_name_plural = "AIC GL Accounts"

    def __str__(self):
        return f"{self.account_name} ({self.account_number})"

