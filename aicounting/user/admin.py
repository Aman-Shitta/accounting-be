from django.contrib import admin

from .models.dim_aic_user_model import DimAICUser
from .models.dim_aic_client_model import DimAICClient, DimAICClientDocument
from .models.dim_aic_contact_model import DimAICContact
from .models.dim_aic_customer_model import DimAICCustomer

@admin.register(DimAICUser)
class DimAICUserAdmin(admin.ModelAdmin):
    list_display = ('user_id', 'username', 'first_name', 'last_name', 'cust_id', 'created_at')
    search_fields = ('username', 'first_name', 'last_name')
    list_filter = ('cust_id',)
    ordering = ('user_id',)


class DimAICContactInline(admin.TabularInline):
    """Inline admin for contacts associated with a client"""
    model = DimAICContact
    extra = 1  # Number of empty forms to display
    fields = ('contact_name', 'contact_email', 'contact_phone')
    verbose_name = "Contact"
    verbose_name_plural = "Contacts"


class DimAICClientDocumentInline(admin.TabularInline):
    """Inline admin for documents associated with a client"""
    model = DimAICClientDocument
    extra = 0  # Don't show empty forms by default for documents
    fields = ('document_type', 'file', 'uploaded_by')
    readonly_fields = ('uploaded_by',)
    verbose_name = "Document"
    verbose_name_plural = "Documents"


@admin.register(DimAICClient)
class DimAICClientAdmin(admin.ModelAdmin):
    list_display = (
        'client_id', 'client_name', 'customer', 'street', 'city', 'state', 'zip_code', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('client_name', 'street', 'city')
    list_filter = ('customer', 'state')
    ordering = ('client_id',)
    inlines = [DimAICContactInline, DimAICClientDocumentInline]
    
    fieldsets = (
        ('Client Information', {
            'fields': ('customer', 'client_name', 'id')
        }),
        ('Address Information', {
            'fields': ('street', 'city', 'state', 'zip_code')
        }),
        ('Assignment Information', {
            'fields': ('assigned_user', 'input_user')
        }),
    )

@admin.register(DimAICContact)
class DimAICContactAdmin(admin.ModelAdmin):
    list_display = (
        'client_id', 'contact_name', 'contact_phone', 'contact_email', 'created_at', 'updated_at'
    )
    search_fields = ('contact_name', 'contact_email', 'contact_phone')
    list_filter = ('client_id',)
    ordering = ('client_id', 'contact_name')

@admin.register(DimAICCustomer)
class DimAICCustomerAdmin(admin.ModelAdmin):
    list_display = (
        'customer_id', 'customer_secure_id', 'customer_name', 'street', 'city', 'state_abrevation', 'zip_code', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('customer_name', 'city', 'customer_secure_id')
    list_filter = ('state_abrevation',)
    ordering = ('customer_id',)