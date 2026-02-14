from django.core.exceptions import ValidationError
from rest_framework import serializers

from account.input_files.input_file_serializers import InputFileAttributeSerializer
from account.models import (
    DimAICGLAcct,
    DimAICJEFreq,
    DimAICJETemplateAttribute,
    DimAICJETemplateHeader,
    DimAicInputFileAttributes,
    DimAicInputFiles,
)
from user.models import DimAICClient


class JEFreqListSerializer(serializers.ModelSerializer):
    """Serializer for listing JE Frequencies"""

    class Meta:
        model = DimAICJEFreq
        fields = ['id', 'je_freq']


class JETemplateListSerializer(serializers.ModelSerializer):
    """Serializer for listing JE Templates"""

    input_files = serializers.SerializerMethodField()
    file_type = serializers.SerializerMethodField()
    attributes_count = serializers.SerializerMethodField()

    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'id', 'je_name', 'je_refrence',
            'je_freq', 'file_type',
            'attributes_count', 'is_object',
            'input_files'
        ]

    def get_attributes_count(self, obj):
        """Get count of configured attributes for this template"""
        return obj.template_attributes.count()

    def get_input_files(self, obj):
        """Return the input files if available"""
        files = obj.input_files.all()
        if files:
            return [{
                'id': file.id,
                'name': file.name,
                'file_type': file.file_type
            } for file in files]
        return []

    def get_file_type(self, obj):
        """Get the file type of the first input file if any"""
        files = obj.input_files.all()
        if files:
            return files[0].file_type
        return None


class JETemplateDetailSerializer(serializers.ModelSerializer):
    """Serializer for detailed JE Template view"""

    input_files = serializers.SerializerMethodField(source='get_input_files')

    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'id', 'je_name', 'je_refrence', 'je_freq', 'is_object', 'input_files',
            'description'
        ]

    def get_input_files(self, obj):
        """Return the input files if available"""
        files = obj.input_files.all()
        if files:
            return [{
                'id': file.id,
                'name': file.name,
                'file_type': file.file_type
            } for file in files]
        return []


class JETemplateCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating JE Templates"""

    class Meta:
        model = DimAICJETemplateHeader
        fields = [
            'je_name', 'je_refrence', 'je_freq', 'je_type',
            'is_object', 'input_files', 'description'
        ]

    def validate(self, data):
        """Custom validation for the template creation"""
        is_object = data.get('is_object', False)
        input_files = data.get('input_files', [])

        if is_object and not input_files:
            raise serializers.ValidationError(
                {"input_files": "At least one input file is required for Object view template."})

        # Check file types and apply restrictions
        if input_files:
            bank_or_credit_files = [f for f in input_files if f.file_type in [
                'bank_statement', 'credit_card']]
            other_files = [f for f in input_files if f.file_type not in [
                'bank_statement', 'credit_card']]

            # If there are bank/credit files, ensure only one is selected and no other file types
            if bank_or_credit_files:
                if len(bank_or_credit_files) > 1:
                    raise serializers.ValidationError(
                        "Only one bank statement or credit card file can be selected at a time"
                    )

                if other_files:
                    raise serializers.ValidationError(
                        "Bank statement or credit card files cannot be combined with other file types"
                    )

                if is_object:
                    raise serializers.ValidationError(
                        f"Templates with {bank_or_credit_files[0].file_type} input files must be configured as object templates (is_object=False)"
                    )

        return data

    def validate_input_files(self, value):
        """Validate that the input files belong to the client"""
        if value:
            client_id = self.context.get('client_id')
            for file in value:
                if file.client.id != client_id:
                    raise serializers.ValidationError(
                        f"Input file {file.name} does not belong to the specified client")
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
        bank_cc_files = [f for f in template.input_files.all()
                         if f.file_type in ['bank_statement', 'credit_card']]

        if bank_cc_files:
            # We've already validated there's only one
            input_file = bank_cc_files[0]
            # Get all attributes for this input file
            input_file_attributes = DimAicInputFileAttributes.objects.filter(
                input_file=input_file
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

    input_file_name = serializers.CharField(
        source='input_file.name', read_only=True)
    input_file_type = serializers.CharField(
        source='input_file.file_type', read_only=True)
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
    """Serializer for JE Template Attributes with dynamic fields"""

    attribute = serializers.SerializerMethodField()
    gl_account_details = serializers.SerializerMethodField()

    class Meta:
        model = DimAICJETemplateAttribute
        fields = [
            'id', 'attribute', 'gl_account_details', 'debit', 'credit', 'attribute_name'
        ]

    def to_representation(self, instance):
        """Override to return dynamic fields based on template type"""
        # Get the base representation
        data = super().to_representation(instance)

        # Check if this is an object template (has input_file_attribute)
        if instance.input_file_attribute:
            # Object template - return only id and attribute
            return {
                'id': data['id'],
                'attribute': data['attribute']
            }
        elif instance.gl_account:
            # Non-object template - return id, gl_account_details, debit, credit, attribute_name
            return {
                'id': data['id'],
                'gl_account_details': data['gl_account_details'],
                'debit': data['debit'],
                'credit': data['credit'],
                'attribute_name': data['attribute_name']
            }
        else:
            # Fallback - return all fields
            return data

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
        """Validate that the attribute exists and belongs to the template's input files"""
        template_id = self.context.get('template_id')

        try:
            template = DimAICJETemplateHeader.objects.get(id=template_id)

            if not template.is_object:
                raise serializers.ValidationError(
                    "This template is not an object template")

            if not template.input_files.exists():
                raise serializers.ValidationError(
                    "Template must have input files for object attributes")

            # Get all input file IDs for this template
            template_file_ids = template.input_files.values_list(
                'id', flat=True)

            # Check if the attribute exists and belongs to any of the template's input files
            try:
                attribute = DimAicInputFileAttributes.objects.get(
                    id=value,
                    input_file__in=template_file_ids
                )

                # Additional restriction for bank_statement and credit_card files
                bank_cc_files = [f for f in template.input_files.all()
                                 if f.file_type in ['bank_statement', 'credit_card']]

                if bank_cc_files:
                    # Check if this template already has any attributes configured
                    existing_attrs_count = DimAICJETemplateAttribute.objects.filter(
                        je_template_id=template,
                        input_file_attribute__isnull=False
                    ).count()

                    # For bank_statement and credit_card, only allow one attribute
                    if existing_attrs_count > 0:
                        raise serializers.ValidationError(
                            f"Templates with {bank_cc_files[0].file_type} files can only have one attribute configured"
                        )

                return attribute
            except DimAicInputFileAttributes.DoesNotExist:
                raise serializers.ValidationError(
                    f"Attribute with ID {value} not found in any of the template's input files")

        except DimAICJETemplateHeader.DoesNotExist:
            raise serializers.ValidationError("Template not found")


