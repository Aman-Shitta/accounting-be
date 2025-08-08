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
        related_name='je_templates',
        null=True,
        blank=True,
        help_text="For object templates - the attribute from input file"
    )
    # Fields for non-object templates
    gl_account = models.ForeignKey(
        'DimAICGLAcct',
        on_delete=models.CASCADE,
        verbose_name="GL Account",
        related_name='je_template_attributes',
        null=True,
        blank=True,
        help_text="For non-object templates - the GL account"
    )
    debit = models.CharField(
        max_length=255,
        verbose_name="Debit",
        null=True,
        blank=True,
        help_text="Debit value: can be null, number as string, attribute_id, or 'manual'"
    )
    credit = models.CharField(
        max_length=255,
        verbose_name="Credit",
        null=True,
        blank=True,
        help_text="Credit value: can be null, number as string, attribute_id, or 'manual'"
    )
    attribute_name = models.CharField(
        max_length=255,
        verbose_name="Attribute Name",
        null=True,
        blank=True,
        help_text="Name of the attribute when referenced by ID"
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
        db_table = 'dim_aic_je_template_attribute'
        verbose_name = "AIC JE Template Attribute"
        verbose_name_plural = "AIC JE Template Attributes"

    def __str__(self):
        if self.input_file_attribute:
            return f"Template {self.je_template_id.je_name} - Attribute {self.input_file_attribute.name}"
        else:
            return f"Template {self.je_template_id.je_name} - GL Account {self.gl_account.account_name if self.gl_account else 'Unknown'}"