# Third-party imports
from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages
from django.core.exceptions import ValidationError

# Local imports
from .models import (
    DimAICAcctType,
    DimAICGLAcct,
    DimAicInputFiles,
    DimAicInputFileAttributes,
    DimAICJEFreq,
    DimAICJEType,
    DimAICJETemplateHeader,
    DimAICJETemplateGL,
    DimAICJETemplateAttribute,
    DimAICTemplateDoc,
    FactJETransOther,
    FactAICJETransBank,
    FactAICJEMonthlyStat,
)
from .models.fact_aic_monthly_accounting import FactAICMonthlyAccounting
from .models.monthly_accounting_document_model import MonthlyAccountingDocument
from .models.monthly_document_line_models import (
    MonthlyDocumentBankKeyItem,
    MonthlyDocumentBankLineItem,
    MonthlyDocumentBankCheckItem,
    MonthlyDocumentAttributeItem,
    MonthlyTemplateManualAttributeItem
)
from .models.dim_aic_snapshot_models import (
    FactAICInputFileSnapshot,
    FactAICInputFileAttributeSnapshot,
    FactAICJETemplateHeaderSnapshot,
    FactAICJETemplateAttributeSnapshot,
)

@admin.register(DimAICAcctType)
class DimAICAcctTypeAdmin(admin.ModelAdmin):
    list_display = ('account_type_id', 'account_type', 'created_at', 'updated_at')
    search_fields = ('account_type',)
    list_filter = ('created_at', 'updated_at')
    ordering = ('account_type_id',)


