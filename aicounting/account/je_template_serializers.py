from rest_framework import serializers
from django.core.exceptions import ValidationError
from .models import (
    DimAICJETemplateHeader, 
    DimAICJETemplateAttribute, 
    DimAicInputFileAttributes,
    DimAicInputFiles,
    DimAICJEFreq,
    DimAICGLAcct
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

    input_file = serializers.SerializerMethodField()
    file_type = serializers.CharField(source='input_file.file_type', read_only=True)
    attributes_count = serializers.SerializerMethodField()
    
    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'id', 'je_name', 'je_refrence',
            'je_freq', 'file_type',
            'attributes_count', 'is_object',
            'input_file'
        ]
    
    def get_attributes_count(self, obj):
        """Get count of configured attributes for this template"""
        return obj.template_attributes.count()

    def get_input_file(self, obj):
        """Return the input file name if available"""
        if obj.input_file:
            return {
                'id': obj.input_file.id,
                'name': obj.input_file.name,
                'file_type': obj.input_file.file_type
            }
        return None

class JETemplateDetailSerializer(serializers.ModelSerializer):
    """Serializer for detailed JE Template view"""
    
    input_file = serializers.SerializerMethodField()
    file_type = serializers.CharField(source='input_file.file_type', read_only=True)
   
    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'id', 'je_name', 'je_refrence', 'je_freq', 'is_object', 'input_file', 
            'file_type'
        ]

    def get_input_file(self, obj):
        """Return the input file details if available"""
        if obj.input_file:
            return {
                'id': obj.input_file.id,
                'name': obj.input_file.name,
                'file_type': obj.input_file.file_type
            }
        return None

class JETemplateCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating JE Templates"""
    
    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'je_name', 'je_refrence', 'je_freq', 'je_type',
            'is_object', 'input_file', 'description'
        ]
    
    def validate(self, data):
        """Custom validation for the template creation"""
        is_object = data.get('is_object', False)
        input_file = data.get('input_file')
        
        if is_object and not input_file:
            raise serializers.ValidationError("input_file is required when is_object is true")
        
        # Additional validation for bank_statement and credit_card files
        if input_file and input_file.file_type in ['bank_statement', 'credit_card']:
            if not is_object:
                raise serializers.ValidationError(
                    f"Templates with {input_file.file_type} input files can only be configured as object templates (is_object=True)"
                )
        
        return data
    
    def validate_input_file(self, value):
        """Validate that the input file belongs to the client"""
        if value:
            client_id = self.context.get('client_id')
            if value.client.id != client_id:
                raise serializers.ValidationError("Input file does not belong to the specified client")
        return value
    
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
        
        # Create the template
        template = super().create(validated_data)
        
        # Auto-create default attributes for bank_statement and credit_card files
        if template.input_file and template.input_file.file_type in ['bank_statement', 'credit_card']:
            # Get all attributes for this input file
            input_file_attributes = DimAicInputFileAttributes.objects.filter(
                input_file=template.input_file
            )
            
            # Create template attributes for all available attributes in the file
            for attribute in input_file_attributes:
                DimAICJETemplateAttribute.objects.create(
                    je_template_id=template,
                    input_file_attribute=attribute,
                    input_user=user
                )
        
        return template


class JETemplateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating JE Templates"""
    
    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'je_name', 'je_refrence', 'je_freq', 
            'description',
            # 'je_type', 'is_object', 'input_file'
        ]
    
    # def validate(self, data):
    #     """Custom validation for the template update"""
    #     is_object = data.get('is_object')
    #     input_file = data.get('input_file')
        
    #     # If is_object is being set to True, input_file must be provided
    #     if is_object and not input_file and not self.instance.input_file:
    #         raise serializers.ValidationError("input_file is required when is_object is true")
        
    #     # Additional validation for bank_statement and credit_card files
    #     current_input_file = input_file or self.instance.input_file if self.instance else None
    #     if current_input_file and current_input_file.file_type in ['bank_statement', 'credit_card']:
    #         current_is_object = is_object if is_object is not None else (self.instance.is_object if self.instance else False)
    #         if not current_is_object:
    #             raise serializers.ValidationError(
    #                 f"Templates with {current_input_file.file_type} input files can only be configured as object templates (is_object=True)"
    #             )
        
    #     return data
    
    # def validate_input_file(self, value):
    #     """Validate that the input file belongs to the client"""
    #     if value and self.instance:
    #         if value.client != self.instance.client:
    #             raise serializers.ValidationError("Input file does not belong to the template's client")
    #     return value


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
        if obj.gl_account:
            data = {
                'id': obj.gl_account.id,
                'name': obj.gl_account.account_name,
                'account_number': obj.gl_account.account_number
            }
            return data
        return None

    def get_offset_gl_account(self, obj):
        """Return the GL account ID as a string"""
        if obj.offset_gl_account:
            data = {
                'id': obj.offset_gl_account.id,
                'name': obj.offset_gl_account.account_name,
                'account_number': obj.offset_gl_account.account_number
            }
            return data
        return None

