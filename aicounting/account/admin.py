# Third-party imports
from django.contrib import admin

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
        'je_freq', 'je_type', 'is_object', 'input_file', 'created_at', 'updated_at'
    )
    search_fields = ('je_name', 'je_refrence', 'client__client_name')
    list_filter = ('is_object', 'je_freq', 'je_type', 'client', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    inlines = [DimAICJETemplateAttributeInline]
    
    fieldsets = (
        ('Template Information', {
            'fields': ('je_name', 'je_refrence', 'je_freq', 'je_type')
        }),
        ('Template Type', {
            'fields': ('is_object', 'input_file'),
            'description': 'is_object determines the template type. If True, input_file is required.'
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
        """Optimize queries with select_related"""
        return super().get_queryset(request).select_related(
            'customer', 'client', 'je_freq', 'je_type', 'input_file'
        )
    
    def save_model(self, request, obj, form, change):
        """Custom save logic with validation"""
        # Validate that if is_object is True, input_file must be provided
        if obj.is_object and not obj.input_file:
            from django.core.exceptions import ValidationError
            raise ValidationError("Input file is required when template is an object template.")
        super().save_model(request, obj, form, change)

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