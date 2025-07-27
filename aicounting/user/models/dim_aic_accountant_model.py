from django.db import models
from django.contrib.auth import get_user_model


class DimAICAccountant(models.Model):
    """
    Django model for the dim_AIC_Accountant table, representing accountant information.
    """
    system_user = models.OneToOneField(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="accountant_profile",
        verbose_name="Linked Django User",
        help_text="Link to Django user for authentication and permissions"
    )
    customer = models.ForeignKey(
        'DimAICCustomer',
        on_delete=models.CASCADE, 
        verbose_name="Customer ID",
        related_name="accountants"
    )
    username = models.CharField(
        max_length=72,
        verbose_name="Username",
    )
    first_name = models.CharField(
        max_length=72,
        verbose_name="First Name",
    )
    last_name = models.CharField(
        max_length=72,
        verbose_name="Last Name",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
    )
    email = models.EmailField(verbose_name="User Email", unique=True)

    verified = models.BooleanField(default=False, verbose_name="Verified")

    azure_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        verbose_name="Azure ID",
        help_text="Azure Active Directory user ID for SSO integration"
    )
    refresher_token = models.TextField(
        null=True,
        blank=True,
        verbose_name="Refresher Token",
        help_text="Azure AD refresher token for SSO integration"
    )

    input_user = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_accountants",
        verbose_name="Input User",
        help_text="User who created this accountant record"
    )

    class Meta:
        # Define the table name in the database
        db_table = 'dim_aic_accountant'
        # Set the verbose name for the model, used in the Django admin interface
        verbose_name = "AIC Accountant"
        verbose_name_plural = "AIC Accountants"

    def __str__(self):
        # String representation of the object, useful for the Django admin
        return f"{self.username} (ID: {self.id})"
