from django.contrib import admin

from user.models import (
    DimAICAccountant,
    DimAICAssistant,
    DimAICClient,
    DimAICClientDocument,
    DimAICContact,
    DimAICCustomer,
    DimAICReviewer,
)


@admin.register(DimAICAccountant)
class DimAICAccountantAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'first_name', 'last_name',
                    'customer', 'verified', 'clients_count', 'created_at')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    list_filter = ('customer', 'verified', 'created_at')
    ordering = ('customer', 'id')

    def clients_count(self, obj):
        """Display the number of assigned clients"""
        return obj.assigned_clients.count()
    clients_count.short_description = 'Assigned Clients'

    def get_queryset(self, request):
        """Optionally filter by customer if needed"""
        qs = super().get_queryset(request)
        # You can add customer filtering here if needed for specific users
        return qs

    fieldsets = (
        ('Basic Information', {
            'fields': ('system_user', 'customer', 'username', 'first_name', 'last_name', 'email')
        }),
        ('Azure Integration', {
            'fields': ('azure_id', 'refresher_token', 'verified'),
            'classes': ('collapse',)
        }),
        ('Meta Information', {
            'fields': ('input_user', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('created_at',)


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


class DimAICAccountantInline(admin.TabularInline):
    """Inline admin for accountants associated with a customer"""
    model = DimAICAccountant
    extra = 0  # Don't show empty forms by default
    fields = ('username', 'first_name', 'last_name', 'email', 'verified')
    readonly_fields = ('email',)
    verbose_name = "Accountant"
    verbose_name_plural = "Accountants"


class DimAICClientInline(admin.TabularInline):
    """Inline admin for clients associated with a customer"""
    model = DimAICClient
    extra = 0  # Don't show empty forms by default
    fields = ('client_id', 'client_name', 'city', 'state')
    readonly_fields = ('client_id',)
    verbose_name = "Client"
    verbose_name_plural = "Clients"


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

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Filter accountants to show only those belonging to the client's customer"""
        if db_field.name == "assigned_accountants":
            # Get the client instance if we're editing an existing client
            if hasattr(request, '_obj_'):
                client = request._obj_
                if client and client.customer:
                    kwargs["queryset"] = DimAICAccountant.objects.filter(
                        customer=client.customer)
            else:
                # For new clients, we can't filter yet, so show empty queryset
                kwargs["queryset"] = DimAICAccountant.objects.none()
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        """Store the object in request for use in formfield_for_manytomany"""
        request._obj_ = obj
        return super().get_form(request, obj, **kwargs)

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
        'id', 'customer_secure_id', 'customer_name', 'street', 'city', 'state_abrevation',
        'zip_code', 'accountants_count', 'clients_count', 'verified', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('customer_name', 'city', 'customer_secure_id', 'email')
    list_filter = ('state_abrevation', 'verified', 'created_at')
    ordering = ('id',)
    readonly_fields = ('id', 'customer_secure_id', 'created_at', 'updated_at')
    inlines = [DimAICAccountantInline, DimAICClientInline]

    def accountants_count(self, obj):
        """Display the number of accountants for this customer"""
        return obj.accountants.count()
    accountants_count.short_description = 'Accountants'

    def clients_count(self, obj):
        """Display the number of clients for this customer"""
        return obj.clients.count()
    clients_count.short_description = 'Clients'

    fieldsets = (
        ('Customer Information', {
            'fields': ('id', 'customer_secure_id', 'customer_name', 'system_user')
        }),
        ('Address Information', {
            'fields': ('street', 'city', 'state_abrevation', 'zip_code')
        }),
        ('Azure Integration', {
            'fields': ('azure_id', 'refresher_token', 'verified', 'registration_complete'),
            'classes': ('collapse',)
        }),
        ('Meta Information', {
            'fields': ('input_user', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DimAICAssistant)
class DimAICAssistantAdmin(admin.ModelAdmin):
    list_display = (
        'client', 'assistant_name', 'assistant_id', 'vector_store_id',
        'model_name', 'temperature', 'top_p', 'is_active', 'created_at'
    )
    list_filter = ('is_active', 'model_name', 'created_at')
    search_fields = ('client__client_name', 'assistant_name', 'assistant_id')
    readonly_fields = ('assistant_id', 'vector_store_id',
                       'created_at', 'updated_at')
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


@admin.register(DimAICReviewer)
class DimAICReviewerAdmin(admin.ModelAdmin):
    list_display = ('id', 'system_user', 'email', 'verified',
                    'azure_id', 'review_assigned_at', 'created_at')
    search_fields = ('email', 'system_user__username',
                     'system_user__first_name', 'system_user__last_name')
    list_filter = ('verified', 'created_at')
    readonly_fields = ('created_at', 'updated_at', 'azure_id')
    ordering = ('id',)

    fieldsets = (
        ('User Link', {
            'fields': ('system_user', 'email')
        }),
        ('Azure / Verification', {
            'fields': ('verified', 'azure_id', 'refresher_token')
        }),
        ('Review Assignment', {
            'fields': ('review_assigned_at',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs
