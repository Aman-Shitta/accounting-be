"""Chart of accounts."""

from rest_framework import serializers

from v1.ledger.models import ClientClassifierProfile, LedgerAccount, LedgerAccountType


class LedgerAccountTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerAccountType
        fields = ["id", "code", "name", "description"]
        read_only_fields = ["id"]


class LedgerAccountSerializer(serializers.ModelSerializer):
    account_type_name = serializers.CharField(source="account_type.name", read_only=True)

    class Meta:
        model = LedgerAccount
        fields = [
            "id",
            "account_number",
            "name",
            "description",
            "account_class",
            "sub_class",
            "account_type",
            "account_type_name",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "account_type_name", "created_at"]

    def validate_account_number(self, value):
        client = self.context.get("client")
        if client is None:
            return value

        clash = LedgerAccount.objects.filter(client=client, account_number=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)

        if clash.exists():
            raise serializers.ValidationError(
                f"This client already has account {value}."
            )
        return value


class ClientClassifierProfileSerializer(serializers.ModelSerializer):
    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = ClientClassifierProfile
        fields = [
            "id",
            "assistant_id",
            "vector_store_id",
            "model_name",
            "special_rules",
            "is_active",
            "is_usable",
            "updated_at",
        ]
        read_only_fields = ["id", "assistant_id", "vector_store_id", "is_usable", "updated_at"]
