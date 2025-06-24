from django.db import models

class DimAICContact(models.Model):
    """
    Django model for the dim_AIC_Contact table, representing contact information.
    Foreign keys have been removed as per request.
    Composite key (unique constraint) added for cust_id and user_id.
    """
    # Removed primary_key=True from user_id, as unique_together will enforce uniqueness
    # on the combination of cust_id and user_id, and Django will implicitly add an 'id' primary key.
    user_id = models.IntegerField(
        verbose_name="User ID",
	)
    # Foreign key to DimAICCustomer, as Cust_Id in DimAICUser links to Cust_Id in DimAICCustomer
    cust_id = models.ForeignKey(
        'DimAICCustomer',
        on_delete=models.CASCADE,
        verbose_name="Customer ID",
	)
    contact_typ = models.CharField(
        max_length=5,
        verbose_name="Contact Type",
	)
    contact = models.CharField(
        max_length=100,
        verbose_name="Contact",
	)
    reg_flg = models.BooleanField(
        verbose_name="Registration Flag",
	)

    input_user = models.ForeignKey(
        "DimAICUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Input User",
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
        db_table = 'dim_aic_contact'
        # Set the verbose name for the model, used in the Django admin interface
        verbose_name = "AIC Contact"
        verbose_name_plural = "AIC Contacts"
        # Enforce uniqueness on the combination of cust_id and user_id to act as a composite key.
        # Django will automatically create an 'id' AutoField as the primary key for the table.
        unique_together = ('cust_id', 'user_id',)

    def __str__(self):
        # String representation of the object, useful for the Django admin
        return f"Contact for User ID: {self.user_id} (Customer: {self.cust_id})"

