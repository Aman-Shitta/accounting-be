from django.db import models
import random # Added for potential future use or if custom ID generation is needed again
import string # Added for potential future use or if custom ID generation is needed again


class FactJETransOther(models.Model):
    """
    Django model for the fact_JE_Trans_Other table.
    Represents other Journal Entry Transactions.
    """
    je_trans_id = models.AutoField( # Primary Key
        primary_key=True,
        verbose_name="JE Transaction ID",
	)
    gl_acct_id = models.ForeignKey(
        'DimAICGLAcct', 
        on_delete=models.CASCADE, # Adjust as necessary for your application logic
        verbose_name="GL Account ID",
	)
    offset_gl_acct_id = models.ForeignKey(
        'DimAICGLAcct', 
        to_field='gl_acct_id',
        on_delete=models.CASCADE,
        related_name='je_trans_offset_accounts',
        verbose_name="Offset GL Account ID",
	)
    amt = models.DecimalField(
        max_digits=10, decimal_places=2, # Assuming typical currency/amount precision
        verbose_name="Amount",
	)
    doc_id = models.ForeignKey(
        'document.DimAICDocument',
        on_delete=models.CASCADE, # Adjust as necessary for your application logic
        verbose_name="Document ID",
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
        db_table = 'fact_je_trans_other'
        verbose_name = "JE Transaction Other"
        verbose_name_plural = "JE Transactions Other"

    def __str__(self):
        return f"Other JE Trans {self.je_trans_id}"


