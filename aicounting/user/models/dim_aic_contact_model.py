
# Third-party imports
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, validate_email
from django.db import models


class DimAICContact(models.Model):
    """
    Contact details for a client, with explicit fields for name, email, and phone.
    """

    client_id = models.ForeignKey(
        'DimAICClient',
        on_delete=models.CASCADE,
        verbose_name="Client",
        related_name="contacts"
    )

    contact_name = models.CharField(
        max_length=100,
        verbose_name="Contact Name"
    )

    contact_phone = models.CharField(
        max_length=15,
        verbose_name="Contact Phone",
        validators=[
            RegexValidator(
                regex=r'^(?:\d{10,15}|\d{3}-\d{3}-\d{4})$',
                message="Enter a valid phone number (7 to 15 digits, optional leading +)"
            )
        ]
    )

    contact_email = models.CharField(
        max_length=100,
        verbose_name="Contact Email"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contact'
        verbose_name = "Contact"
        verbose_name_plural = "Contacts"
        unique_together = ('client_id', 'contact_email')

    def clean(self):
        try:
            validate_email(self.contact_email)
        except ValidationError:
            raise ValidationError(
                {'contact_email': 'Enter a valid email address.'})

    def save(self, *args, **kwargs):
        self.full_clean()  # Run validations
        super().save(*args, **kwargs)