# Serializer for non-object template attributes (using gl_account, debit, credit)
class JETemplateAttributeNonObjectSerializer(serializers.Serializer):
    """Serializer for non-object template attributes"""

    gl_account = serializers.IntegerField(help_text="GL Account ID")
    debit = serializers.CharField(
        max_length=255, allow_null=True, required=False, help_text="Debit value")
    credit = serializers.CharField(
        max_length=255, allow_null=True, required=False, help_text="Credit value")

    def validate_gl_account(self, value):
        """Validate that the GL account exists"""
        try:
            return DimAICGLAcct.objects.get(id=value)
        except DimAICGLAcct.DoesNotExist:
            raise serializers.ValidationError(
                f"GL Account with ID {value} not found")

    def validate(self, data):
        """Validate that at least one of debit or credit has a value"""
        debit = data.get('debit')
        credit = data.get('credit')

        if not debit and not credit:
            raise serializers.ValidationError(
                "At least one of debit or credit must have a value")

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
        if not template.is_object:
            # Validate for non-object templates
            validated_attributes = self._validate_manual_attributes(
                value, template)
        else:
            # Templates without input files can only have manual attributes
            if not template.input_files.exists():
                raise serializers.ValidationError(
                    "Cannot create Object based JE template without files.")

            # Validate for object templates (expecting id)
            elif template.is_object:

                new_ids = []
                for i, attr_data in enumerate(value):
                    # Validate that attr_data contains id
                    if 'id' not in attr_data:
                        raise serializers.ValidationError(
                            f"Attribute at index {i}: 'id' field is required for object templates")

                    object_serializer = JETemplateAttributeObjectSerializer(
                        data=attr_data,
                        context={'template_id': template_id}
                    )
                    if object_serializer.is_valid():
                        attribute = object_serializer.validated_data['id']

                        # Check for duplicates in current request
                        if attribute.id in new_ids:
                            raise serializers.ValidationError(
                                f"Duplicate attribute ID {attribute.id} in request")

                        new_ids.append(attribute.id)
                        validated_attributes.append({
                            'type': 'object',
                            'input_file_attribute': attribute
                        })
                    else:
                        raise serializers.ValidationError(
                            f"Attribute at index {i}: {object_serializer.errors}")

            # Additional validation: for object templates (except bank_statement and credit_card),
            # no two templates for the same client can have the exact same attributes
            if new_ids:
                # Find other object templates for the same client with the same attributes
                client = template.client
                other_templates = DimAICJETemplateHeader.objects.filter(
                    client=client,
                    is_object=True
                ).exclude(id=template.id)

                for other_template in other_templates:
                    # Skip bank_statement and credit_card templates in this check
                    other_has_bank_cc = False
                    for input_file in other_template.input_files.all():
                        if input_file.file_type in ['bank_statement', 'credit_card']:
                            other_has_bank_cc = True
                            break

                    if other_has_bank_cc:
                        continue

                    other_ids = set(
                        DimAICJETemplateAttribute.objects.filter(
                            je_template_id=other_template,
                            input_file_attribute__isnull=False
                        ).values_list('input_file_attribute__id', flat=True)
                    )

                    if new_ids == other_ids:
                        raise serializers.ValidationError(
                            f"Another object template '{other_template.je_name}' already has the same attribute configuration"
                        )

        return validated_attributes

    def _validate_manual_attributes(self, value, template):
        """Validate manual attributes (non-object attributes)"""
        validated_attributes = []

        # For manual attributes, expect payload: {"gl_account": 1, "debit": "1", "credit": null}
        for i, attr_data in enumerate(value):
            # Validate that attr_data contains required fields for non-object templates
            required_fields = ['gl_account']
            missing_fields = [
                field for field in required_fields if field not in attr_data]
            if missing_fields:
                raise serializers.ValidationError(
                    f"Attribute at index {i}: Missing required fields for manual attributes: {missing_fields}"
                )

            if not template.input_files.exists():
                if any([i for i in attr_data if i in ['debit', 'credit'] and str(attr_data[i]).isdigit()]):
                    raise serializers.ValidationError(
                        f"Manual attributes cannot reference attribute without  input files"
                    )

            non_object_serializer = JETemplateAttributeNonObjectSerializer(
                data=attr_data)
            if non_object_serializer.is_valid():
                gl_account = non_object_serializer.validated_data['gl_account']
                debit = non_object_serializer.validated_data.get('debit')
                credit = non_object_serializer.validated_data.get('credit')

                # Set attribute_name based on debit/credit values if they reference attribute IDs
                attribute_name = None
                attribute_comment = None
                input_file_attribute = None
                if debit and str(debit).isdigit():
                    try:
                        input_file_attribute = DimAicInputFileAttributes.objects.get(
                            id=int(debit))
                        attribute_name = input_file_attribute.name
                        attribute_comment = input_file_attribute.comments
                    except DimAicInputFileAttributes.DoesNotExist:
                        pass
                elif credit and str(credit).isdigit():
                    try:
                        input_file_attribute = DimAicInputFileAttributes.objects.get(
                            id=int(credit))
                        attribute_name = input_file_attribute.name
                        attribute_comment = input_file_attribute.comments
                    except DimAicInputFileAttributes.DoesNotExist:
                        pass

                validated_attributes.append({
                    'type': 'non_object',
                    'gl_account': gl_account,
                    'debit': debit,
                    'credit': credit,
                    'attribute_name': attribute_name,
                    'attribute_comment': attribute_comment,
                    'input_file_attribute': input_file_attribute
                })
            else:
                raise serializers.ValidationError(
                    f"Attribute at index {i}: {non_object_serializer.errors}")

        return validated_attributes

    def create(self, validated_data):
        """Create JE Template Attributes based on template type"""
        template_id = self.context.get('template_id')
        user = self.context.get('request').user

        template = DimAICJETemplateHeader.objects.get(id=template_id)
        validated_attributes = validated_data['attributes']

        created_attributes = []
        # If this is a non-object template or object template without input files,
        # we'll use manual attributes and clear existing ones
        if not template.is_object or (template.is_object and not template.input_files.exists()):
            # Clear existing attributes
            DimAICJETemplateAttribute.objects.filter(
                je_template_id=template).delete()

        for attr_data in validated_attributes:
            input_file_attribute = attr_data['input_file_attribute']
            if attr_data['type'] == 'object':
                # For object templates, only create if not already exists for this template
                existing = DimAICJETemplateAttribute.objects.filter(
                    je_template_id=template,
                    input_file_attribute=input_file_attribute
                ).first()
                if existing:
                    template_attribute = existing
                else:
                    template_attribute = DimAICJETemplateAttribute.objects.create(
                        je_template_id=template,
                        input_file_attribute=input_file_attribute,
                        input_user=user
                    )
            else:  # non_object or manual attributes
                # Normalize None values to 'X' for debit/credit
                # One side should always be 'X', the other can be: attribute_id, 'manual', or a number
                debit_value = attr_data['debit'] if attr_data['debit'] is not None else 'X'
                credit_value = attr_data['credit'] if attr_data['credit'] is not None else 'X'

                template_attribute = DimAICJETemplateAttribute.objects.create(
                    je_template_id=template,
                    gl_account=attr_data['gl_account'],
                    debit=debit_value,
                    credit=credit_value,
                    attribute_name=attr_data['attribute_name'],
                    input_user=user,
                    attribute_comment=attr_data.get('attribute_comment'),
                    input_file_attribute=input_file_attribute
                )

            created_attributes.append(template_attribute)

        return created_attributes
