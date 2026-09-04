"""Firms, clients, contacts and reference documents."""

from rest_framework import serializers

from v1.tenancy.models import (
    Client,
    ClientAssignment,
    ClientContact,
    ClientReferenceDocument,
    Firm,
    FirmMembership,
)


class FirmSerializer(serializers.ModelSerializer):
    client_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Firm
        fields = [
            "id",
            "name",
            "public_id",
            "street",
            "city",
            "state",
            "postal_code",
            "extraction_provider",
            "is_active",
            "client_count",
            "created_at",
        ]
        read_only_fields = ["id", "public_id", "is_active", "client_count", "created_at"]


class ClientContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientContact
        fields = ["id", "name", "title", "email", "phone", "is_primary", "created_at"]
        read_only_fields = ["id", "created_at"]


class ClientSerializer(serializers.ModelSerializer):
    contacts = ClientContactSerializer(many=True, read_only=True)
    firm_name = serializers.CharField(source="firm.name", read_only=True)

    class Meta:
        model = Client
        fields = [
            "id",
            "firm",
            "firm_name",
            "name",
            "external_ref",
            "street",
            "city",
            "state",
            "postal_code",
            "allow_review",
            "contacts",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "firm", "firm_name", "contacts", "created_at", "updated_at"]

    def validate_external_ref(self, value):
        """Unique per firm, not globally — two firms may both use "ACME"."""
        firm = self.context.get("firm")
        if firm is None:
            return value

        clash = Client.objects.filter(firm=firm, external_ref=value, is_deleted=False)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)

        if clash.exists():
            raise serializers.ValidationError(
                f"Your firm already has a client with the reference '{value}'."
            )
        return value


class ClientReferenceDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientReferenceDocument
        fields = ["id", "kind", "file", "uploaded_by", "created_at"]
        read_only_fields = ["id", "uploaded_by", "created_at"]


class ClientAssignmentSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="membership.user.email", read_only=True)
    role = serializers.CharField(source="membership.role", read_only=True)

    class Meta:
        model = ClientAssignment
        fields = ["id", "membership", "email", "role", "assigned_by", "created_at"]
        read_only_fields = ["id", "email", "role", "assigned_by", "created_at"]

    def validate_membership(self, membership: FirmMembership):
        client = self.context.get("client")
        if client and membership.firm_id and membership.firm_id != client.firm_id:
            raise serializers.ValidationError(
                "That person belongs to a different firm."
            )
        return membership