class JETemplateAttributeSerializer(serializers.ModelSerializer):
    """Serializer for JE Template Attributes"""
    
    attribute = serializers.SerializerMethodField()
    gl_account_details = serializers.SerializerMethodField()

    class Meta:
        model = DimAICJETemplateAttribute
        fields = [
            'id', 'attribute', 'gl_account_details', 'debit', 'credit', 'attribute_name'
        ]

    def get_attribute(self, obj):
        """Return the attributes related to this JE Template Attribute for object templates"""
        if obj.input_file_attribute:
            return InputFileAttributeSerializer(obj.input_file_attribute).data
        return None
    
    def get_gl_account_details(self, obj):
        """Return GL account details for non-object templates"""
        if obj.gl_account:
            return {
                'id': obj.gl_account.id,
                'name': obj.gl_account.account_name,
                'account_number': obj.gl_account.account_number
            }
        return None


# Serializer for object template attributes (using id)
class JETemplateAttributeObjectSerializer(serializers.Serializer):
    """Serializer for object template attributes"""
    
    id = serializers.IntegerField(help_text="Input file attribute ID")
    
    def validate_id(self, value):
        """Validate that the attribute exists and belongs to the template's input file"""
        template_id = self.context.get('template_id')
        
        try:
            template = DimAICJETemplateHeader.objects.get(id=template_id)
            
            if not template.is_object:
                raise serializers.ValidationError("This template is not an object template")
            
            if not template.input_file:
                raise serializers.ValidationError("Template must have an input file for object attributes")
            
            # Check if the attribute exists and belongs to the template's input file
            try:
                attribute = DimAicInputFileAttributes.objects.get(
                    id=value,
                    input_file=template.input_file
                )
                
                # Additional restriction for bank_statement and credit_card files
                if template.input_file.file_type in ['bank_statement', 'credit_card']:
                    # Check if this template already has any attributes configured
                    existing_attrs_count = DimAICJETemplateAttribute.objects.filter(
                        je_template_id=template,
                        input_file_attribute__isnull=False
                    ).count()
                    
                    # For bank_statement and credit_card, only allow one attribute
                    if existing_attrs_count > 0:
                        raise serializers.ValidationError(
                            f"Templates with {template.input_file.file_type} files can only have one attribute configured"
                        )
                
                return attribute
            except DimAicInputFileAttributes.DoesNotExist:
                raise serializers.ValidationError(f"Attribute with ID {value} not found in template's input file")
                
        except DimAICJETemplateHeader.DoesNotExist:
            raise serializers.ValidationError("Template not found")


# Serializer for non-object template attributes (using gl_account, debit, credit)
class JETemplateAttributeNonObjectSerializer(serializers.Serializer):
    """Serializer for non-object template attributes"""
    
    gl_account = serializers.IntegerField(help_text="GL Account ID")
    debit = serializers.CharField(max_length=255, allow_null=True, required=False, help_text="Debit value")
    credit = serializers.CharField(max_length=255, allow_null=True, required=False, help_text="Credit value")
    
    def validate_gl_account(self, value):
        """Validate that the GL account exists"""
        try:
            return DimAICGLAcct.objects.get(id=value)
        except DimAICGLAcct.DoesNotExist:
            raise serializers.ValidationError(f"GL Account with ID {value} not found")
    
    def validate(self, data):
        """Validate that at least one of debit or credit has a value"""
        debit = data.get('debit')
        credit = data.get('credit')
        
        if not debit and not credit:
            raise serializers.ValidationError("At least one of debit or credit must have a value")
        
        return data


