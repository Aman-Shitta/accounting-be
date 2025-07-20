from django.contrib import admin

# Register your models here.
from django.contrib import admin


from .models import (
    DimAICAcctType,
    DimAICGLAcct,
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
        'gl_acct_id',
        'gl_acct_nbr',
        'gl_acct_name',
        'cust_id',
        'client_id',
        'account_type_id',
        'input_user_id',
        'created_at',
        'updated_at',
    )
    search_fields = ('gl_acct_nbr', 'gl_acct_name', 'gl_acct_desc')
    list_filter = ('account_type_id', 'client_id', 'cust_id', 'created_at', 'updated_at')
    ordering = ('gl_acct_id',)



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
