
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated

from authentication import authenticate
from authentication.permissions import IsCustomerOrAccountant
from aicounting.response import create_api_response
from .je_accounting_serializers import (
    JETemplateDataSerializer,
    ManualValueUpdateSerializer,
    JETemplateStatusUpdateSerializer
)

from .models import FactAICJETemplateHeaderSnapshot, FactAICJETemplateAttributeSnapshot, MonthlyAccountingDocument

import logging
logger = logging.getLogger(__name__)



class JEAccountingDetailView(generics.GenericAPIView):

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountant]

    serializer_class = JETemplateDataSerializer

    @staticmethod
    def generate_export_file(template_snapshot):
        """
        Generate export file for JE template
        
        For bank statements and credit cards: generates the export file based on extracted data
        For non-bank documents: only generates if template is verified or has is_object=True
        """
        import io
        import csv
        from django.core.files.base import ContentFile

        # Check if this is a bank statement or credit card document
        is_bank_or_cc = False
        if hasattr(template_snapshot, 'input_file') and template_snapshot.input_file and \
           template_snapshot.input_file.file_type in ['bank_statement', 'credit_card']:
            is_bank_or_cc = True

        # For non-bank/cc documents, only generate if status is verified
        if not is_bank_or_cc and \
           not getattr(template_snapshot, 'status', None) == 'verified' and \
           not template_snapshot.is_object:
            # Don't generate for unverified non-bank, non-object templates
            logger.info(f"Skipping export generation for unverified template {template_snapshot.id}")
            return
            
        # Get template attributes
        template_attributes = JETemplateDataSerializer(template_snapshot).data['attributes']
        
        # Generate CSV file
        filename = "je_template.csv"
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(['GL Account Code', 'GL Account Name', 'Description', 'Debit', 'Credit'])
        for row in template_attributes:
            attribute_gl = row.get('gl_account') or dict()
            writer.writerow([
                attribute_gl.get('account_number', '') or '',
                attribute_gl.get('account_name', '') or '',
                row.get('description', '') or '',
                row.get('debit', '') or '',
                row.get('credit', '') or ''
            ])

        csv_data = output.getvalue()
        output.close()

        template_snapshot.je_export_file.save(filename, ContentFile(csv_data))

    def get(self, request, *args, **kwargs):

        user = request.user
        client = kwargs['client_id']
        template_id = kwargs['template_id']

        # Get client and customer based on user authorization
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile

        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            customer = accountant.customer
        
        template = get_object_or_404(FactAICJETemplateHeaderSnapshot, id=template_id, client_id=client, customer=customer.id)

        serializer = self.serializer_class(template, context={'request': request})

        
        return create_api_response(
            data=serializer.data,
            message="JE Template data retrieved successfully.", 
            status_code=status.HTTP_200_OK
        )

    def post(self, request, *args, **kwargs):
        """
        Update multiple debit or credit values for manual entries at once.
        
        Only allows updating manual entry values, not creating new entries.
        Expects a JSON body with:
        {
            "values": [
                {"attribute_id": 123, "value": 150.75},
                {"attribute_id": 456, "value": 78.90}
            ]
        }
        """
        user = request.user
        client_id = kwargs['client_id']
        template_id = kwargs['template_id']

        # Validate request data using serializer
        serializer = ManualValueUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid data provided.",
                data=serializer.errors
            )
        
        # Extract the list of values to update
        value_entries = serializer.validated_data['values']
        
        # Get client and customer based on user authorization
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            customer = accountant.customer
        else:
            return create_api_response(
                status_code=status.HTTP_403_FORBIDDEN,
                message="User is not authorized to perform this action."
            )
        
        # Get the JE template snapshot with proper authorization checks
        try:
            template = get_object_or_404(
                FactAICJETemplateHeaderSnapshot, 
                id=template_id, 
                client_id=client_id, 
                customer=customer.id
            )
        except Exception as e:
            return create_api_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message=f"JE Template not found or access denied: {str(e)}"
            )
        
        # Process each value entry
        updated_attributes = []
        error_messages = []
        
        for entry in value_entries:
            attribute_id = entry['attribute_id']
            value = entry['value']
            
            # Get the attribute snapshot with validation
            try:
                attribute = get_object_or_404(
                    FactAICJETemplateAttributeSnapshot,
                    id=attribute_id,
                    je_template_snapshot=template
                )
                
                # Check if the attribute is a manual entry and can be updated
                manual_value = f"{value}"
                
                if attribute.debit == 'manual':
                    attribute.debit = manual_value
                    attribute.save(update_fields=['debit'])
                    updated_attributes.append(attribute_id)
                elif attribute.credit == 'manual':
                    attribute.credit = manual_value
                    attribute.save(update_fields=['credit'])
                    updated_attributes.append(attribute_id)
                else:
                    error_messages.append(f"Attribute {attribute_id} is not a manual entry and cannot be updated.")
            except Exception as e:
                error_messages.append(f"Error updating attribute {attribute_id}: {str(e)}")
        
        # If no attributes were updated successfully, return an error
        if not updated_attributes:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="No attributes were updated.",
                data={"errors": error_messages}
            )
        
        # Generate export file with updated values only if this is a bank or cc document
        # or if the template is already verified
        is_bank_or_cc = False
        if hasattr(template, 'input_file') and template.input_file and \
           template.input_file.file_type in ['bank_statement', 'credit_card']:
            is_bank_or_cc = True
        
        if is_bank_or_cc or getattr(template, 'status', None) == 'verified' or template.is_object:
            try:
                self.generate_export_file(template)
            except Exception as e:
                logger.error(f"Error generating export file: {str(e)}")
                # Continue even if export file generation fails
        
        # Return updated template data
        serializer = self.serializer_class(template, context={'request': request})
        
        # Create appropriate message
        message = f"Successfully updated {len(updated_attributes)} manual entries."
        if len(error_messages) > 0:
            message += f" {len(error_messages)} entries had errors: {'; '.join(error_messages)}"
        
        # For non-bank/cc documents that aren't verified, remind user to verify
        is_bank_or_cc = False
        if hasattr(template, 'input_file') and template.input_file and \
           template.input_file.file_type in ['bank_statement', 'credit_card']:
            is_bank_or_cc = True
            
        if not is_bank_or_cc and not getattr(template, 'status', None) == 'verified':
            message += " Please verify the template to generate the export file."
        
        return create_api_response(
            status_code=status.HTTP_200_OK,
            message=message,
            data=serializer.data
        )
        
    def put(self, request, *args, **kwargs):
        """
        Update JE template status to verified and generate export file for non-bank/credit card documents.
        
        Expects a JSON body with:
        {
            "status": "verified"
        }
        """
        user = request.user
        client_id = kwargs['client_id']
        template_id = kwargs['template_id']
        
        # Validate request data using serializer
        serializer = JETemplateStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid data provided.",
                data=serializer.errors
            )
        
        # Get client and customer based on user authorization
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            customer = accountant.customer
        else:
            return create_api_response(
                status_code=status.HTTP_403_FORBIDDEN,
                message="User is not authorized to perform this action."
            )
        
        # Get the JE template snapshot with proper authorization checks
        try:
            template = get_object_or_404(
                FactAICJETemplateHeaderSnapshot, 
                id=template_id, 
                client_id=client_id, 
                customer=customer.id
            )
        except Exception as e:
            return create_api_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message=f"JE Template not found or access denied: {str(e)}"
            )
        
        # Check if this is a non-bank/non-credit card template
        input_file = template.input_file if hasattr(template, 'input_file') else None
        if input_file and input_file.file_type in ['bank_statement', 'credit_card']:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="This endpoint is only for non-bank statement and non-credit card templates."
            )
        
        # Check if all attached documents are verified
        unverified_docs = []
        input_files_count = template.input_files.count()
        document_count = 0
        
        # If no input files are attached, we can't verify the template
        if input_files_count == 0:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Cannot update template status because no input files are attached to this template."
            )
            
        for input_file_snapshot in template.input_files.all():
            # Get all documents associated with this input file snapshot
            documents = MonthlyAccountingDocument.objects.filter(
                input_file_snapshot=input_file_snapshot,
                monthly_accounting=template.monthly_accounting
            )
            
            document_count += documents.count()
            
            # Check if any documents are not verified
            for doc in documents:
                if doc.status != 'verified':
                    return create_api_response(
                       status_code=status.HTTP_400_BAD_REQUEST,
                        message="Cannot update template status because some attached documents are not verified."
                    )
        
        # All documents are verified, so update the status to verified
        template.status = 'verified'
        template.save(update_fields=['status'])
        
        # Generate export file now that it's verified
        try:
            self.generate_export_file(template)
        except Exception as e:
            logger.error(f"Error generating export file: {str(e)}")
            template.status = 'pending'
            template.save(update_fields=['status'])

            # Status was already updated but export failed - leave it in verified state
            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Template Not verified. Please try again.",
                errors={"export_error": str(e)}
            )
            
        
        # Return updated template data
        serializer = self.serializer_class(template, context={'request': request})
        return create_api_response(
            status_code=status.HTTP_200_OK,
            message=f"Template Verified.",
            data=serializer.data
        )