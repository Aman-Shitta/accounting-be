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
        'client_id', 'client_name', 'cust_id', 'street', 'city', 'st_abrv', 'zip_code', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('client_name', 'street', 'city')
    list_filter = ('cust_id', 'st_abrv')
    ordering = ('client_id',)

@admin.register(DimAICContact)
class DimAICContactAdmin(admin.ModelAdmin):
    list_display = (
        'user_id', 'cust_id', 'contact_typ', 'contact', 'reg_flg', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('contact',)
    list_filter = ('contact_typ', 'reg_flg', 'cust_id')
    ordering = ('cust_id', 'user_id')

@admin.register(DimAICCustomer)
class DimAICCustomerAdmin(admin.ModelAdmin):
    list_display = (
        'cust_id', 'cust_secure_id', 'cust_name', 'street', 'city', 'st_abrv', 'zip_code', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('cust_name', 'city', 'cust_secure_id')
    list_filter = ('st_abrv',)
    ordering = ('cust_id',)