# Third-party imports
from django.contrib import admin

# Local imports
from .models.dim_aic_accountant_model import DimAICAccountant
from .models.dim_aic_assistant_model import DimAICAssistant
from .models.dim_aic_client_model import DimAICClient, DimAICClientDocument
from .models.dim_aic_contact_model import DimAICContact
from .models.dim_aic_customer_model import DimAICCustomer

@admin.register(DimAICAccountant)
class DimAICAccountantAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'first_name', 'last_name', 'customer', 'verified', 'created_at')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    list_filter = ('customer', 'verified')
    ordering = ('id',)


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
    fields = ('document_type', 'file', 'uploaded_by', 'created_at')
    readonly_fields = ('uploaded_by', 'created_at')
    verbose_name = "Document"
    verbose_name_plural = "Documents"


@admin.register(DimAICClient)
class DimAICClientAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'client_id', 'client_name', 'customer', 'street', 'city', 'state', 'zip_code', 'accountants_count', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('client_name', 'client_id', 'street', 'city')
    list_filter = ('customer', 'state', 'created_at')
    ordering = ('id', 'client_id')
    readonly_fields = ('id', 'created_at', 'updated_at')
    inlines = [DimAICContactInline, DimAICClientDocumentInline]
    
    def accountants_count(self, obj):
        """Display the number of assigned accountants"""
        return obj.assigned_accountants.count()
    accountants_count.short_description = 'Accountants'
    
    fieldsets = (
        ('Client Information', {
            'fields': ('customer', 'client_name', 'client_id')
        }),
        ('Address Information', {
            'fields': ('street', 'city', 'state', 'zip_code')
        }),
        ('Assignment Information', {
            'fields': ('assigned_accountants', 'input_user')
        }),
        ('Timestamps', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
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


@admin.register(DimAICAssistant)
class DimAICAssistantAdmin(admin.ModelAdmin):
    list_display = (
        'client', 'assistant_name', 'assistant_id', 'vector_store_id', 
        'model_name', 'temperature', 'top_p', 'is_active', 'created_at'
    )
    list_filter = ('is_active', 'model_name', 'created_at')
    search_fields = ('client__client_name', 'assistant_name', 'assistant_id')
    readonly_fields = ('assistant_id', 'vector_store_id', 'created_at', 'updated_at')
    fieldsets = (
        ('Client Information', {
            'fields': ('client', 'assistant_name')
        }),
        ('OpenAI Configuration', {
            'fields': ('assistant_id', 'vector_store_id', 'model_name', 'temperature', 'top_p')
        }),
        ('Schema and Rules', {
            'fields': ('response_schema', 'special_rules')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editing an existing object
            return self.readonly_fields + ('client',)
        return self.readonly_fields