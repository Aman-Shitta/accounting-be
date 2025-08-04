from django.db import models


class FactAICJETransBank(models.Model):
    """
    Django model for the fact_JE_Trans_Bank table.
    Represents bank-related Journal Entry Transactions.
    """
    je_trans_bank_id = models.AutoField( # Primary Key
        primary_key=True,
        verbose_name="JE Transaction Bank ID",
	)
    je_template_id = models.ForeignKey(
        'DimAICJETemplateHeader',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending on desired behavior
        db_column='JE_Template_Id', # Specify the actual column name in the database if it differs from the field name
        verbose_name="JE Template ID",
	)
    post_dt = models.DateTimeField(
        verbose_name="Posting Date",
	)
    trans_dt = models.DateTimeField(
        verbose_name="Transaction Date",
	)
    dscr = models.CharField(
        max_length=500,
        verbose_name="Description",
	)
    gl_acct_id = models.ForeignKey(
        'DimAICGLAcct',
        on_delete=models.CASCADE,
        verbose_name="GL Account ID",
        related_name="je_transactions"
    )

    offset_gl_acct_id = models.ForeignKey(
        'DimAICGLAcct',
        on_delete=models.CASCADE,
        verbose_name="Offset GL Account ID",
        related_name="je_offset_transactions"
    )

    amt = models.DecimalField(
        max_digits=10, decimal_places=2, # Assuming typical currency/amount precision
        verbose_name="Amount",
	)
    class_conf_score = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        verbose_name="Category Classification Confidence Score",
	)
    verified = models.BooleanField(
        verbose_name="Verified",
        default=False, 
	)
    je_trans_type = models.CharField(
        max_length=80,
        verbose_name="JE Transaction Type",
        choices=[
            ("debit", "debit"), 
            ("credit", 'credit'),
        ]
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
        db_table = 'fact_je_trans_bank'
        verbose_name = "JE Transaction Bank"
        verbose_name_plural = "JE Transactions Bank"

    def __str__(self):
        return f"Bank Trans {self.je_trans_bank_id} - {self.dscr}"
