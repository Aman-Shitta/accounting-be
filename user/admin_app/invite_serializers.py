
from rest_framework import serializers


class AzureInviteCustomerSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    customer_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True)
    street = serializers.CharField(
        max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(
        max_length=100, required=False, allow_blank=True)
    state_abrevation = serializers.CharField(
        max_length=2, required=False, allow_blank=True)
    zip_code = serializers.IntegerField(required=False, allow_null=True)

    def validate_email(self, value):
        """
        Validate email format and ensure it's not empty.
        """
        if not value:
            raise serializers.ValidationError("Email is required.")
        return value.lower()

    def validate_customer_name(self, value):
        """
        If customer_name is not provided, generate it from email domain.
        """
        if not value:
            # This will be handled in the view if needed
            return ""
        return value

    def validate_zip_code(self, value):
        """
        Validate zip code if provided.
        """
        if value is not None and (value < 0 or value > 99999):
            raise serializers.ValidationError("Invalid zip code.")
        return value
