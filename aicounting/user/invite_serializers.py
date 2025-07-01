
from rest_framework import serializers
from django.contrib.auth import get_user_model
from user.models import DimAICCustomer

from user.services import create_customer_and_user


class CustomerInviteSerializer(serializers.Serializer):

    class Meta:
        model = DimAICCustomer

    customer_name = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)

    street = serializers.CharField(required=False, allow_blank=True, default='')
    city = serializers.CharField(required=False, allow_blank=True, default='')
    street_abrevation = serializers.CharField(required=False, allow_blank=True, default='')
    zip_code = serializers.IntegerField(required=False, allow_null=True)

    def validate_email(self, value):
        User = get_user_model()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
    
    def create(self, validated_data):
        """
        Handles the creation of the Django user and DimAICCustomer instance.
        """
        request_user = self.context.get("request").user
        
        customer, invite_token = create_customer_and_user(
            customer_name=validated_data["customer_name"],
            email=validated_data["email"],
            street=validated_data.get("street", ""),
            city=validated_data.get("city", ""),
            street_abrevation=validated_data.get("street_abrevation", ""),
            zip_code=validated_data.get("zip_code"),
            input_user=request_user
        )

        return customer, invite_token