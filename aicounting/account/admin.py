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
    list_display = ('je_freq_id', 'je_freq', 'created_at', 'updated_at')
    search_fields = ('je_freq',)
    ordering = ('je_freq_id',)

@admin.register(DimAICJEType)
class DimAICJETypeAdmin(admin.ModelAdmin):
    list_display = ('je_type_id', 'je_type', 'created_at', 'updated_at')
    search_fields = ('je_type',)
    ordering = ('je_type_id',)

@admin.register(DimAICJETemplateHeader)
class DimAICJETemplateHeaderAdmin(admin.ModelAdmin):
    list_display = ('je_template_id', 'je_name', 'je_ref', 'cust_id', 'client_id', 'je_freq_id', 'je_type_id')
    search_fields = ('je_name', 'je_ref')
    ordering = ('je_template_id',)

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
