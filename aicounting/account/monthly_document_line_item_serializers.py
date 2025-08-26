from decimal import Decimal, InvalidOperation
from django.db import transaction, models
from rest_framework import serializers

from .models.monthly_document_line_models import MonthlyDocumentBankLineItem
from .models import DimAICGLAcct


class GLAccountNestedSerializer(serializers.ModelSerializer):
    """Nested serializer for GL Account details"""
    class Meta:
        model = DimAICGLAcct
        fields = ["id", "account_number", "account_name", "description", "account_class", "sub_class"]


class MonthlyDocumentBankLineItemSerializer(serializers.ModelSerializer):
    """Serializer for MonthlyDocumentBankLineItem with debit/credit split"""
    debit = serializers.SerializerMethodField()
    credit = serializers.SerializerMethodField()
    gl_account = GLAccountNestedSerializer(read_only=True)
    offset_gl_account = GLAccountNestedSerializer(read_only=True)
    gl_account_id = serializers.PrimaryKeyRelatedField(
        queryset=DimAICGLAcct.objects.all(), 
        write_only=True, 
        required=False, 
        allow_null=True,
        help_text="ID of the GL account to assign"
    )

    class Meta:
        model = MonthlyDocumentBankLineItem
        fields = [
            "id",
            "page_number",
            "line_number", 
            "date",
            "description",
            "debit",
            "credit",
            "gl_account",
            "offset_gl_account", 
            "gl_account_id",
        ]
        read_only_fields = ["id"]

    def get_debit(self, obj):
        """Return debit amount as string if transaction is debit type"""
        if obj.transaction_type == 'debit' and obj.amount is not None:
            return str(obj.amount)
        return None

    def get_credit(self, obj):
        """Return credit amount as string if transaction is credit type"""
        if obj.transaction_type == 'credit' and obj.amount is not None:
            return str(obj.amount)
        return None

    def validate(self, attrs):
        """Validate that either debit or credit is provided, but not both"""
        request = self.context.get('request')
        is_create = self.instance is None
        debit = request.data.get('debit') if request else None
        credit = request.data.get('credit') if request else None
        
        if is_create:
            if not debit and not credit:
                raise serializers.ValidationError("Either 'debit' or 'credit' amount is required.")
            if debit and credit:
                raise serializers.ValidationError("Provide only one of 'debit' or 'credit', not both.")
        else:
            # For updates, allow neither (no amount change) or only one
            if debit and credit:
                raise serializers.ValidationError("Provide only one of 'debit' or 'credit', not both.")
        
        return attrs

    def _parse_amount(self, value):
        """Parse amount string to Decimal, handling common formats"""
        if value in (None, ""):
            return None
        try:
            # Remove commas and whitespace
            clean_value = str(value).replace(',', '').strip()
            return Decimal(clean_value)
        except (InvalidOperation, ValueError):
            raise serializers.ValidationError("Invalid amount format.")

    @transaction.atomic
    def create(self, validated_data):
        """Create new line item with proper line number handling to avoid duplicate key constraint"""
        request = self.context.get('request')
        document = self.context.get('document')  # MonthlyAccountingDocument instance
        
        if not document:
            raise serializers.ValidationError("Document context is required.")
        
        page_number = validated_data.get('page_number')
        line_number = validated_data.get('line_number')
        date = validated_data.get('date')
        description = validated_data.get('description')
        gl_account = validated_data.get('gl_account_id')
        
        if not page_number:
            raise serializers.ValidationError("Page number is required.")
        
        debit = request.data.get('debit') if request else None
        credit = request.data.get('credit') if request else None

        debit_amount = self._parse_amount(debit)
        credit_amount = self._parse_amount(credit)

        # Handle line number assignment with proper conflict resolution
        if line_number is None or line_number <= 0:
            # Append to end of page
            max_line = MonthlyDocumentBankLineItem.objects.filter(
                document=document, 
                page_number=page_number
            ).aggregate(max_line=models.Max('line_number'))['max_line']
            line_number = (max_line or 0) + 1
        else:
            # For specific line number insertion, avoid conflicts
            # Get all existing line numbers on this page
            existing_lines = list(MonthlyDocumentBankLineItem.objects.filter(
                document=document, 
                page_number=page_number
            ).values_list('line_number', flat=True).order_by('line_number'))
            
            if line_number in existing_lines:
                # Need to shift lines to make room
                # Update in reverse order to avoid constraint violations
                lines_to_update = MonthlyDocumentBankLineItem.objects.filter(
                    document=document, 
                    page_number=page_number, 
                    line_number__gte=line_number
                ).order_by('-line_number')
                
                # Shift each line individually to avoid bulk update conflicts
                for line_item in lines_to_update:
                    line_item.line_number = line_item.line_number + 1
                    line_item.save()

        # Determine transaction type and amount
        transaction_type = 'debit' if debit_amount is not None else 'credit'
        amount = debit_amount if transaction_type == 'debit' else credit_amount

        # Get default offset GL account from input file snapshot
        default_offset_gl = None
        try:
            bank_attributes = document.input_file_snapshot.attribute_snapshots.all()
            if bank_attributes.exists():
                default_offset_gl = bank_attributes.first().offset_gl_account
        except Exception:
            # If no offset GL found, continue without it
            pass
        # Create the line item
        item = MonthlyDocumentBankLineItem.objects.create(
            document=document,
            page_number=page_number,
            line_number=line_number,
            date=date,
            description=description,
            amount=amount,
            transaction_type=transaction_type,
            gl_account=gl_account,
            offset_gl_account=default_offset_gl
        )
        return item

    @transaction.atomic
    def update(self, instance, validated_data):
        """Update existing line item"""
        request = self.context.get('request')
        debit = request.data.get('debit') if request else None
        credit = request.data.get('credit') if request else None
        
        if debit and credit:
            raise serializers.ValidationError("Provide only one of 'debit' or 'credit'.")

        # Update basic fields
        if 'date' in validated_data:
            instance.date = validated_data['date']
        if 'description' in validated_data:
            instance.description = validated_data['description']
        if 'gl_account_id' in validated_data:
            instance.gl_account = validated_data['gl_account_id']

        # Update amount and transaction type if provided
        if debit is not None or credit is not None:
            debit_amount = self._parse_amount(debit)
            credit_amount = self._parse_amount(credit)
            
            if debit_amount is not None and credit_amount is not None:
                raise serializers.ValidationError("Only one of debit or credit can be set.")
            
            if debit_amount is not None:
                instance.transaction_type = 'debit'
                instance.amount = debit_amount
            elif credit_amount is not None:
                instance.transaction_type = 'credit'
                instance.amount = credit_amount

        instance.save()
        return instance
