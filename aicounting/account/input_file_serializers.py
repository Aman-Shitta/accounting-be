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
            'id', 'name', 'gl_account', 'gl_account', 'type', 
            'offset_gl_account', 'offset_gl_account', 'comments',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', ]
    
    def validate(self, attrs):
        """Validate that gl_account and offset_gl_account are different"""
        gl_account = attrs.get('gl_account')
        offset_gl_account = attrs.get('offset_gl_account')
        
        if gl_account and offset_gl_account and gl_account.id == offset_gl_account.id:
            raise serializers.ValidationError(
                "GL Account and Offset GL Account cannot be the same."
            )
        
        return attrs


class InputFileListSerializer(serializers.ModelSerializer):
    """Serializer for listing input files (minimal data)"""
    
    class Meta:
        model = DimAicInputFiles
        fields = ['id', 'name', 'file_type', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class InputFileBasicCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating input files without attributes"""
    
    class Meta:
        model = DimAicInputFiles
        fields = [
            'name', 'file_type', 'file'
        ]
    
    def create(self, validated_data):
        """Create input file without attributes"""
        request_user = self.context['request'].user
        client_id = self.context['client_id']
        
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
        if validated_data['file_type'] in ['bank_statement', 'credit_card']:
            DimAicInputFileAttributes.objects.create(
                input_file=input_file,
                name="*",  # Default name
                gl_account=None,  # Empty GL account
                type="",  # Empty type
                offset_gl_account=None,  # Will be required to be set later
                input_user=request_user,
                comments="Auto-generated for bank statement/credit card processing"
            )
        
        return input_file


class InputFileBasicUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating input files without attributes"""
    
    class Meta:
        model = DimAicInputFiles
        fields = [
            'name', 'file_type', 'file'
        ]
    
    def update(self, instance, validated_data):
        """Update input file basic information"""
        request_user = self.context['request'].user
        
        # Check if file type is changing to bank_statement or credit_card
        new_file_type = validated_data.get('file_type', instance.file_type)
        old_file_type = instance.file_type
        
        # Update the input file
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Handle file type change to bank_statement or credit_card
        if (new_file_type in ['bank_statement', 'credit_card'] and 
            new_file_type != old_file_type):
            # Remove all existing attributes
            instance.attributes.all().delete()
            
            # Create default attribute
            DimAicInputFileAttributes.objects.create(
                input_file=instance,
                name="*",
                gl_account=None,
                type="",
                offset_gl_account=None,
                input_user=request_user,
                comments="Auto-generated for bank statement/credit card processing"
            )
        
        return instance


class InputFileDetailSerializer(serializers.ModelSerializer):
    """Serializer for detailed input file view with attributes"""
    
    client_name = serializers.CharField(source='client.client_name', read_only=True)
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = DimAicInputFiles
        fields = [
            'id', 'name', 'file_type', 'file_url', 'client_name', 
        ]
        read_only_fields = ['id']
    
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
        """Validate that gl_account and offset_gl_account are different"""
        gl_account = attrs.get('gl_account')
        offset_gl_account = attrs.get('offset_gl_account')
        
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