@admin.register(DimAICGLAcct)
class DimAICGLAcctAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'account_number',
        'account_name',
        'customer',
        'client_id',
        'account_class',
        'sub_class',
        'account_type',
        'input_user',
        'created_at',
        'updated_at',
    )
    search_fields = ('account_number', 'account_name', 'description')
    list_filter = ('account_type', 'account_class', 'sub_class', 'customer', 'client_id', 'created_at', 'updated_at')
    ordering = ('id',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Account Information', {
            'fields': ('account_number', 'account_name', 'description')
        }),
        ('Classification', {
            'fields': ('account_class', 'sub_class', 'account_type')
        }),
        ('Relationships', {
            'fields': ('customer', 'client_id', 'input_user')
        }),
        ('Timestamps', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        """Optimize queries with select_related"""
        return super().get_queryset(request).select_related(
            'customer', 'client_id', 'account_type', 'input_user'
        )



@admin.register(DimAICJEFreq)
class DimAICJEFreqAdmin(admin.ModelAdmin):
    list_display = ('id', 'je_freq', 'created_at', 'updated_at')
    search_fields = ('je_freq',)
    ordering = ('id',)

@admin.register(DimAICJEType)
class DimAICJETypeAdmin(admin.ModelAdmin):
    list_display = ('je_type', 'je_type', 'created_at', 'updated_at')
    search_fields = ('je_type',)
    ordering = ('je_type',)


class DimAICJETemplateAttributeInline(admin.TabularInline):
    model = DimAICJETemplateAttribute
    extra = 1
    fields = ('template_type_display', 'input_file_attribute', 'gl_account', 'debit', 'credit', 'attribute_name')
    readonly_fields = ('template_type_display',)
    
    def template_type_display(self, obj):
        """Display template type"""
        if obj.je_template_id:
            return "Object" if obj.je_template_id.is_object else "Non-Object"
        return "Unknown"
    template_type_display.short_description = 'Template Type'
    
    def get_formset(self, request, obj=None, **kwargs):
        """Customize the formset based on template type"""
        formset = super().get_formset(request, obj, **kwargs)
        if obj and obj.is_object:
            # For object templates, hide non-object fields
            self.fields = ('template_type_display', 'input_file_attribute')
        else:
            # For non-object templates, hide object fields
            self.fields = ('template_type_display', 'gl_account', 'debit', 'credit', 'attribute_name')
        return formset


@admin.register(DimAICJETemplateHeader)
class DimAICJETemplateHeaderAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'je_name', 'je_refrence', 'customer', 'client', 
        'je_freq', 'je_type', 'is_object', 'display_input_files', 'created_at', 'updated_at'
    )
    search_fields = ('je_name', 'je_refrence', 'client__client_name')
    list_filter = ('is_object', 'je_freq', 'je_type', 'client', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'display_input_files')
    inlines = [DimAICJETemplateAttributeInline]
    
    filter_horizontal = ('input_files',)  # Adds a nice widget for handling M2M relationships
    
    fieldsets = (
        ('Template Information', {
            'fields': ('je_name', 'je_refrence', 'je_freq', 'je_type')
        }),
        ('Template Type', {
            'fields': ('is_object', 'input_files'),
            'description': 'is_object determines the template type. If True, at least one input file is required.'
        }),
        ('Relationships', {
            'fields': ('customer', 'client')
        }),
        ('Timestamps', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        """Optimize queries with select_related and prefetch_related"""
        return super().get_queryset(request).select_related(
            'customer', 'client', 'je_freq', 'je_type'
        ).prefetch_related('input_files')
    
    def display_input_files(self, obj):
        """Display input files as comma-separated list in admin list view"""
        return ", ".join([file.name for file in obj.input_files.all()])
    display_input_files.short_description = "Input Files"
    
    def save_model(self, request, obj, form, change):
        """Custom save logic with validation"""
        super().save_model(request, obj, form, change)
        
        # We need to check after saving because M2M fields are only saved after the main model
        if obj.is_object and not obj.input_files.exists():
            messages.warning(
                request,
                "Warning: This is an object template but no input files are associated. At least one input file is recommended."
            )

@admin.register(DimAICJETemplateGL)
class DimAICJETemplateGLAdmin(admin.ModelAdmin):
    list_display = ('je_template_gl_id', 'je_template_id', 'gl_acct_id', 'acct_type_id', 'offset_gl_acct_id')
    search_fields = ('je_template_id__je_name',)
    ordering = ('je_template_gl_id',)

@admin.register(DimAICTemplateDoc)
class DimAICTemplateDocAdmin(admin.ModelAdmin):
    list_display = ('je_template_gl_acct_id', 'doc_id', 'created_at', 'updated_at')
    search_fields = ('doc_comments', 'doc_ai_prompt')
    ordering = ('je_template_gl_acct_id',)

@admin.register(FactJETransOther)
class FactJETransOtherAdmin(admin.ModelAdmin):
    list_display = ('je_trans_id', 'gl_acct_id', 'offset_gl_acct_id', 'amt', 'doc_id', 'created_at', 'updated_at')
    search_fields = ('je_trans_id',)
    ordering = ('je_trans_id',)

@admin.register(FactAICJETransBank)
class FactAICJETransBankAdmin(admin.ModelAdmin):
    list_display = (
        'je_trans_bank_id', 'je_template_id', 'post_dt', 'trans_dt', 'dscr',
        'gl_acct_id', 'offset_gl_acct_id', 'amt', 'class_conf_score', 'verified', 'je_trans_type'
    )
    search_fields = ('dscr',)
    list_filter = ('verified', 'je_trans_type')
    ordering = ('je_trans_bank_id',)

@admin.register(FactAICJEMonthlyStat)
class FactAICJEMonthlyStatAdmin(admin.ModelAdmin):
    list_display = (
        'je_trans_id', 'je_template_id', 'je_mth', 'je_yr',
        'is_processed', 'is_verified', 'created_at', 'updated_at'
    )
    list_filter = ('is_processed', 'is_verified', 'je_mth', 'je_yr')
    ordering = ('je_trans_id',)


@admin.register(DimAicInputFiles)
class DimAicInputFilesAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'file_type', 'client', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('name', 'client__client_name')
    list_filter = ('file_type', 'client', 'input_user', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    
    fieldsets = (
        ('File Information', {
            'fields': ('name', 'file_type', 'file')
        }),
        ('Relationships', {
            'fields': ('client', 'input_user')
        }),
        ('Timestamps', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        """Optimize queries with select_related"""
        return super().get_queryset(request).select_related(
            'client', 'input_user'
        )


class DimAicInputFileAttributesInline(admin.TabularInline):
    model = DimAicInputFileAttributes
    extra = 1
    fields = ('name', 'gl_account', 'type', 'offset_gl_account', 'input_user', 'comments')


@admin.register(DimAicInputFileAttributes)
class DimAicInputFileAttributesAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'input_file', 'gl_account', 'type', 'offset_gl_account', 'input_user', 'created_at', 'updated_at'
    )
    search_fields = ('name', 'input_file__name', 'gl_account__account_name', 'offset_gl_account__account_name')
    list_filter = ('type', 'input_user', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Attribute Information', {
            'fields': ('name', 'input_file', 'type', 'comments')
        }),
        ('GL Accounts', {
            'fields': ('gl_account', 'offset_gl_account')
        }),
        ('User Information', {
            'fields': ('input_user',)
        }),
        ('Timestamps', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        """Optimize queries with select_related"""
        return super().get_queryset(request).select_related(
            'input_file', 'gl_account', 'offset_gl_account', 'input_user'
        )


# Add the inline to the DimAicInputFiles admin
DimAicInputFilesAdmin.inlines = [DimAicInputFileAttributesInline]


@admin.register(DimAICJETemplateAttribute)
class DimAICJETemplateAttributeAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'je_template_id', 'template_type', 'attribute_display', 
        'gl_account_display', 'debit', 'credit', 'attribute_name',
        'input_user', 'created_at', 'updated_at'
    )
    search_fields = (
        'je_template_id__je_name', 'input_file_attribute__name',
        'gl_account__account_name', 'attribute_name'
    )
    list_filter = ('je_template_id__is_object', 'input_user', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Template Information', {
            'fields': ('je_template_id',)
        }),
        ('Object Template Fields', {
            'fields': ('input_file_attribute',),
            'description': 'Used with Object(Attribute) View'
        }),
        ('Non-Object Template Fields', {
            'fields': ('gl_account', 'debit', 'credit', 'attribute_name'),
            'description': 'Used with GL view'
        }),
        ('User Information', {
            'fields': ('input_user',)
        }),
        ('Timestamps', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def template_type(self, obj):
        """Display whether this is an object or non-object template"""
        return "Object" if obj.je_template_id.is_object else "Non-Object"
    template_type.short_description = 'Template Type'
    
    def attribute_display(self, obj):
        """Display the attribute name for object templates"""
        if obj.input_file_attribute:
            return f"{obj.input_file_attribute.name} ({obj.input_file_attribute.input_file.name})"
        return "N/A"
    attribute_display.short_description = 'Input File Attribute'
    
    def gl_account_display(self, obj):
        """Display the GL account for non-object templates"""
        if obj.gl_account:
            return f"{obj.gl_account.account_name} ({obj.gl_account.account_number})"
        return "N/A"
    gl_account_display.short_description = 'GL Account'
    
    def get_queryset(self, request):
        """Optimize queries with select_related"""
        return super().get_queryset(request).select_related(
            'je_template_id', 'input_file_attribute__input_file',
            'gl_account', 'input_user'
        )
    
    def save_model(self, request, obj, form, change):
        """Custom save logic with validation"""
        from django.core.exceptions import ValidationError
        
        # Validate fields based on template type
        if obj.je_template_id.is_object:
            # For object templates, input_file_attribute is required
            if not obj.input_file_attribute:
                raise ValidationError("Input file attribute is required for object templates.")
            # Clear non-object fields
            obj.gl_account = None
            obj.debit = None
            obj.credit = None
            obj.attribute_name = None
        else:
            # For non-object templates, gl_account is required
            if not obj.gl_account:
                raise ValidationError("GL account is required for non-object templates.")
            # At least one of debit or credit should have a value
            if not obj.debit and not obj.credit:
                raise ValidationError("At least one of debit or credit must have a value.")
            # Clear object fields
            obj.input_file_attribute = None
        
        super().save_model(request, obj, form, change)


#############################################
# Monthly Accounting Documents (Inline)
#############################################
class MonthlyAccountingDocumentInline(admin.TabularInline):
    """Inline for documents under a Monthly Accounting session (read-only)."""
    model = MonthlyAccountingDocument
    extra = 0
    can_delete = False
    readonly_fields = ("doc_id", "doc_type", "status", "file_link", "created_at", "updated_at")
    fields = ("doc_id", "doc_type", "status", "file_link", "created_at", "updated_at")

    def file_link(self, obj):  # pragma: no cover - admin display helper
        if obj.file:
            return format_html('<a href="{}" target="_blank">file</a>', obj.file.url)
        return "-"
    file_link.short_description = "File"

    def has_add_permission(self, request, obj=None):  # pragma: no cover
        return False


#############################################
# Monthly Document Line Items (Inlines)
#############################################
class MonthlyDocumentBankKeyItemInline(admin.TabularInline):
    """Inline for document key items (summary data like balances)."""
    model = MonthlyDocumentBankKeyItem
    extra = 0
    readonly_fields = ('page_number', 'key', 'value', 'created_at')
    fields = ('page_number', 'key', 'value', 'created_at')
    can_delete = False
    classes = ['collapse']
    
    def has_add_permission(self, request, obj=None):
        return False


class MonthlyDocumentBankLineItemInline(admin.TabularInline):
    """Inline for transaction line items."""
    model = MonthlyDocumentBankLineItem
    extra = 0
    readonly_fields = ('page_number', 'line_number', 'date', 'description', 'formatted_amount', 
                      'transaction_type', 'gl_account', 'offset_gl_account', 'created_at')
    fields = ('page_number', 'line_number', 'date', 'description', 'formatted_amount', 
             'transaction_type', 'gl_account', 'offset_gl_account')
    can_delete = False
    classes = ['collapse']
    
    def has_add_permission(self, request, obj=None):
        return False


class MonthlyDocumentBankCheckItemInline(admin.TabularInline):
    """Inline for check items extracted from document."""
    model = MonthlyDocumentBankCheckItem
    extra = 0
    readonly_fields = ('page_number', 'amount', 'payee', 'check_number', 'memo', 'created_at')
    fields = ('page_number', 'amount', 'payee', 'check_number', 'memo', 'related_line_item')
    can_delete = False
    classes = ['collapse']
    
    def has_add_permission(self, request, obj=None):
        return False


#############################################
# Monthly Accounting Documents (Standalone)
#############################################
@admin.register(MonthlyAccountingDocument)
class MonthlyAccountingDocumentAdmin(admin.ModelAdmin):
    list_display = ("doc_id", "monthly_accounting", "doc_type", "status", "file_link", "created_at")
    list_filter = ("status", "doc_type", "created_at")
    search_fields = ("doc_id", "monthly_accounting__client__client_name")
    readonly_fields = ("doc_id", "monthly_accounting", "input_file_snapshot", "created_at", "updated_at", "file_link")
    
    inlines = [
        # MonthlyDocumentBankKeyItemInline,
        MonthlyDocumentBankLineItemInline,
        # MonthlyDocumentBankCheckItemInline,
    ]

    def file_link(self, obj):  # pragma: no cover
        if obj.file:
            return format_html('<a href="{}" target="_blank">file</a>', obj.file.url)
        return "-"
    file_link.short_description = "File"

    fieldsets = (
        (None, {"fields": ("doc_id", "monthly_accounting", "input_file_snapshot", "doc_type", "status", "file", "file_link")}),
        ("Processing Results", {"fields": ("control_item", "markdown_metadata"), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

#############################################
# Monthly Accounting Sessions
#############################################
@admin.register(FactAICMonthlyAccounting)
class FactAICMonthlyAccountingAdmin(admin.ModelAdmin):
    list_display = ("id", "client", "month", "year", "status", "created_by", "created_at")
    list_filter = ("status", "month", "year", "created_at")
    search_fields = ("client__client_name",)
    readonly_fields = ("created_at", "completed_at")
    inlines = [MonthlyAccountingDocumentInline]
    fieldsets = (
        (None, {"fields": ("client", "month", "year", "status", "created_by", "created_at", "completed_at")}),
    )

    def save_model(self, request, obj, form, change):  # pragma: no cover
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class FactAICInputFileAttributeSnapshotInline(admin.TabularInline):
    """
    Inline admin for FactAICInputFileAttributeSnapshot
    """
    model = FactAICInputFileAttributeSnapshot
    extra = 0
    readonly_fields = ('original_attribute', 'name', 'gl_account', 'type', 'offset_gl_account', 'comments')
    fields = ('name', 'gl_account', 'type', 'offset_gl_account', 'comments', 'original_attribute')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FactAICInputFileSnapshot)
class FactAICInputFileSnapshotAdmin(admin.ModelAdmin):
    """
    Admin for FactAICInputFileSnapshot
    """
    list_display = ('id', 'name', 'monthly_accounting_link', 'file_type', 'file_link', 'original_created_at')
    list_filter = ('file_type', 'monthly_accounting__month', 'monthly_accounting__year')
    search_fields = ('name', 'monthly_accounting__client__client_name')
    readonly_fields = ('monthly_accounting', 'original_input_file', 'client', 'file_link', 'original_created_at', 'original_updated_at')
    inlines = [FactAICInputFileAttributeSnapshotInline]
    
    fieldsets = (
        ('File Information', {
            'fields': ('name', 'file_type', 'description', 'file', 'file_link')
        }),
        ('Relationships', {
            'fields': ('monthly_accounting', 'original_input_file', 'client', 'input_user')
        }),
        ('Timestamps', {
            'fields': ('original_created_at', 'original_updated_at')
        }),
    )
    
    def monthly_accounting_link(self, obj):
        if obj.monthly_accounting:
            url = f"/admin/account/factaicmonthlyaccounting/{obj.monthly_accounting.id}/change/"
            return format_html('<a href="{}">{} - {} {}</a>', 
                url, 
                obj.monthly_accounting.client.client_name,
                obj.monthly_accounting.get_month_name(),
                obj.monthly_accounting.year
            )
        return "None"
    monthly_accounting_link.short_description = 'Monthly Accounting'
    
    def file_link(self, obj):
        if obj.file:
            return format_html('<a href="{}" target="_blank">View File</a>', obj.file.url)
        return "No file"
    file_link.short_description = 'File'


class FactAICJETemplateAttributeSnapshotInline(admin.TabularInline):
    """
    Inline admin for FactAICJETemplateAttributeSnapshot
    """
    model = FactAICJETemplateAttributeSnapshot
    extra = 0
    readonly_fields = ('original_attribute', 'gl_account', 'debit', 'credit', 'attribute_name', 'input_file_attribute')
    fields = ('gl_account', 'debit', 'credit', 'attribute_name', 'input_file_attribute', 'original_attribute')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FactAICJETemplateHeaderSnapshot)
class FactAICJETemplateHeaderSnapshotAdmin(admin.ModelAdmin):
    """
    Admin for FactAICJETemplateHeaderSnapshot
    """
    list_display = ('id', 'je_name', 'monthly_accounting_link', 'je_type', 'is_object', 'display_input_files', 'original_created_at')
    list_filter = ('je_type', 'is_object', 'monthly_accounting__month', 'monthly_accounting__year')
    search_fields = ('je_name', 'monthly_accounting__client__client_name')
    readonly_fields = ('monthly_accounting', 'original_template', 'client', 'customer', 'original_created_at', 'original_updated_at', 'display_input_files')
    inlines = [FactAICJETemplateAttributeSnapshotInline]
    
    filter_horizontal = ('input_files',)  # Better UI for M2M fields
    
    fieldsets = (
        ('Template Information', {
            'fields': ('je_name', 'je_refrence', 'je_freq', 'je_type', 'is_object', 'description')
        }),
        ('Relationships', {
            'fields': ('monthly_accounting', 'original_template', 'client', 'customer', 'input_files')
        }),
        ('Timestamps', {
            'fields': ('original_created_at', 'original_updated_at')
        }),
        ('Export Item', {
            'fields': ('je_export_file',),
        })
    )
    
    def display_input_files(self, obj):
        """Display input files as comma-separated list in admin list view"""
        return ", ".join([file.name for file in obj.input_files.all()])
    display_input_files.short_description = "Input Files"
    
    def monthly_accounting_link(self, obj):
        if obj.monthly_accounting:
            url = f"/admin/account/factaicmonthlyaccounting/{obj.monthly_accounting.id}/change/"
            return format_html('<a href="{}">{} - {} {}</a>', 
                url, 
                obj.monthly_accounting.client.client_name,
                obj.monthly_accounting.get_month_name(),
                obj.monthly_accounting.year
            )
        return "None"
    monthly_accounting_link.short_description = 'Monthly Accounting'

#############################################
# Snapshot Attribute Models (Standalone)
#############################################
@admin.register(FactAICInputFileAttributeSnapshot)
class FactAICInputFileAttributeSnapshotAdmin(admin.ModelAdmin):
    """Standalone view for input file attribute snapshots."""
    list_display = (
        'id', 'input_file_snapshot', 'name', 'gl_account', 'type', 'offset_gl_account', 'original_created_at'
    )
    list_filter = ('type', 'original_created_at')
    search_fields = ('name', 'input_file_snapshot__name', 'gl_account__account_name')
    readonly_fields = (
        'input_file_snapshot', 'original_attribute', 'name', 'gl_account', 'type', 'offset_gl_account',
        'comments', 'original_created_at', 'original_updated_at'
    )
    fieldsets = (
        (None, { 'fields': ('input_file_snapshot', 'original_attribute', 'name', 'type', 'gl_account', 'offset_gl_account', 'comments') }),
        ('Timestamps', { 'fields': ('original_created_at', 'original_updated_at'), 'classes': ('collapse',) }),
    )

@admin.register(FactAICJETemplateAttributeSnapshot)
class FactAICJETemplateAttributeSnapshotAdmin(admin.ModelAdmin):
    """Standalone view for JE template attribute snapshots."""
    list_display = (
        'id', 'je_template_snapshot', 'attribute_name', 'gl_account', 'debit', 'credit', 'original_created_at'
    )
    list_filter = ('je_template_snapshot__is_object', 'original_created_at')
    search_fields = ('attribute_name', 'je_template_snapshot__je_name', 'gl_account__account_name')
    readonly_fields = (
        'je_template_snapshot', 'original_attribute', 'input_file_attribute', 'gl_account', 'debit', 'credit',
        'attribute_name', 'input_user', 'original_created_at', 'original_updated_at'
    )
    fieldsets = (
        (None, { 'fields': ('je_template_snapshot', 'original_attribute', 'input_file_attribute', 'attribute_name', 'gl_account', 'debit', 'credit', 'input_user') }),
        ('Timestamps', { 'fields': ('original_created_at', 'original_updated_at'), 'classes': ('collapse',) }),
    )


#############################################
# Monthly Document Line Items (Standalone)
#############################################
@admin.register(MonthlyDocumentBankKeyItem)
class MonthlyDocumentBankKeyItemAdmin(admin.ModelAdmin):
    """Admin for monthly document key items."""
    list_display = ('id', 'document', 'page_number', 'key', 'value', 'created_at')
    list_filter = ('page_number', 'key', 'created_at')
    search_fields = ('document__doc_id', 'key', 'value')
    readonly_fields = ('document', 'page_number', 'key', 'value', 'created_at', 'updated_at')
    
    fieldsets = (
        (None, {'fields': ('document', 'page_number', 'key', 'value')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(MonthlyDocumentBankLineItem)
class MonthlyDocumentBankLineItemAdmin(admin.ModelAdmin):
    """Admin for monthly document line items."""
    list_display = ('id', 'document', 'page_number', 'line_number', 'date', 'description_short', 
                   'formatted_amount', 'transaction_type', 'gl_account', 'created_at')
    list_filter = ('transaction_type', 'page_number', 'is_check_transaction', 'created_at')
    search_fields = ('document__doc_id', 'description', 'check_number')
    readonly_fields = ('document', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('document', 'page_number', 'line_number', 'date', 'description', 
                      'amount', 'transaction_type', 'debit_amount', 'credit_amount')
        }),
        ('Check Information', {
            'fields': ('is_check_transaction', 'check_number'),
            'classes': ('collapse',)
        }),
        ('GL Classification', {
            'fields': ('gl_account', 'offset_gl_account'),
            'description': 'GL accounts assigned through classification pipeline'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def description_short(self, obj):
        return obj.description[:50] + "..." if len(obj.description) > 50 else obj.description
    description_short.short_description = 'Description'


@admin.register(MonthlyDocumentBankCheckItem)
class MonthlyDocumentBankCheckItemAdmin(admin.ModelAdmin):
    """Admin for monthly document check items."""
    list_display = ('id', 'document', 'page_number', 'check_number', 'amount', 'payee_short', 'created_at')
    list_filter = ('page_number', 'created_at')
    search_fields = ('document__doc_id', 'check_number', 'payee', 'amount')
    readonly_fields = ('document', 'created_at')
    
    fieldsets = (
        ('Check Details', {
            'fields': ('document', 'page_number', 'amount', 'payee', 'memo', 
                      'check_number', 'clearing_date', 'passing_date')
        }),
        ('Relationship', {
            'fields': ('related_line_item',),
            'description': 'Link to corresponding transaction line item'
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def payee_short(self, obj):
        return obj.payee[:30] + "..." if obj.payee and len(obj.payee) > 30 else obj.payee
    payee_short.short_description = 'Payee'


@admin.register(MonthlyDocumentAttributeItem)
class MonthlyDocumentAttributeItemAdmin(admin.ModelAdmin):
    """Admin for monthly document attribute items."""
    list_display = ('id', 'document', 'page_number', 'attribute_name', 'value_short', 
                   'transaction_type', 'gl_account', 'created_at')
    list_filter = ('transaction_type', 'page_number', 'created_at')
    search_fields = ('document__doc_id', 'attribute__name', 'value')
    readonly_fields = ('document', 'created_at', 'updated_at')
    
    def attribute_name(self, obj):
        return obj.attribute.name if obj.attribute else 'N/A'
    attribute_name.short_description = 'Attribute Name'
    
    def value_short(self, obj):
        return (obj.value[:50] + '...') if obj.value and len(obj.value) > 50 else obj.value
    value_short.short_description = 'Value'


@admin.register(MonthlyTemplateManualAttributeItem)
class MonthlyTemplateManualAttributeItemAdmin(admin.ModelAdmin):
    """Admin for monthly template manual attribute items."""
    list_display = ('id', 'template_attribute_name', 'value_short', 'formatted_value', 
                   'transaction_type', 'gl_account', 'entered_by', 'created_at')
    list_filter = ('transaction_type', 'created_at', 'entered_by')
    search_fields = ('template_attribute__attribute_name', 'value', 'description')
    readonly_fields = ('created_at', 'updated_at', 'formatted_value')
    
    fieldsets = (
        ('Template Reference', {
            'fields': ('template_attribute',)
        }),
        ('Manual Entry Details', {
            'fields': ('value', 'formatted_value', 'transaction_type', 'description')
        }),
        ('GL Classification', {
            'fields': ('gl_account', 'offset_gl_account'),
            'description': 'GL accounts for this manual entry'
        }),
        ('User Information', {
            'fields': ('entered_by',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def template_attribute_name(self, obj):
        if obj.template_attribute:
            template_name = obj.template_attribute.je_template_snapshot.je_name if obj.template_attribute.je_template_snapshot else 'N/A'
            attribute_name = obj.template_attribute.attribute_name or 'N/A'
            return f"{template_name} - {attribute_name}"
        return 'N/A'
    template_attribute_name.short_description = 'Template Attribute'
    
    def value_short(self, obj):
        return (obj.value[:50] + '...') if obj.value and len(obj.value) > 50 else obj.value
    value_short.short_description = 'Value'
    
    def save_model(self, request, obj, form, change):
        if not change and not obj.entered_by:
            obj.entered_by = request.user
        super().save_model(request, obj, form, change)