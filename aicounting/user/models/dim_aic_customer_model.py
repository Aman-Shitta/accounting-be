import random
import string
from django.db import models
from django.contrib.auth import get_user_model


class DimAICCustomer(models.Model):
    """
    Django model for the dim_AIC_Customer table, representing customer information.
    """
    system_user = models.OneToOneField(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="customer_profile",
        verbose_name="Linked Django User",
        help_text="Link to Django user for authentication and permissions"
    )
    id = models.AutoField(
        primary_key=True,
        verbose_name="Customer ID",
    )
    customer_secure_id = models.CharField(
        max_length=9,
        editable=False,
        verbose_name="Customer Secure ID",
    )
    customer_name = models.CharField(
        max_length=255,
        verbose_name="Customer Name",
    )
    street = models.CharField(
        max_length=255,
        verbose_name="Street",
    )
    city = models.CharField(
        max_length=100,
        verbose_name="City",
    )
    state_abrevation = models.CharField(
        max_length=2,
        verbose_name="State Abbrevation",
    )

    zip_code = models.IntegerField(
        verbose_name="Zip Code",
    )

    input_user = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Input User"
    )
    registration_complete = models.BooleanField(
        default=False,
        help_text="Becomes True after first SSO login"
    )

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

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
    )

    class Meta:
        # Define the table name in the database
        db_table = 'customer'
        # Set the verbose name for the model, used in the Django admin interface
        verbose_name = "Customer"
        verbose_name_plural = "Customers"

    def generate_unique_cust_id(self):
        """
        Generates a unique random customer ID in the format '####-####'.
        """
        while True:
            part1 = ''.join(random.choices(string.digits, k=4))
            part2 = ''.join(random.choices(string.digits, k=4))
            new_id = f"{part1}-{part2}"
            # Check if an object with this ID already exists in the database
            if not DimAICCustomer.objects.filter(customer_secure_id=new_id).exists():
                return new_id

    def save(self, *args, **kwargs):
        """
        Overrides the save method to generate a unique cust_id if it's not already set.
        """
        if not self.customer_secure_id:  # Only generate ID for new objects
            self.customer_secure_id = self.generate_unique_cust_id()
        super().save(*args, **kwargs)

    def __str__(self):
        # String representation of the object, useful for the Django admin
        return f"{self.customer_name} (ID: {self.customer_secure_id})"
