"""Request and response shapes for the auth endpoints."""

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from v1.tenancy.models import FirmMembership

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["email"].strip().lower(),
            password=attrs["password"],
        )
        if user is None:
            # One message for every failure mode, so the endpoint cannot be
            # used to tell "no such account" from "wrong password".
            raise serializers.ValidationError("Incorrect email or password.")

        attrs["user"] = user
        return attrs


class SetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=FirmMembership.Role.choices)
    first_name = serializers.CharField(required=False, allow_blank=True, default="")
    last_name = serializers.CharField(required=False, allow_blank=True, default="")


class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    is_verified = serializers.BooleanField(source="user.profile.is_verified", read_only=True)
    firm_name = serializers.CharField(source="firm.name", read_only=True, default=None)

    class Meta:
        model = FirmMembership
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "firm",
            "firm_name",
            "is_active",
            "is_verified",
            "created_at",
        ]
        read_only_fields = fields


class WhoAmISerializer(serializers.Serializer):
    """The caller's identity and what they can reach."""

    id = serializers.IntegerField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    is_verified = serializers.BooleanField()
    memberships = MembershipSerializer(many=True)
    client_count = serializers.IntegerField()
