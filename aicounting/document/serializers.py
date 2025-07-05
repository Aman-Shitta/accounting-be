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



class KeyItemSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = FactAICDocKeyItem
        fields = ["id", "page_number", "key", "value"]


class LineValueSerializer(serializers.ModelSerializer):

    class Meta:
        model = FactAICDocLineItem
        fields = ["key", "value"]


class LineRowSerializer(serializers.ModelSerializer):
    # id = serializers.IntegerField(read_only=True)
    values = LineValueSerializer(many=True, read_only=True)

    class Meta:
        model = FactAICDocLine
        fields = ["id", "page_number", "line_number", "values"]

class DocumentDataSerializer(serializers.ModelSerializer):
    extracted_data = serializers.SerializerMethodField()
    document_url = serializers.SerializerMethodField()
    control_total = serializers.JSONField(source='control_item', read_only=True)
    upload_status = serializers.CharField(source='upload_stat', read_only=True)
    doc_type = serializers.CharField(source='doc_typ', read_only=True)

    class Meta:
        model = DimAICDocument
        fields = ["doc_id", "doc_type", "created_at", "input_user", "extracted_data", "document_url", "control_total", "upload_status"]

    def get_document_url(self, obj):
        return default_storage.url(obj.file_loc)

    def get_extracted_data(self, obj):
        data = {}

        # Serialize using DRF
        key_items = KeyItemSerializer(obj.key_items.all(), many=True).data
        line_rows = LineRowSerializer(obj.line_rows.all(), many=True).data

        # Group key items by page
        key_items_by_page = {}
        for item in key_items:
            page = item["page_number"]
            key_items_by_page.setdefault(page, {})[item["key"]] = item["value"]

        # Group line items by page and line
        line_items_by_page = {}
        for row in line_rows:
            page = row["page_number"]
            line = row["line_number"]
            line_dict = {"id": row["id"]}

            for val in row["values"]:
                line_dict[val["key"]] = val["value"]

            line_items_by_page.setdefault(page, {})[line] = line_dict

        # Combine both into the final structure
        all_pages = set(key_items_by_page.keys()) | set(line_items_by_page.keys())
        for page in sorted(all_pages, key=int):
            data[page] = {
                "key_items": key_items_by_page.get(page, {}),
                "line_items": line_items_by_page.get(page, {})
            }

        return data


class LineUpdateModelSerializer(serializers.ModelSerializer):

    class Meta:
        model = FactAICDocLine
        fields = ['id']

    def to_internal_value(self, data):

        return data

    def update(self, instance, validated_data):
        updated_items = []
        skipped_keys = []

        existing_items = {item.key: item for item in instance.values.all()}

        for key, new_value in validated_data.items():
            if key in existing_items:
                item_obj = existing_items[key]
                item_obj.value = new_value
                item_obj.save()
                updated_items.append(item_obj)
            else:
                skipped_keys.append(key)

        return {
            "updated": LineValueSerializer(updated_items, many=True).data,
            "skipped_keys": skipped_keys
        }
