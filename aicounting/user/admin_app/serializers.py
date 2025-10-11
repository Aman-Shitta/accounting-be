
from rest_framework import serializers
from user.models import DimAICCustomer


class AdminLoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, required=True)
    password = serializers.CharField(write_only=True, required=True)

    def validate_username(self, value):
        if not value:
            raise serializers.ValidationError("Username is required.")
        return value

    def validate_password(self, value):
        if not value:
            raise serializers.ValidationError("Password is required.")
        return value


class CustomerStatisticsSerializer(serializers.Serializer):
    total_customers = serializers.IntegerField()
    verified_customers = serializers.IntegerField()
    pending_customers = serializers.IntegerField()
    verification_rate = serializers.FloatField()


class RecentCustomerSerializer(serializers.ModelSerializer):
    email = serializers.CharField(source='system_user.email')
    is_active = serializers.BooleanField(source='system_user.is_active')
    date_joined = serializers.DateTimeField(source='system_user.date_joined')
    verification_status = serializers.SerializerMethodField()

    class Meta:
        model = DimAICCustomer
        fields = [
            'id', 'customer_name', 'email', 'is_active',
            'date_joined', 'verification_status'
        ]

    def get_verification_status(self, obj):
        return 'verified' if obj.system_user.is_active else 'pending'


class AdminDashboardSerializer(serializers.Serializer):
    statistics = CustomerStatisticsSerializer()
    recent_customers = RecentCustomerSerializer(many=True)


class CustomerDetailSerializer(serializers.ModelSerializer):
    email = serializers.CharField(source='system_user.email')
    is_active = serializers.BooleanField(source='system_user.is_active')
    date_joined = serializers.DateTimeField(source='system_user.date_joined')
    verification_status = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = DimAICCustomer
        fields = [
            'customer_id', 'customer_name', 'email', 'street', 'city',
            'state_abrevation', 'zip_code', 'verification_status',
            'is_active', 'date_joined', 'created_by'
        ]

    def get_verification_status(self, obj):
        return 'verified' if obj.system_user.is_active else 'pending'

    def get_created_by(self, obj):
        return obj.input_user.username if obj.input_user else None

