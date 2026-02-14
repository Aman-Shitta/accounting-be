from rest_framework import serializers

from account.models import FactAICMonthlyAccounting


class MonthlyAccountingCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new monthly accounting session
    """
    month = serializers.IntegerField(
        min_value=1,
        max_value=12,
        help_text="Month (1-12)"
    )
    year = serializers.IntegerField(
        min_value=2000,
        max_value=2100,
        help_text="Year (e.g., 2025)"
    )


class MonthlyAccountingSerializer(serializers.ModelSerializer):
    """
    Serializer for displaying monthly accounting sessions
    """
    created_by = serializers.CharField(
        source='created_by.username', read_only=True)
    month = serializers.SerializerMethodField(read_only=True)

    def get_month(self, obj):
        """Get the month name from the model method"""
        return obj.get_month_name()

    class Meta:
        model = FactAICMonthlyAccounting
        fields = [
            'id',
            'month',
            'year',
            'status',
            'created_by',
            'created_at',
            'completed_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at']


class MonthlyAccountingDetailSerializer(MonthlyAccountingSerializer):
    """
    Detailed serializer for monthly accounting - same as basic for now
    """
    pass
