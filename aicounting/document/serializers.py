from rest_framework import serializers
from document.models import (
    DimAICDocument,
    FactAICDocKeyItem,
    FactAICDocLine,
    FactAICDocLineItem
)

from django.core.files.storage import default_storage


class DocumentListSerializer(serializers.ModelSerializer):

    created_at = serializers.SerializerMethodField()
    doc_type = serializers.SerializerMethodField()

    class Meta:
        model = DimAICDocument
        fields = ['doc_id', 'upload_stat', 'doc_type', 'created_at']


    def get_created_at(self, instance):
        return instance.created_at.date()

    def get_doc_type(self, instance):
        return instance.doc_typ



class DocumentDataSerializer(serializers.ModelSerializer):
    extracted_data = serializers.SerializerMethodField()
    document_url = serializers.SerializerMethodField()

    class Meta:
        model = DimAICDocument
        fields = ["doc_id", "doc_typ", "created_at", "input_user", "extracted_data", "document_url"]


    def get_document_url(self, obj):
        return default_storage.url(obj.file_loc)

    def get_extracted_data(self, obj):
        data = {}

        # Prepare key items grouped by page
        key_items_by_page = {}
        for item in obj.key_items.all():
            page = str(item.page_number)
            if page not in key_items_by_page:
                key_items_by_page[page] = {}
            key_items_by_page[page][item.key] = item.value

        # Prepare line items grouped by page and line
        line_items_by_page = {}
        for line in obj.line_rows.all():
            page = str(line.page_number)
            line_num = str(line.line_number)

            if page not in line_items_by_page:
                line_items_by_page[page] = {}

            if line_num not in line_items_by_page[page]:
                line_items_by_page[page][line_num] = {}

            for val in line.values.all():
                line_items_by_page[page][line_num][val.key] = val.value

        # Combine key and line items per page
        all_pages = set(key_items_by_page.keys()) | set(line_items_by_page.keys())
        for page in all_pages:
            data[page] = {
                "key_items": key_items_by_page.get(page, {}),
                "line_items": line_items_by_page.get(page, {})
            }

        return data




