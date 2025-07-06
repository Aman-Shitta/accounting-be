from rest_framework import serializers

from django.db import transaction
from django.db.models import F

from django.core.files.storage import default_storage

from document.models import (
    DimAICDocument,
    FactAICDocKeyItem,
    FactAICDocLine,
    FactAICDocLineItem
)

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
            line_items = line_items_by_page.get(page, {})

            # Sort line numbers by int
            sorted_line_items = {
                k: line_items[k] for k in sorted(line_items.keys())
            }

            data[page] = {
                "key_items": key_items_by_page.get(page, {}),
                "line_items": sorted_line_items
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


class LineItemCreateSerializer(serializers.Serializer):
    page_number = serializers.IntegerField()
    line_number = serializers.IntegerField()
    # dynamic keys handled in validate()

    def to_internal_value(self, data):
        self.page_number = data.get('page_number')
        self.line_number = data.get('line_number')

        # Extract everything else as dynamic
        self.dynamic_fields = {
            k: v for k, v in data.items() if k not in ['page_number', 'line_number']
        }
        return data

    def validate(self, data):
        return data

    @transaction.atomic
    def save(self, **kwargs):
        doc = self.context.get('doc')
        page_number = self.page_number
        line_number = self.line_number
        dynamic_fields = self.dynamic_fields

        existing_lines = FactAICDocLine.objects.filter(doc=doc, page_number=page_number)

        if existing_lines.count() < line_number:
            line_number = existing_lines.count() + 1
        else:
            existing_lines.filter(line_number__gte=line_number).update(
                line_number=F('line_number') + 1
            )

        # Create line
        new_line = FactAICDocLine.objects.create(
            doc=doc,
            page_number=page_number,
            line_number=line_number
        )

        # Create items
        created_items = []
        for key, value in dynamic_fields.items():
            item = FactAICDocLineItem.objects.create(
                line=new_line,
                key=key,
                value=value
            )
            created_items.append({
                "id": item.id,
                "key": key,
                "value": value
            })

        return LineValueSerializer(created_items, many=True).data
 
