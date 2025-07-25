# Third-party imports
from django.db import models



class DimAICJETemplateGL(models.Model):
    """
    Django model for the dim_AIC_JE_Template_GL table.
    Represents General Ledger information for Journal Entry Templates.
    """
    je_template_gl_id = models.AutoField( # Primary Key
        primary_key=True,
        verbose_name="GL Account Type ID",
	)
    je_template_id = models.ForeignKey(
        'DimAICJETemplateHeader',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending on desired behavior
        verbose_name="JE Template ID",
	)
    gl_acct_id = models.ForeignKey( # Foreign Key
        'DimAICGLAcct',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending
        verbose_name="GL Account ID",
	)
    acct_type_id = models.ForeignKey( # foreign Key
        'DimAICAcctType',
        on_delete=models.CASCADE, # Or models.PROTECT, models.SET_NULL, etc., depending
        verbose_name="GL Account Type ID",
	)
    
    offset_gl_acct_id = models.ForeignKey( # Foreign Key
        'DimAICGLAcct',
        on_delete=models.CASCADE,
        verbose_name="Offset GL Account ID",
        related_name='je_gl_templates'
	)

    

    class Meta:
        db_table = 'dim_aic_je_template_gl'
        verbose_name = "AIC JE Template GL"
        verbose_name_plural = "AIC JE Template GLs"

    def __str__(self):
        return f"JE Template GL for Template {self.je_template_gl_id}"

