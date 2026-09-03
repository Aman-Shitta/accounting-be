"""Document sources, extraction fields, journal templates and config versions."""

from rest_framework import serializers

from v1.configuration.models import (
    ConfigVersion,
    DocumentSource,
    DocumentType,
    ExtractionField,
    JournalTemplate,
    JournalTemplateLine,
)


class ExtractionFieldSerializer(serializers.ModelSerializer):
    ledger_account_number = serializers.CharField(
        source="ledger_account.account_number", read_only=True, default=None
    )

    class Meta:
        model = ExtractionField
        fields = [
            "id",
            "key",
            "label",
            "prompt_hint",
            "direction",
            "ledger_account",
            "ledger_account_number",
            "offset_ledger_account",
            "position",
        ]
        read_only_fields = ["id", "ledger_account_number"]


class DocumentSourceSerializer(serializers.ModelSerializer):
    fields_ = ExtractionFieldSerializer(source="fields", many=True, read_only=True)
    is_transactional = serializers.BooleanField(read_only=True)
    field_count = serializers.IntegerField(source="fields.count", read_only=True)

    class Meta:
        model = DocumentSource
        fields = [
            "id",
            "name",
            "document_type",
            "is_transactional",
            "ledger_account",
            "default_offset_account",
            "extraction_notes",
            "reference_file",
            "is_active",
            "fields_",
            "field_count",
            "created_at",
        ]
        read_only_fields = ["id", "is_transactional", "fields_", "field_count", "created_at"]

    def validate(self, attrs):
        """
        A transactional source has nothing to configure per field, and needs the
        account the statement represents. A field-configured one is the reverse.
        """
        document_type = attrs.get(
            "document_type", getattr(self.instance, "document_type", None)
        )

        if document_type in DocumentType.transactional():
            if self.instance and self.instance.fields.exists():
                raise serializers.ValidationError(
                    {
                        "document_type": (
                            "This source has extraction fields, which a transaction "
                            "list cannot use. Remove them before changing the type."
                        )
                    }
                )

        return attrs


class JournalTemplateLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalTemplateLine
        fields = [
            "id",
            "side",
            "amount_source",
            "extraction_field",
            "fixed_amount",
            "ledger_account",
            "label",
            "comment",
            "position",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        source = attrs.get("amount_source", getattr(self.instance, "amount_source", None))

        if source == JournalTemplateLine.AmountSource.EXTRACTED_FIELD and not attrs.get(
            "extraction_field", getattr(self.instance, "extraction_field", None)
        ):
            raise serializers.ValidationError(
                {"extraction_field": "Required when the amount comes from an extracted field."}
            )

        if source == JournalTemplateLine.AmountSource.FIXED and attrs.get(
            "fixed_amount", getattr(self.instance, "fixed_amount", None)
        ) is None:
            raise serializers.ValidationError(
                {"fixed_amount": "Required when the amount is fixed."}
            )

        return attrs


class JournalTemplateSerializer(serializers.ModelSerializer):
    lines = JournalTemplateLineSerializer(many=True, read_only=True)

    class Meta:
        model = JournalTemplate
        fields = [
            "id",
            "name",
            "reference",
            "frequency",
            "entry_type",
            "uses_extracted_fields",
            "description",
            "sources",
            "lines",
            "created_at",
        ]
        read_only_fields = ["id", "lines", "created_at"]


class ConfigVersionSerializer(serializers.ModelSerializer):
    published_by_email = serializers.EmailField(
        source="published_by.email", read_only=True, default=None
    )

    class Meta:
        model = ConfigVersion
        fields = ["id", "version", "payload", "published_at", "published_by_email"]
        read_only_fields = fields


class ConfigVersionSummarySerializer(serializers.ModelSerializer):
    """Version history without the payload, which is large."""

    published_by_email = serializers.EmailField(
        source="published_by.email", read_only=True, default=None
    )
    source_count = serializers.SerializerMethodField()

    class Meta:
        model = ConfigVersion
        fields = ["id", "version", "published_at", "published_by_email", "source_count"]
        read_only_fields = fields

    def get_source_count(self, obj) -> int:
        return len(obj.payload.get("document_sources", []))
