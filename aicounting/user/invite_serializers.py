
from rest_framework import serializers
from user.services import create_customer

class AzureInviteCustomerSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def create(self, validated_data):
        email = validated_data["email"]

        system_user = None
        request_user = self.context.get('request').user

        system_user = create_customer(
            request_user,
            customer_name=email.split('@')[1].capitalize(),
            email=email,
        )
        
        return system_user