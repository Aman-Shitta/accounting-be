from django.db import models

class DimAICClient(models.Model):
    """
    Django model for the dim_AIC_Client table, representing client information.
    """
    client_id = models.AutoField(
        primary_key=True,
        verbose_name="Client ID",
	)
    # Foreign key to DimAICCustomer, assuming Cust_Id in DimAICClient links to Cust_Id in DimAICCustomer
    cust_id = models.ForeignKey(
        'DimAICCustomer',
        on_delete=models.CASCADE,
        verbose_name="Customer ID",
	)
    client_name = models.CharField(
        max_length=255,
        verbose_name="Client Name",
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
        db_table = 'dim_aic_client'
        # Set the verbose name for the model, used in the Django admin interface
        verbose_name = "AIC Client"
        verbose_name_plural = "AIC Clients"

    def __str__(self):
        # String representation of the object, useful for the Django admin
        return f"{self.client_name} (ID: {self.client_id})"

