import uuid
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated

from authentication import authenticate
from authentication.permissions import IsCustomerOrAccountant
from aicounting.response import create_api_response
from .je_accounting_serializers import JETemplateDataSerializer

from .models import FactAICJETemplateHeaderSnapshot

from django.conf import settings
from django.core.files.storage import FileSystemStorage as system_storage
from django.core.files.base import ContentFile

import logging
logger = logging.getLogger(__name__)



class JEAccountingDetailView(generics.GenericAPIView):

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountant]

    serializer_class = JETemplateDataSerializer

    @staticmethod
    def generate_export_file(template_snapshot):
        """Generate export file for JE template"""
        import io
        import csv
        from django.core.files.base import ContentFile

        if template_snapshot.input_file and template_snapshot.input_file.file_type in ['bank_statement', 'credit_card']:
            # Handle bank statement/credit card documents
            template_attributes = JETemplateDataSerializer(template_snapshot).data['attributes']

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
        else:
            # Handle non-bank document types (sales, etc.)
            if template_snapshot.is_object:
                # For is_object templates, use data from extracted attribute items
                template_attributes = JETemplateDataSerializer(template_snapshot).data['attributes']

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
            else:
                # For non-is_object templates, use GL accounts from JE template with attribute values
                template_attributes = JETemplateDataSerializer(template_snapshot).data['attributes']

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
        """Generate and save export file for JE template"""
        user = request.user
        client = kwargs['client_id']
        template_id = kwargs['template_id']

        # Get client and customer based on user authorization
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            customer = accountant.customer
        else:
            return create_api_response(status.HTTP_403_FORBIDDEN, "Access denied.")
        
        template = get_object_or_404(FactAICJETemplateHeaderSnapshot, id=template_id, client_id=client, customer=customer.id)

        try:
            self.generate_export_file(template)
            
            return create_api_response(
                data={
                    "export_file": template.je_export_file.url if template.je_export_file else None
                },
                message="Export file generated successfully.", 
                status_code=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Error generating export file for template {template_id}: {str(e)}")
            return create_api_response(
                message='Error generating export file.',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data={"error": str(e)}
            )
