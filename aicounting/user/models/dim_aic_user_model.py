from django.db import models

class DimAICUser(models.Model):
    """
    Django model for the dim_AIC_User table, representing user information.
    """
    user_id = models.AutoField(
        primary_key=True,
        verbose_name="User ID",
	)
    # Foreign key to DimAICCustomer, as Cust_Id in DimAICUser links to Cust_Id in DimAICCustomer
    cust_id = models.ForeignKey(
        'DimAICCustomer',
        on_delete=models.CASCADE, 
        verbose_name="Customer ID",
	)
    username = models.CharField(
        max_length=8,
        verbose_name="Username",
	)
    first_name = models.CharField(
        max_length=100,
        verbose_name="First Name",
	)
    last_name = models.CharField(
        max_length=100,
        verbose_name="Last Name",
	)
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
	)

    class Meta:
        # Define the table name in the database
        db_table = 'dim_aic_user'
        # Set the verbose name for the model, used in the Django admin interface
        verbose_name = "AIC User"
        verbose_name_plural = "AIC Users"

    def __str__(self):
        # String representation of the object, useful for the Django admin
        return f"{self.username} (ID: {self.user_id})"
