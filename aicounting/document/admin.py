from django.contrib import admin
from document.models import DimAICDocument, FactAICDocKeyItem, FactAICDocLine, FactAICDocCheckItem
from django.utils.html import format_html

class FactAICDocKeyItemInline(admin.TabularInline):
    model = FactAICDocKeyItem
    extra = 0
    fields = ('page_number', 'line_number', 'key', 'value')
    readonly_fields = ('page_number', 'line_number', 'key', 'value')
    can_delete = False
    show_change_link = False
    classes = ['collapse']  # Makes this inline collapsible

class FactAICDocLineInline(admin.TabularInline):
    model = FactAICDocLine
    extra = 0
    readonly_fields = ('page_number', 'line_number', 'created_at', 'display_line_items')
    fields = ('page_number', 'line_number', 'created_at', 'display_line_items')
    can_delete = False
    show_change_link = False
    classes = ['collapse']  # Makes this inline collapsible

    def display_line_items(self, obj):
        """
        Displays associated line item key-value pairs for each line as HTML.
        """
        if not obj.pk:
            return "-"
        items = obj.values.all()  # 'values' is the related_name for FactAICDocLineItem
        if not items:
            return "-"
        html = "<table style='border-collapse: collapse; width: 100%;'>"
        html += "<tr><th style='border: 1px solid #ccc; padding: 4px;'>Key</th><th style='border: 1px solid #ccc; padding: 4px;'>Value</th></tr>"
        for item in items:
            html += f"<tr><td style='border: 1px solid #ccc; padding: 4px;'>{item.key}</td><td style='border: 1px solid #ccc; padding: 4px;'>{item.value}</td></tr>"
        html += "</table>"
        return format_html(html)

    display_line_items.short_description = "Line Item Values"
    display_line_items.allow_tags = True

class FactAICDocCheckItemInline(admin.TabularInline):
    model = FactAICDocCheckItem
    extra = 0
    fields = ('amount', 'payee', 'memo', 'clearing_date', 'passing_date', 'check_number', 'created_at')
    readonly_fields = ('amount', 'payee', 'memo', 'clearing_date', 'passing_date', 'check_number', 'created_at')
    can_delete = False
    show_change_link = False
    classes = ['collapse']  # Makes this inline collapsible

@admin.register(DimAICDocument)
class DimAICDocumentAdmin(admin.ModelAdmin):
    list_display = ('doc_id', 'doc_typ', 'file_format', 'upload_stat', 'input_user', 'created_at')
    readonly_fields = ('doc_id', 'created_at')

    fieldsets = (
        (None, {
            'fields': ('doc_id', 'doc_typ', 'file_format', 'upload_stat', 'input_user', 'file')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
        }),
    )

    inlines = [
        FactAICDocKeyItemInline,
        FactAICDocLineInline,
        FactAICDocCheckItemInline,  # Attach check items as collapsible inline
    ]

@admin.register(FactAICDocCheckItem)
class FactAICDocCheckItemAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'doc', 'amount', 'payee', 'memo', 'clearing_date',
        'passing_date', 'check_number', 'created_at'
    )
    search_fields = ('payee', 'check_number', 'amount')
    list_filter = ('clearing_date', 'passing_date', 'created_at')
    readonly_fields = ('created_at',)