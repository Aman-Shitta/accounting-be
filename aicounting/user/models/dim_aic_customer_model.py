import random
import string
from django.db import models

class DimAICCustomer(models.Model):
    """
    Django model for the dim_AIC_Customer table, representing customer information.
    """
    cust_id = models.AutoField(
        primary_key=True,
        verbose_name="Customer ID",
	)
    cust_secure_id = models.CharField(
        max_length=9,
        editable=False,
        verbose_name="Customer Secure ID",
	)
    cust_name = models.CharField(
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
    st_abrv = models.CharField(
        max_length=2,
        verbose_name="State Abbreviation",
	)

    zip_code = models.IntegerField(
        verbose_name="Zip Code",
	)

    input_user = models.ForeignKey(
        "DimAICUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Input User",
	)
    
    created_at = models.DateTimeField(
        auto_now_add=True, # Automatically sets the field to the current datetime when the object is first created.
        verbose_name="Created At",
	)

    updated_at = models.DateTimeField(
        auto_now=True, # Automatically updates the field to the current datetime every time the object is saved.
        verbose_name="Updated At",
	)

    class Meta:
        # Define the table name in the database
        db_table = 'dim_aic_customer'
        # Set the verbose name for the model, used in the Django admin interface
        verbose_name = "AIC Customer"
        verbose_name_plural = "AIC Customers"

    def generate_unique_cust_id(self):
        """
        Generates a unique random customer ID in the format '####-####'.
        """
        while True:
            part1 = ''.join(random.choices(string.digits, k=4))
            part2 = ''.join(random.choices(string.digits, k=4))
            new_id = f"{part1}-{part2}"
            # Check if an object with this ID already exists in the database
            if not DimAICCustomer.objects.filter(cust_id=new_id).exists():
                return new_id

    def save(self, *args, **kwargs):
        """
        Overrides the save method to generate a unique cust_id if it's not already set.
        """
        if not self.cust_id:  # Only generate ID for new objects
            self.cust_id = self.generate_unique_cust_id()
        super().save(*args, **kwargs)

    def __str__(self):
        # String representation of the object, useful for the Django admin
        return f"{self.cust_name} (ID: {self.cust_id})"