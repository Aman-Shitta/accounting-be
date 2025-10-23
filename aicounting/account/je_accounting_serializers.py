
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from .models import FactAICJETemplateHeaderSnapshot

from account.serializers import DimAICGLAcctSerializer

class JETemplateAttributeDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    gl_account = DimAICGLAcctSerializer(allow_null=True)
    offset_gl_account = DimAICGLAcctSerializer(allow_null=True)
    description = serializers.CharField()
    date = serializers.CharField()
    debit = serializers.CharField()
    credit = serializers.CharField()

class JETemplateDataSerializer(serializers.ModelSerializer):
    """Serializer for JE Template Data"""

    class Meta:
        model = FactAICJETemplateHeaderSnapshot
        fields = ['id', 'je_name', 'je_refrence', 'je_freq', 'is_object']

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        # For bank statements and credit cards that only 1 attribite *
        if instance.attribute_snapshots.count() == 1:
            star_attribute_snapshot = instance.attribute_snapshots.first()
            input_file_attribute = star_attribute_snapshot.input_file_attribute
            input_file_snapshot = input_file_attribute.input_file_snapshot

            if not input_file_snapshot:
                ret['attributes'] = []
                return ret

            if input_file_snapshot.file_type in ['bank_statement', 'credit_card']:
                bank_documents = input_file_snapshot.extraction_documents.all()
                if not bank_documents.exists():
                    ret['attributes'] = []
                    return ret

                bank_document = bank_documents.first()

                if bank_document.status != 'verified':
                    raise ValidationError(
                        {'detail': 'Extracted data needs to be verified to get the template data.'}
                    )

                from .models.monthly_document_line_models import MonthlyDocumentBankLineItem

                items = MonthlyDocumentBankLineItem.objects.filter(
                    document=bank_document
                ).select_related('gl_account', 'offset_gl_account')

                attributes_data = []
                for item in items:
                    attributes_data.append({
                        "id": item.id,
                        "gl_account": item.gl_account,
                        "offset_gl_account": item.offset_gl_account,
                        "description": item.description,
                        "date": item.date,
                        "debit": item.amount if item.transaction_type == "debit" else "",
                        "credit": item.amount if item.transaction_type == "credit" else "",
                    })

        else:
            # Handle non-bank document types (sales, etc.)

            # For templates with multiple attributes, use the input_file directly
            input_file_snapshot = instance.input_files.all()

            if not input_file_snapshot:
                attributes = instance.attribute_snapshots.all()
                attributes_data = [
                    {
                        "id": attr.id,
                        "gl_account": DimAICGLAcctSerializer(attr.gl_account).data,
                        "offset_gl_account": None,
                        "description": attr.attribute_name or (attr.input_file_attribute.name if attr.input_file_attribute else '<Manual>'),
                        "date": None,
                        "debit": attr.debit,
                        "credit": attr.credit,
                    }
                    for attr in attributes
                ]

            attributes_data = []
            for ifs in input_file_snapshot:
                documents = ifs.extraction_documents.all()
                if not documents.exists():
                    ret['attributes'] = []
                    return ret

                document = documents.first()

                # Check if the JE template is_object
                if instance.is_object:
                    # For is_object templates, get values from extracted attribute items
                    from .models.monthly_document_line_models import MonthlyDocumentAttributeItem
                    
                    attribute_items = MonthlyDocumentAttributeItem.objects.filter(
                        document=document
                    ).select_related('attribute', 'gl_account', 'offset_gl_account')

                    for item in attribute_items:
                        attributes_data.append({
                            "id": item.id,
                            "gl_account": item.gl_account,
                            "offset_gl_account": item.offset_gl_account, 
                            "description": item.attribute.name if item.attribute else 'Unknown Attribute',
                            "date": None,  # Attributes don't have dates
                            "debit": item.value if item.transaction_type == "debit" else "",
                            "credit": item.value if item.transaction_type == "credit" else "",
                        })

                        # balance the transaction by adding an offset entry
                        # for object data is always coming from attribure items
                        # so we can safely add the offset entry here
                        attributes_data.append({
                            "id": item.id,
                            "gl_account": item.offset_gl_account,
                            "offset_gl_account": item.gl_account, 
                            "description": item.attribute.name if item.attribute else 'Unknown Attribute',
                            "date": None,  # Attributes don't have dates
                            "credit": item.value if item.transaction_type == "debit" else "",
                            "debit": item.value if item.transaction_type == "credit" else "",
                        })

                else:
                    # For non-is_object templates, get attribute values but use GL account from JE template
                    from .models.monthly_document_line_models import MonthlyDocumentAttributeItem
                    
                    # Get all template attribute snapshots
                    template_attributes = instance.attribute_snapshots.all()
                    
                    attributes_data = []
                    for template_attr in template_attributes:
                        # Find corresponding attribute item value
                        attribute_value = ""
                        attribute_offset_gl = None
                        if template_attr.input_file_attribute:
                            # Find the extracted attribute item
                            try:
                                attr_item = MonthlyDocumentAttributeItem.objects.get(
                                    document=document,
                                    attribute=template_attr.input_file_attribute
                                )

                                attribute_value = attr_item.value or ""
                                attribute_offset_gl = attr_item.offset_gl_account
                            except MonthlyDocumentAttributeItem.DoesNotExist:
                                attribute_value = ""
                                attribute_offset_gl = None

                        # Use GL account from JE template, not from attribute item
                        attributes_data.append({
                            "id": template_attr.pk,
                            "gl_account": template_attr.gl_account,
                            "offset_gl_account": attribute_offset_gl,
                            "description": template_attr.attribute_name or (template_attr.input_file_attribute.name if template_attr.input_file_attribute else '<Manual>'),
                            "date": None,  # Attributes don't have dates
                            "debit": attribute_value if template_attr.debit else "",
                            "credit": attribute_value if template_attr.credit else "",
                        })

        ret['attributes'] = JETemplateAttributeDataSerializer(attributes_data, many=True).data

        return ret


class ManualValueItem(serializers.Serializer):
    """Individual manual value entry"""
    attribute_id = serializers.IntegerField(required=True)
    value = serializers.FloatField(required=True)

class ManualValueUpdateSerializer(serializers.Serializer):
    """Serializer for updating multiple manual values in JE templates at once"""
    values = serializers.ListField(
        child=ManualValueItem(),
        required=True,
        allow_empty=False
    )

class JETemplateStatusUpdateSerializer(serializers.Serializer):
    """Serializer for updating JE template status"""
    status = serializers.CharField(
        required=True
    )

    def validate_status(self, value):
        allowed_statuses = ['verified']
        if value not in allowed_statuses:
            raise serializers.ValidationError(f"Status must be one of {allowed_statuses}.")
        return value

