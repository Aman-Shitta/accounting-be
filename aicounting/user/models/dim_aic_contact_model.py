from django.db import models
from django.contrib.auth import get_user_model

class DimAICContact(models.Model):
    """
    Django model for the dim_AIC_Contact table, representing contact information.
    Foreign keys have been removed as per request.
    Composite key (unique constraint) added for cust_id and user_id.
    """
    client_id = models.ForeignKey(
        'DimAICClient',
        on_delete=models.CASCADE,
        verbose_name="Client ID",
	)

    contact_type = models.CharField(
        max_length=5,
        verbose_name="Contact Type",
        choices=[
            ('phone', 'phone'),
            ('email', 'email'),
        ]
	)
    contact = models.CharField(
        max_length=100,
        verbose_name="Contact",
	)
    reg_flg = models.BooleanField(
        verbose_name="Registration Flag",
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
        # Define the table name in the database
        db_table = 'dim_aic_contact'
        # Set the verbose name for the model, used in the Django admin interface
        verbose_name = "AIC Contact"
        verbose_name_plural = "AIC Contacts"
        # Enforce uniqueness on the combination of cust_id and user_id to act as a composite key.
        # Django will automatically create an 'id' AutoField as the primary key for the table.
        unique_together = ('client_id', 'contact_type',)

