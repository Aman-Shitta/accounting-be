"""Periods, documents and everything extracted within one."""

from rest_framework import serializers

from v1.periods.models import (
    AccountingPeriod,
    PeriodCheckDetail,
    PeriodDocument,
    PeriodFieldValue,
    PeriodTransaction,
)


class PeriodDocumentSummarySerializer(serializers.ModelSerializer):
    transaction_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = PeriodDocument
        fields = [
            "id",
            "source_key",
            "source_name",
            "document_type",
            "status",
            "file",
            "transaction_count",
            "assigned_reviewer",
            "updated_at",
        ]
        read_only_fields = fields


class PeriodDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PeriodDocument
        fields = [
            "id",
            "period",
            "source_key",
            "source_name",
            "document_type",
            "status",
            "file",
            "uploaded_by",
            "failure_reason",
            "assigned_reviewer",
            "review_notes",
            "balance_mismatch_details",
            "control_totals",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            f for f in fields if f not in ("file", "review_notes")
        ]


class AccountingPeriodSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    config_version_number = serializers.IntegerField(
        source="config_version.version", read_only=True
    )
    documents = PeriodDocumentSummarySerializer(many=True, read_only=True)

    class Meta:
        model = AccountingPeriod
        fields = [
            "id",
            "client",
            "client_name",
            "year",
            "month",
            "status",
            "config_version",
            "config_version_number",
            "documents",
            "created_by",
            "created_at",
            "completed_at",
        ]
        read_only_fields = [
            "id",
            "client",
            "client_name",
            "config_version",
            "config_version_number",
            "documents",
            "created_by",
            "created_at",
            "completed_at",
        ]


class OpenPeriodSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    month = serializers.IntegerField(min_value=1, max_value=12)


class PeriodTransactionSerializer(serializers.ModelSerializer):
    ledger_account_number = serializers.CharField(
        source="ledger_account.account_number", read_only=True, default=None
    )
    ledger_account_name = serializers.CharField(
        source="ledger_account.name", read_only=True, default=None
    )

    class Meta:
        model = PeriodTransaction
        fields = [
            "id",
            "page_number",
            "line_number",
            "transaction_date",
            "raw_date",
            "description",
            "amount",
            "direction",
            "ledger_account",
            "ledger_account_number",
            "ledger_account_name",
            "offset_ledger_account",
            "is_check",
            "check_number",
            "classified_at",
            "is_manually_classified",
        ]
        read_only_fields = [
            "id",
            "raw_date",
            "ledger_account_number",
            "ledger_account_name",
            "classified_at",
            "is_manually_classified",
        ]

    def update(self, instance, validated_data):
        """A human touching the account overrides whatever the classifier chose."""
        if "ledger_account" in validated_data:
            validated_data["is_manually_classified"] = True
        return super().update(instance, validated_data)


class PeriodCheckDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = PeriodCheckDetail
        fields = [
            "id",
            "transaction",
            "page_number",
            "check_number",
            "amount",
            "payee",
            "memo",
            "cleared_on",
        ]
        read_only_fields = ["id"]


class PeriodFieldValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = PeriodFieldValue
        fields = [
            "id",
            "field_key",
            "field_label",
            "page_number",
            "value",
            "direction",
            "ledger_account",
            "offset_ledger_account",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "field_key",
            "field_label",
            "page_number",
            "direction",
            "updated_at",
        ]


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
