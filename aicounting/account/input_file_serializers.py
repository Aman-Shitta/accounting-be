from rest_framework import serializers

from account.models import DimAicInputFiles, DimAicInputFileAttributes
from user.models import DimAICClient
import logging

logger = logging.getLogger(__name__)


class InputFileAttributeSerializer(serializers.ModelSerializer):
    """Serializer for DimAicInputFileAttributes model"""
    
    # gl_account_name = serializers.CharField(source='gl_account.account_name', read_only=True)
    # offset_gl_account_name = serializers.CharField(source='offset_gl_account.account_name', read_only=True)
    
    class Meta:
        model = DimAicInputFileAttributes
        fields = [
            'id', 'name', 'gl_account', 'type', 
            'offset_gl_account', 'comments',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', ]
    
    def validate(self, attrs):
        """Validate that gl_account and offset_gl_account are different"""
        gl_account = attrs.get('gl_account')
        offset_gl_account = attrs.get('offset_gl_account')
        
        # Both can be null for bank statement and credit card types
        if gl_account and offset_gl_account and gl_account.id == offset_gl_account.id:
            raise serializers.ValidationError(
                "GL Account and Offset GL Account cannot be the same."
            )
        
        return attrs


class InputFileListSerializer(serializers.ModelSerializer):
    """Serializer for listing input files (minimal data)"""
    
    class Meta:
        model = DimAicInputFiles
        fields = ['id', 'name', 'file_type', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class InputFileBasicCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating input files without attributes"""
    
    offset_gl_account = serializers.IntegerField(required=False, write_only=True, help_text="Offset GL Account ID for bank/credit card statements")
    
    class Meta:
        model = DimAicInputFiles
        fields = [
            'name', 'file_type', 'file', 'description', 'offset_gl_account'
        ]
    
    def validate(self, attrs):
        """Validate offset_gl_account based on file_type"""
        file_type = attrs.get('file_type')
        offset_gl_account = attrs.get('offset_gl_account')
        
        # For bank statement and credit card, offset_gl_account is required
        if file_type in ['bank_statement', 'credit_card']:
            if not offset_gl_account:
                raise serializers.ValidationError({
                    'offset_gl_account': f'Offset GL Account is required for {file_type} files.'
                })
        
        return attrs
    
    def create(self, validated_data):
        """Create input file without attributes"""
        request_user = self.context['request'].user
        client_id = self.context['client_id']
        
        # Extract offset_gl_account from validated_data
        offset_gl_account_id = validated_data.pop('offset_gl_account', None)
        
        # Get the client instance
        try:
            client = DimAICClient.objects.get(id=client_id)
        except DimAICClient.DoesNotExist:
            raise serializers.ValidationError("Client not found.")
        
        # Create the input file
        input_file = DimAicInputFiles.objects.create(
            client=client,
            input_user=request_user,
            **validated_data
        )
        
        # If file type is bank_statement or credit_card, create default attribute
        if input_file.file_type in ['bank_statement', 'credit_card']:
            # Validate that the offset GL account exists
            from account.models.dim_aic_gl_acct_model import DimAICGLAcct
            try:
                offset_gl_account = DimAICGLAcct.objects.get(
                    id=offset_gl_account_id,
                    customer__system_user=request_user    
                )
            except DimAICGLAcct.DoesNotExist:
                raise serializers.ValidationError({
                    'offset_gl_account': 'Invalid offset GL account ID.'
                })
            
            DimAicInputFileAttributes.objects.create(
                input_file=input_file,
                name="*",  # Default name
                gl_account=None,  # Null GL account for bank/credit card statements
                type="",  # Empty type initially
                offset_gl_account=offset_gl_account,  # Required offset GL account
                input_user=request_user,
                comments="Auto-generated for bank statement/credit card processing"
            )
        
        return input_file


class InputFileBasicUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating input files without attributes"""
    
    class Meta:
        model = DimAicInputFiles
        fields = [
            'name', 'description',
        ]
    
    def update(self, instance, validated_data):
        """Update input file basic information"""

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        return instance


class InputFileDetailSerializer(serializers.ModelSerializer):
    """Serializer for detailed input file view with attributes"""
    
    client_name = serializers.CharField(source='client.client_name', read_only=True)
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = DimAicInputFiles
        fields = [
            'id', 'name', 'file_type', 'file_url', 'client_name', 'description',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_file_url(self, obj):
        """Get secure URL for the file"""
        if obj.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
        return None


class AttributeCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating individual attributes"""
    
    class Meta:
        model = DimAicInputFileAttributes
        fields = [
            'name', 'gl_account', 'type', 'offset_gl_account', 'comments'
        ]
    
    def validate(self, attrs):
        """Validate input file attributes based on file type"""
        gl_account = attrs.get('gl_account')
        offset_gl_account = attrs.get('offset_gl_account')
        
        # Get the input file from context if available
        input_file = self.context.get('input_file')
        
        # If we have input file context, check file type
        if input_file:
            # For bank statements and credit cards, GL accounts can be null
            if input_file.file_type in ['bank_statement', 'credit_card']:
                # Both can be null for bank statement and credit card types
                if gl_account and offset_gl_account and gl_account.id == offset_gl_account.id:
                    raise serializers.ValidationError(
                        "GL Account and Offset GL Account cannot be the same."
                    )
            else:
                # For other file types, both accounts are typically required
                # (though we allow nulls at model level for flexibility)
                if gl_account and offset_gl_account and gl_account.id == offset_gl_account.id:
                    raise serializers.ValidationError(
                        "GL Account and Offset GL Account cannot be the same."
                    )
        else:
            # General validation when context is not available
            if gl_account and offset_gl_account and gl_account.id == offset_gl_account.id:
                raise serializers.ValidationError(
                    "GL Account and Offset GL Account cannot be the same."
                )
        
        return attrs


# class AttributeUpdateSerializer(serializers.ModelSerializer):
#     """Serializer for updating individual attributes"""
    
#     class Meta:
#         model = DimAicInputFileAttributes
#         fields = [
#             'name', 'gl_account', 'type', 'offset_gl_account', 'comments'
#         ]
    
#     def validate(self, attrs):
#         """Validate that gl_account and offset_gl_account are different"""
#         gl_account = attrs.get('gl_account', self.instance.gl_account)
#         offset_gl_account = attrs.get('offset_gl_account', self.instance.offset_gl_account)
        
#         if gl_account and offset_gl_account and gl_account.id == offset_gl_account.id:
#             raise serializers.ValidationError(
#                 "GL Account and Offset GL Account cannot be the same."
#             )
        
#         return attrs
