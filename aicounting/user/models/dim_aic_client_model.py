# Third-party imports
from django.contrib.auth import get_user_model
from django.db import models


class DimAICClient(models.Model):
    """
    Represents a client entity associated with a customer and assigned user.
    """

    id = models.AutoField(primary_key=True, verbose_name="Client ID")

    customer = models.ForeignKey(
        'DimAICCustomer',
        on_delete=models.CASCADE,
        related_name="clients",
        verbose_name="Customer",
    )

    client_name = models.CharField(max_length=255, verbose_name="Client Name")
    client_id = models.CharField(max_length=255, verbose_name="Client Assigned ID", unique=True)
    street = models.CharField(max_length=255, verbose_name="Street", null=True, blank=True,)
    city = models.CharField(max_length=100, verbose_name="City", null=True, blank=True,)
    state = models.CharField(max_length=2, verbose_name="State Abbreviation", null=True, blank=True)
    zip_code = models.IntegerField(verbose_name="Zip Code", null=True, blank=True,)

    assigned_accountants = models.ManyToManyField(
        "DimAICAccountant",
        related_name="assigned_clients",
        blank=True,
        verbose_name="Assigned Accountants",
    )

    input_user = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Input User (Admin)",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        db_table = 'dim_aic_client'
        verbose_name = "AIC Client"
        verbose_name_plural = "AIC Clients"

    def __str__(self):
        return f"{self.client_name} (ID: {self.client_id})"


class DimAICClientDocument(models.Model):
    """
    Documents associated with a client, such as COA, Vendor List, GL History.
    """

    DOCUMENT_TYPE_CHOICES = [
        ("chart_of_account", "Chart of Accounts"),
        ("vendor_list", "Vendor List"),
        ("gl_history", "GL History"),
    ]

    client = models.ForeignKey(
        "DimAICClient",
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="Client"
    )

    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPE_CHOICES,
        verbose_name="Document Type"
    )

    file = models.FileField(
        upload_to="client_documents/",
        verbose_name="Document File",
        help_text="File will be stored in local media folder. Future support for S3/Azure."
    )

    uploaded_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Uploaded By"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        db_table = 'client_documents'
        verbose_name = "Client Document"
        verbose_name_plural = "Client Documents"

    def __str__(self):
        return f"{self.client.client_name} - {self.get_document_type_display()}"
