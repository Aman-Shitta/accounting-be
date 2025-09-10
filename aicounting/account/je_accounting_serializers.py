
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from .models import FactAICJETemplateHeaderSnapshot

from account.serializers import DimAICGLAcctSerializer

class BankTemplateDataSerializer(serializers.Serializer):
    gl_account = DimAICGLAcctSerializer(allow_null=True)
    offset_gl_account = DimAICGLAcctSerializer(allow_null=True)
    debit = serializers.CharField()
    credit = serializers.CharField()

class JETemplateDataSerializer(serializers.ModelSerializer):
    """Serializer for JE Template Data"""

    class Meta:
        model = FactAICJETemplateHeaderSnapshot
        fields = ['id', 'je_name', 'je_refrence', 'je_freq', 'is_object']

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        if instance.attribute_snapshots.count() != 1:
            ret['attributes'] = []
            return ret

        star_attribute_snapshot = instance.attribute_snapshots.first()

        input_file_attribute = star_attribute_snapshot.input_file_attribute
        input_file_snapshot = input_file_attribute.input_file_snapshot

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
                    "gl_account": item.gl_account,
                    "offset_gl_account": item.offset_gl_account,
                    "debit": item.debit_amount,
                    "credit": item.credit_amount,
                })

            ret['attributes'] = BankTemplateDataSerializer(attributes_data, many=True).data
        else:
            raise ValidationError(
                    {'detail': 'Document Type not yet supported.'}
                )

        return ret