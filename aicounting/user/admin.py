from django.contrib import admin

from .models.dim_aic_user_model import DimAICUser
from .models.dim_aic_client_model import DimAICClient
from .models.dim_aic_contact_model import DimAICContact
from .models.dim_aic_customer_model import DimAICCustomer

@admin.register(DimAICUser)
class DimAICUserAdmin(admin.ModelAdmin):
    list_display = ('user_id', 'username', 'first_name', 'last_name', 'cust_id', 'created_at')
    search_fields = ('username', 'first_name', 'last_name')
    list_filter = ('cust_id',)
    ordering = ('user_id',)

@admin.register(DimAICClient)
class DimAICClientAdmin(admin.ModelAdmin):
    list_display = (
        'client_id', 'client_name', 'customer', 'street', 'city', 'state', 'zip_code', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('client_name', 'street', 'city')
    list_filter = ('customer', 'street')
    ordering = ('client_id',)

@admin.register(DimAICContact)
class DimAICContactAdmin(admin.ModelAdmin):
    list_display = (
        'client_id', 'contact_type', 'contact', 'reg_flg', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('contact',)
    list_filter = ('contact_type', 'reg_flg', 'client_id')
    ordering = ('client_id', )

@admin.register(DimAICCustomer)
class DimAICCustomerAdmin(admin.ModelAdmin):
    list_display = (
        'customer_id', 'customer_secure_id', 'customer_name', 'street', 'city', 'state_abrevation', 'zip_code', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('customer_name', 'city', 'customer_secure_id')
    list_filter = ('state_abrevation',)
    ordering = ('customer_id',)