from rest_framework import serializers


class AzureInviteAccountantSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    user_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True)
    first_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True)
    last_name = serializers.CharField(
        max_length=100, required=False, allow_blank=True)

    def validate_email(self, value):
        """
        Validate email format and ensure it's not empty.
        """
        if not value:
            raise serializers.ValidationError("Email is required.")
        return value.lower()
