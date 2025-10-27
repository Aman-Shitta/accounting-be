
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from .models import FactAICJETemplateHeaderSnapshot

from account.serializers import DimAICGLAcctSerializer

class JETemplateAttributeDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    gl_account = DimAICGLAcctSerializer(allow_null=True)
    offset_gl_account = DimAICGLAcctSerializer(allow_null=True)
    description = serializers.CharField()
    date = serializers.CharField()
    debit = serializers.CharField()
    credit = serializers.CharField()

class JETemplateDataSerializer(serializers.ModelSerializer):
    """Serializer for JE Template Data"""

    input_files = serializers.SerializerMethodField(source='get_input_files')

    class Meta:
        model = FactAICJETemplateHeaderSnapshot
        fields = ['id', 'je_name', 'je_refrence', 'input_files', 'je_freq', 'is_object', 'input_files']

    def to_representation(self, instance):
        """
        Convert JE template instance to JSON representation.
        Handles different document types: bank statements, credit cards, and other documents.
        """
        ret = super().to_representation(instance)
        attributes_data = []

        # Determine if this is a single-attribute template (bank statement/credit card)
        if instance.attribute_snapshots.count() == 1 and instance.input_files.count() == 1 and instance.attribute_snapshots.first().file_type in ['bank_statement', 'credit_card']:
            attributes_data = self._handle_single_attribute_template(instance)
        
        if not attributes_data:
            # Handle templates with multiple attributes
            attributes_data = self._handle_multi_attribute_template(instance)
        
        # Serialize and attach attributes data to response
        ret['attributes'] = JETemplateAttributeDataSerializer(attributes_data, many=True).data
        return ret

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

    def _handle_single_attribute_template(self, instance):
        """
        Handle JE templates with a single attribute (typically bank statements/credit cards).
        
        Args:
            instance: FactAICJETemplateHeaderSnapshot instance
            
        Returns:
            list: List of attribute data dictionaries
        """
        attributes_data = []
        
        # Get the single attribute snapshot and its input file
        star_attribute_snapshot = instance.attribute_snapshots.first()
        input_file_attribute = star_attribute_snapshot.input_file_attribute
        input_file_snapshot = input_file_attribute.input_file_snapshot

        # Validate input file snapshot exists
        if not input_file_snapshot:
            return []

        # Only process bank statements and credit cards
        if input_file_snapshot.file_type in ['bank_statement', 'credit_card']:
            attributes_data = self._process_bank_documents(input_file_snapshot)
        
        return attributes_data

    def _process_bank_documents(self, input_file_snapshot):
        """
        Process bank statement or credit card documents to extract line items.
        
        Args:
            input_file_snapshot: Input file snapshot containing bank documents
            
        Returns:
            list: List of bank line item data dictionaries
            
        Raises:
            ValidationError: If document is not verified
        """
        from .models.monthly_document_line_models import MonthlyDocumentBankLineItem
        
        attributes_data = []
        
        # Get extraction documents
        bank_documents = input_file_snapshot.extraction_documents.all()
        if not bank_documents.exists():
            return []

        # Get first bank document and validate its status
        bank_document = bank_documents.first()
        if bank_document.status != 'verified':
            raise ValidationError(
                {'detail': 'Extracted data needs to be verified to get the template data.'}
            )

        # Fetch all bank line items with related GL accounts
        items = MonthlyDocumentBankLineItem.objects.filter(
            document=bank_document
        ).select_related('gl_account', 'offset_gl_account')

        # Convert bank line items to attribute data format
        for item in items:
            attributes_data.append({
                "id": item.id,
                "gl_account": item.gl_account,
                "offset_gl_account": item.offset_gl_account,
                "description": item.description,
                "date": item.date,
                "debit": item.amount if item.transaction_type == "debit" else "",
                "credit": item.amount if item.transaction_type == "credit" else "",
            })
        
        return attributes_data

    def _handle_multi_attribute_template(self, instance):
        """
        Handle JE templates with multiple attributes (sales, etc.).
        
        Args:
            instance: FactAICJETemplateHeaderSnapshot instance
            
        Returns:
            list: List of attribute data dictionaries
        """
        attributes_data = []
        
        # Get all input file snapshots
        input_file_snapshot = instance.input_files.all()
        
        if not input_file_snapshot:
            # No input files - use template attributes directly
            attributes_data = self._get_template_attributes_without_files(instance)
        else:
            # Collect all extraction documents from input files
            all_documents = self._collect_all_documents(input_file_snapshot)
            
            if not all_documents:
                return []
            
            # Process based on template type (is_object or not)
            if instance.is_object:
                attributes_data = self._process_object_template(all_documents)
            else:
                attributes_data = self._process_non_object_template(instance, all_documents)
        
        return attributes_data

    def _get_template_attributes_without_files(self, instance):
        """
        Get template attributes when no input files are available.
        
        Args:
            instance: FactAICJETemplateHeaderSnapshot instance
            
        Returns:
            list: List of template attribute data dictionaries
        """
        template_attributes = instance.attribute_snapshots.all()
        attributes_data = [
            {
                "id": attr.id,
                "gl_account": DimAICGLAcctSerializer(attr.gl_account).data,
                "offset_gl_account": None,
                "description": attr.attribute_name or (
                    attr.input_file_attribute.name if attr.input_file_attribute else '<Manual>'
                ),
                "date": None,
                "debit": attr.debit,
                "credit": attr.credit,
            }
            for attr in template_attributes
        ]
        return attributes_data

    def _collect_all_documents(self, input_file_snapshots):
        """
        Collect all extraction documents from multiple input file snapshots.
        
        Args:
            input_file_snapshots: QuerySet of input file snapshots
            
        Returns:
            list: List of all extraction documents
        """
        all_documents = []
        for ifs in input_file_snapshots:
            documents = ifs.extraction_documents.all()
            if documents.exists():
                all_documents.extend(documents)
        return all_documents

    def _process_object_template(self, all_documents):
        """
        Process is_object templates - extract values from attribute items across all documents.
        Creates balanced transactions with offset entries.
        
        Args:
            all_documents: List of extraction documents
            
        Returns:
            list: List of attribute data dictionaries with balanced entries
        """
        from .models.monthly_document_line_models import MonthlyDocumentAttributeItem
        
        attributes_data = []
        
        # Process attribute items from all documents
        for document in all_documents:
            attribute_items = MonthlyDocumentAttributeItem.objects.filter(
                document=document
            ).select_related('attribute', 'gl_account', 'offset_gl_account')

            for item in attribute_items:
                # Add primary transaction entry
                attributes_data.append({
                    "id": item.id,
                    "gl_account": item.gl_account,
                    "offset_gl_account": item.offset_gl_account,
                    "description": item.attribute.name if item.attribute else 'Unknown Attribute',
                    "date": None,  # Attributes don't have dates
                    "debit": item.value if item.transaction_type == "debit" else "",
                    "credit": item.value if item.transaction_type == "credit" else "",
                })

                # Add balancing offset entry (reverse debit/credit)
                attributes_data.append({
                    "id": item.id,
                    "gl_account": item.offset_gl_account,
                    "offset_gl_account": item.gl_account,
                    "description": "",
                    "date": None,
                    "credit": item.value if item.transaction_type == "debit" else "",
                    "debit": item.value if item.transaction_type == "credit" else "",
                })
        
        return attributes_data

    def _process_non_object_template(self, instance, all_documents):
        """
        Process non-is_object templates - use GL accounts from JE template but values from documents.
        
        Args:
            instance: FactAICJETemplateHeaderSnapshot instance
            all_documents: List of extraction documents
            
        Returns:
            list: List of attribute data dictionaries
        """
        from .models.monthly_document_line_models import (
            MonthlyDocumentAttributeItem,
            MonthlyTemplateManualAttributeItem
        )
        
        attributes_data = []
        template_attributes = instance.attribute_snapshots.all()
        
        for template_attr in template_attributes:
            # Extract value and offset GL account for this attribute
            attribute_value, attribute_offset_gl = self._get_attribute_value(
                template_attr, all_documents
            )
            
            # Build attribute data using template GL account
            attributes_data.append({
                "id": template_attr.pk,
                "gl_account": template_attr.gl_account,
                "offset_gl_account": attribute_offset_gl,
                "description": template_attr.attribute_name or (
                    template_attr.input_file_attribute.name if template_attr.input_file_attribute else '<Manual>'
                ),
                "date": None,
                "debit": attribute_value if template_attr.debit != 'X' else "",
                "credit": attribute_value if template_attr.credit != 'X' else "",
            })
        
        return attributes_data

    def _get_attribute_value(self, template_attr, all_documents):
        """
        Get the value and offset GL account for a template attribute.
        Searches across extracted documents or manual entries.
        
        Args:
            template_attr: Template attribute snapshot
            all_documents: List of extraction documents to search
            
        Returns:
            tuple: (attribute_value, attribute_offset_gl)
        """
        from .models.monthly_document_line_models import (
            MonthlyDocumentAttributeItem,
            MonthlyTemplateManualAttributeItem
        )
        
        attribute_value = ""
        attribute_offset_gl = None
        
        print("template_attr.input_file_attribute :: ", 
              template_attr.input_file_attribute, template_attr.attribute_name)

        if template_attr.input_file_attribute:
            # Search for extracted attribute value across all documents
            attribute_value, attribute_offset_gl = self._find_extracted_attribute_value(
                template_attr.input_file_attribute, all_documents
            )
        else:
            # Handle manual attributes
            attribute_value = self._get_or_create_manual_attribute(template_attr)
        
        return attribute_value, attribute_offset_gl

    def _find_extracted_attribute_value(self, input_file_attribute, all_documents):
        """
        Find extracted attribute value from documents.
        
        Args:
            input_file_attribute: Input file attribute to search for
            all_documents: List of documents to search
            
        Returns:
            tuple: (attribute_value, attribute_offset_gl)
        """
        from .models.monthly_document_line_models import MonthlyDocumentAttributeItem
        
        # Search across all documents for this attribute
        for document in all_documents:
            try:
                attr_item = MonthlyDocumentAttributeItem.objects.get(
                    document=document,
                    attribute=input_file_attribute
                )
                return attr_item.value, attr_item.offset_gl_account
            except MonthlyDocumentAttributeItem.DoesNotExist:
                continue
        
        # Not found in any document
        return "", None

    def _get_or_create_manual_attribute(self, template_attr):
        """
        Get or create a manual attribute item for template attribute.
        
        Args:
            template_attr: Template attribute snapshot
            
        Returns:
            str: Attribute value
        """
        from .models.monthly_document_line_models import MonthlyTemplateManualAttributeItem
        
        try:
            # Try to get existing manual attribute
            attr_item = MonthlyTemplateManualAttributeItem.objects.get(
                template_attribute=template_attr
            )
            return attr_item.value
        except (MonthlyTemplateManualAttributeItem.DoesNotExist, Exception):
            # Create new manual attribute if doesn't exist
            attr_item = MonthlyTemplateManualAttributeItem.objects.create(
                template_attribute=template_attr,
                value="",
                transaction_type="debit" if template_attr.debit != 'X' else "credit",
                gl_account=template_attr.gl_account,
                offset_gl_account=None,
            )
            return ""


class ManualValueItem(serializers.Serializer):
    """Individual manual value entry"""
    attribute_id = serializers.IntegerField(required=True)
    value = serializers.FloatField(required=True)

class ManualValueUpdateSerializer(serializers.Serializer):
    """Serializer for updating multiple manual values in JE templates at once"""
    values = serializers.ListField(
        child=ManualValueItem(),
        required=True,
        allow_empty=False
    )

class JETemplateStatusUpdateSerializer(serializers.Serializer):
    """Serializer for updating JE template status"""
    status = serializers.CharField(
        required=True
    )

    def validate_status(self, value):
        allowed_statuses = ['verified']
        if value not in allowed_statuses:
            raise serializers.ValidationError(f"Status must be one of {allowed_statuses}.")
        return value