class JETemplateAttributeCreateSerializer(serializers.Serializer):
    """Serializer for creating JE Template Attributes with different payloads based on is_object"""
    
    attributes = serializers.ListField(
        child=serializers.JSONField(),
        min_length=1,
        help_text="List of attributes to add to the JE template"
    )
    
    def validate_attributes(self, value):
        """Validate attributes based on template type"""
        template_id = self.context.get('template_id')
        
        try:
            template = DimAICJETemplateHeader.objects.get(id=template_id)
        except DimAICJETemplateHeader.DoesNotExist:
            raise serializers.ValidationError("Template not found")
        
        validated_attributes = []
        
        # Validate for object templates (expecting id)
        if template.is_object:
            # For object templates, expect payload: {"id": 1}
            # Check for duplicate attributes in the same template
            existing_ids = set(
                DimAICJETemplateAttribute.objects.filter(
                    je_template_id=template,
                    input_file_attribute__isnull=False
                ).values_list('input_file_attribute__id', flat=True)
            )
            
            # Special handling for bank_statement and credit_card files
            if template.input_file and template.input_file.file_type in ['bank_statement', 'credit_card']:
                if existing_ids:
                    raise serializers.ValidationError(
                        f"Templates with {template.input_file.file_type} files can only have one attribute and it's already configured"
                    )
                if len(value) > 1:
                    raise serializers.ValidationError(
                        f"Templates with {template.input_file.file_type} files can only have one attribute configured at a time"
                    )
            
            new_ids = []
            for i, attr_data in enumerate(value):
                # Validate that attr_data contains id
                if 'id' not in attr_data:
                    raise serializers.ValidationError(f"Attribute at index {i}: 'id' field is required for object templates")
                
                object_serializer = JETemplateAttributeObjectSerializer(
                    data=attr_data, 
                    context={'template_id': template_id}
                )
                if object_serializer.is_valid():
                    attribute = object_serializer.validated_data['id']
                    
                    # Check for duplicates in existing template attributes
                    if attribute.id in existing_ids:
                        raise serializers.ValidationError(f"Attribute {attribute.id} is already configured for this template")
                    
                    # Check for duplicates in current request
                    if attribute.id in new_ids:
                        raise serializers.ValidationError(f"Duplicate attribute ID {attribute.id} in request")
                    
                    new_ids.append(attribute.id)
                    validated_attributes.append({
                        'type': 'object',
                        'input_file_attribute': attribute
                    })
                else:
                    raise serializers.ValidationError(f"Attribute at index {i}: {object_serializer.errors}")
            
            # Additional validation: for object templates (except bank_statement and credit_card), 
            # no two templates for the same client can have the exact same attributes
            if new_ids and template.input_file and template.input_file.file_type not in ['bank_statement', 'credit_card']:
                # Find other object templates for the same client with the same attributes
                client = template.client
                other_templates = DimAICJETemplateHeader.objects.filter(
                    client=client,
                    is_object=True
                ).exclude(id=template.id)
                
                for other_template in other_templates:
                    # Skip bank_statement and credit_card templates in this check
                    if other_template.input_file and other_template.input_file.file_type in ['bank_statement', 'credit_card']:
                        continue
                        
                    other_ids = set(
                        DimAICJETemplateAttribute.objects.filter(
                            je_template_id=other_template,
                            input_file_attribute__isnull=False
                        ).values_list('input_file_attribute__id', flat=True)
                    )
                    
                    # Check if the combination of existing + new attributes matches another template
                    current_template_attrs = set(existing_ids)
                    current_template_attrs.update(new_ids)
                    
                    if current_template_attrs == other_ids:
                        raise serializers.ValidationError(
                            f"Another object template '{other_template.je_name}' already has the same attribute configuration"
                        )
        
        # Validate for non-object templates (expecting gl_account, debit, credit)
        else:
            # For non-object templates, expect payload: {"gl_account": 1, "debit": "1", "credit": null}
            for i, attr_data in enumerate(value):
                # Validate that attr_data contains required fields for non-object templates
                required_fields = ['gl_account']
                missing_fields = [field for field in required_fields if field not in attr_data]
                if missing_fields:
                    raise serializers.ValidationError(
                        f"Attribute at index {i}: Missing required fields for non-object templates: {missing_fields}"
                    )
                
                non_object_serializer = JETemplateAttributeNonObjectSerializer(data=attr_data)
                if non_object_serializer.is_valid():
                    gl_account = non_object_serializer.validated_data['gl_account']
                    debit = non_object_serializer.validated_data.get('debit')
                    credit = non_object_serializer.validated_data.get('credit')
                    
                    # Set attribute_name based on debit/credit values if they reference attribute IDs
                    attribute_name = None
                    if debit and str(debit).isdigit():
                        try:
                            attr = DimAicInputFileAttributes.objects.get(id=int(debit))
                            attribute_name = attr.name
                        except DimAicInputFileAttributes.DoesNotExist:
                            pass
                    elif credit and str(credit).isdigit():
                        try:
                            attr = DimAicInputFileAttributes.objects.get(id=int(credit))
                            attribute_name = attr.name
                        except DimAicInputFileAttributes.DoesNotExist:
                            pass
                    
                    validated_attributes.append({
                        'type': 'non_object',
                        'gl_account': gl_account,
                        'debit': debit,
                        'credit': credit,
                        'attribute_name': attribute_name
                    })
                else:
                    raise serializers.ValidationError(f"Attribute at index {i}: {non_object_serializer.errors}")
        
        return validated_attributes
    
    def create(self, validated_data):
        """Create JE Template Attributes based on template type"""
        template_id = self.context.get('template_id')
        user = self.context.get('request').user
        
        template = DimAICJETemplateHeader.objects.get(id=template_id)
        validated_attributes = validated_data['attributes']
        
        created_attributes = []
        
        for attr_data in validated_attributes:
            if attr_data['type'] == 'object':
                template_attribute = DimAICJETemplateAttribute.objects.create(
                    je_template_id=template,
                    input_file_attribute=attr_data['input_file_attribute'],
                    input_user=user
                )
            else:  # non_object
                template_attribute = DimAICJETemplateAttribute.objects.create(
                    je_template_id=template,
                    gl_account=attr_data['gl_account'],
                    debit=attr_data['debit'],
                    credit=attr_data['credit'],
                    attribute_name=attr_data['attribute_name'],
                    input_user=user
                )
            
            created_attributes.append(template_attribute)
        
        return created_attributes
