from django.db import models
import random # Added for potential future use or if custom ID generation is needed again
import string # Added for potential future use or if custom ID generation is needed again




class DimAICTemplateDoc(models.Model):
    """
    Django model for the dim_AIC_Template_Doc table.
    Represents document information associated with templates.
    """
    je_template_gl_acct_id = models.ForeignKey(
        'DimAICGLAcct', 
        to_field='gl_acct_id',
        on_delete=models.CASCADE,
        verbose_name="JE Temaplate GL Account ID",
	)
    doc_id = models.ForeignKey(
        'document.DimAICDocument', 
        on_delete=models.CASCADE,
        verbose_name="Document ID",
	)
    doc_comments = models.TextField(
        verbose_name="Document Comments",
	)
    doc_ai_prompt = models.TextField(
        verbose_name="Document AI Prompt",
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
        db_table = 'dim_aic_template_doc'
        verbose_name = "AIC Template Document"
        verbose_name_plural = "AIC Template Documents"

    def __str__(self):
        return f"Document {self.doc_id}"