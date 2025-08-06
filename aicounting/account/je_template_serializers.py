from rest_framework import serializers
from .models import (
    DimAICJETemplateHeader, 
    DimAICJETemplateAttribute, 
    DimAicInputFileAttributes,
    DimAICJEFreq
)
from .input_file_serializers import InputFileAttributeSerializer
from user.models import DimAICClient


class JEFreqListSerializer(serializers.ModelSerializer):
    """Serializer for listing JE Frequencies"""
    
    class Meta:
        model = DimAICJEFreq
        fields = ['id', 'je_freq']


class JETemplateListSerializer(serializers.ModelSerializer):
    """Serializer for listing JE Templates"""
    
    client_name = serializers.CharField(source='client.client_name', read_only=True)
    customer_name = serializers.CharField(source='customer.customer_name', read_only=True)
    je_freq_name = serializers.CharField(source='je_freq.je_freq', read_only=True)
    je_type_name = serializers.CharField(source='je_type.je_type', read_only=True)
    attributes_count = serializers.SerializerMethodField()
    
    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'id', 'je_name', 'je_refrence', 
            'client_name', 'customer_name', 
            'je_freq_name', 'je_type_name',
            'attributes_count'
        ]
    
    def get_attributes_count(self, obj):
        """Get count of configured attributes for this template"""
        return obj.template_attributes.count()


class JETemplateDetailSerializer(serializers.ModelSerializer):
    """Serializer for detailed JE Template view"""
   
    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'id', 'je_name', 'je_refrence', 'je_freq'
        ]

class JETemplateCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating JE Templates"""
    
    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'je_name', 'je_refrence', 'je_freq', 'je_type'
        ]
    
    def create(self, validated_data):
        """Create JE Template with client and customer from context"""
        client = self.context['client_id']
        user = self.context['request'].user
        
        # Get client and customer based on user authorization
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            client = DimAICClient.objects.get(id=client, customer=customer)
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            client = DimAICClient.objects.get(
                id=client, 
                customer=accountant.customer,
                assigned_accountants=accountant
            )
        
        validated_data['client'] = client
        validated_data['customer'] = client.customer
        
        return super().create(validated_data)


class JETemplateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating JE Templates"""
    
    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'je_name', 'je_refrence', 'je_freq', 'je_type'
        ]


class AvailableAttributeSerializer(serializers.ModelSerializer):
    """Serializer for available input file attributes (excluding bank_statement and credit_card)"""
    
    input_file_name = serializers.CharField(source='input_file.name', read_only=True)
    input_file_type = serializers.CharField(source='input_file.file_type', read_only=True)
    gl_account = serializers.SerializerMethodField()
    offset_gl_account = serializers.SerializerMethodField()
    
    class Meta:
        model = DimAicInputFileAttributes
        fields = [
            'id', 'name', 'type',
            'input_file_name', 'input_file_type',
            'gl_account', 'offset_gl_account',
        ]

    def get_gl_account(self, obj):
        """Return the GL account ID as a string"""
        data = {
            'id': obj.gl_account.id,
            'name': obj.gl_account.account_name,
            'number': obj.gl_account.account_number
        }
        return data

    def get_offset_gl_account(self, obj):
        """Return the GL account ID as a string"""
        data = {
            'id': obj.offset_gl_account.id,
            'name': obj.offset_gl_account.account_name,
            'number': obj.offset_gl_account.account_number
        }
        return data

class JETemplateAttributeSerializer(serializers.ModelSerializer):
    """Serializer for JE Template Attributes"""
    
    attribute = serializers.SerializerMethodField()

    class Meta:
        model = DimAICJETemplateAttribute
        fields = [
            'id', 'attribute',
        ]

    def get_attribute(self, obj):
        """Return the attributes related to this JE Template Attribute"""
        return InputFileAttributeSerializer(obj.input_file_attribute).data


class JETemplateAttributeCreateSerializer(serializers.Serializer):
    """Serializer for creating JE Template Attributes with list of attribute IDs"""
    
    input_file_attribute_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        help_text="List of input file attribute IDs to add to the JE template"
    )
    
    def validate_input_file_attribute_ids(self, value):
        """Validate that all attribute IDs exist and belong to the client"""
        template_id = self.context.get('template_id')
        user = self.context.get('request').user
        
        # Get the template and verify access
        try:
            if hasattr(user, 'customer_profile'):
                customer = user.customer_profile
                template = DimAICJETemplateHeader.objects.get(
                    id=template_id,
                    customer=customer
                )
            elif hasattr(user, 'accountant_profile'):
                accountant = user.accountant_profile
                template = DimAICJETemplateHeader.objects.get(
                    id=template_id,
                    customer=accountant.customer,
                    client__assigned_accountants=accountant
                )
            else:
                raise serializers.ValidationError("User does not have permission to access this template.")
        except DimAICJETemplateHeader.DoesNotExist:
            raise serializers.ValidationError("JE Template not found or access denied.")
        
        client = template.client
        
        # Validate each attribute ID
        validated_attributes = []
        invalid_ids = []
        already_configured = []
        invalid_file_types = []
        
        for attr_id in value:
            try:
                attribute = DimAicInputFileAttributes.objects.get(
                    id=attr_id,
                    input_file__client=client
                )
                
                # Check if attribute is from excluded file types
                if attribute.input_file.file_type in ['bank_statement', 'credit_card']:
                    invalid_file_types.append(attr_id)
                    continue
                
                # Check if already configured for this template
                if DimAICJETemplateAttribute.objects.filter(
                    je_template_id=template,
                    input_file_attribute=attribute
                ).exists():
                    already_configured.append(attr_id)
                    continue
                
                validated_attributes.append(attribute)
                
            except DimAicInputFileAttributes.DoesNotExist:
                invalid_ids.append(attr_id)
        
        # Raise validation errors if any issues found
        error_messages = []
        if invalid_ids:
            error_messages.append(f"Invalid attribute IDs or not belonging to client: {invalid_ids}")
        if already_configured:
            error_messages.append(f"Attributes already configured for this template: {already_configured}")
        if invalid_file_types:
            error_messages.append(f"Cannot add attributes from bank_statement or credit_card files: {invalid_file_types}")
        
        if error_messages:
            raise serializers.ValidationError(error_messages)
        
        if not validated_attributes:
            raise serializers.ValidationError("No valid attributes to add.")
        
        return validated_attributes
    
    def create(self, validated_data):
        """Create JE Template Attributes for all validated attributes"""
        template_id = self.context.get('template_id')
        user = self.context.get('request').user
        
        template = DimAICJETemplateHeader.objects.get(id=template_id)
        validated_attributes = validated_data['input_file_attribute_ids']
        
        created_attributes = []
        for attribute in validated_attributes:
            template_attribute = DimAICJETemplateAttribute.objects.create(
                je_template_id=template,
                input_file_attribute=attribute,
                input_user=user
            )
            created_attributes.append(template_attribute)
        
        return created_attributes
