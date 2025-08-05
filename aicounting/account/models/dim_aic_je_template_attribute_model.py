# Third-party imports
from django.db import models
from django.contrib.auth import get_user_model


class DimAICJETemplateAttribute(models.Model):
    """
    Django model to link JE Templates with Input File Attributes.
    This represents which input file attributes are used in a specific JE template.
    """
    id = models.AutoField(
        primary_key=True,
        verbose_name="JE Template Attribute ID",
    )
    je_template_id = models.ForeignKey(
        'DimAICJETemplateHeader',
        on_delete=models.CASCADE,
        verbose_name="JE Template ID",
        related_name='template_attributes'
    )
    input_file_attribute = models.ForeignKey(
        'DimAicInputFileAttributes',
        on_delete=models.CASCADE,
        verbose_name="Input File Attribute",
        related_name='je_templates'
    )
    # gl_acct_id = models.ForeignKey(
    #     'DimAICGLAcct',
    #     on_delete=models.CASCADE,
    #     verbose_name="GL Account ID",
    #     related_name='je_template_attributes'
    # )
    # offset_gl_acct_id = models.ForeignKey(
    #     'DimAICGLAcct',
    #     on_delete=models.CASCADE,
    #     verbose_name="Offset GL Account ID",
    #     related_name='je_template_offset_attributes'
    # )
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
        db_table = 'dim_aic_je_template_attribute'
        verbose_name = "AIC JE Template Attribute"
        verbose_name_plural = "AIC JE Template Attributes"
        unique_together = ['je_template_id', 'input_file_attribute']

    def __str__(self):
        return f"Template {self.je_template_id.je_name} - Attribute {self.input_file_attribute.name}"
