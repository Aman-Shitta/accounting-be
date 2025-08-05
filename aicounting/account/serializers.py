from rest_framework import serializers
from account.models import DimAICGLAcct


class DimAICGLAcctSerializer(serializers.ModelSerializer):
    """Serializer for DimAICGLAcct model"""
    

    class Meta:
        model = DimAICGLAcct
        fields = [
            'id', 'account_number', 'account_name', 'description',
            'account_class', 'sub_class',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


