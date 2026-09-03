import csv
import io
import logging
from decimal import Decimal

from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated

from account.accounting.je_accounting_serializers import (
    JETemplateDataSerializer,
    JETemplateStatusUpdateSerializer,
    ManualValueUpdateSerializer,
)
from account.models import (
    FactAICJETemplateAttributeSnapshot,
    FactAICJETemplateHeaderSnapshot,
    MonthlyAccountingDocument,
    MonthlyTemplateManualAttributeItem,
    FactAICMonthlyAccounting
)
from aicounting.response import create_api_response
from aicounting.constants import BANKING_DOCS

from authentication import authenticate
from authentication.permissions import IsCustomerOrAccountant


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

        # Check if this is a bank statement or credit card document
        is_bank_or_cc = False
        if hasattr(template_snapshot, 'input_file') and template_snapshot.input_file and \
           template_snapshot.input_file.file_type in BANKING_DOCS:
            is_bank_or_cc = True

        # For non-bank/cc documents, only generate if status is verified
        if not is_bank_or_cc and \
           not getattr(template_snapshot, 'status', None) == 'verified' and \
           not template_snapshot.is_object:
            # Don't generate for unverified non-bank, non-object templates
            logger.error(
                f"Skipping export generation for unverified template {template_snapshot.id}")
            return

        # Get template attributes
        template_attributes = JETemplateDataSerializer(
            template_snapshot
        ).data['attributes']

        # Generate CSV file
        filename = "je_template.csv"
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(['GL Account Code', 'GL Account Name',
                         'Description', 'Debit', 'Credit'])
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

        template = get_object_or_404(
            FactAICJETemplateHeaderSnapshot, id=template_id, client_id=client, customer=customer.id)

        serializer = self.serializer_class(
            template, context={'request': request})

        return create_api_response(
            data=serializer.data,
            message="Template details loaded.",
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
                message="Please correct the errors and try again.",
                errors=serializer.errors
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
                message="You do not have permission to perform this action."
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
            logger.error(f"Error fetching template: {str(e)}", exc_info=True)
            return create_api_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Template not found or you do not have access."
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
                    error_messages.append(
                        f"Attribute {attribute_id} is not a manual entry and cannot be updated.")
            except Exception as e:
                logger.error(f"Error updating attribute {attribute_id}: {str(e)}", exc_info=True)
                error_messages.append(
                    f"Error updating attribute {attribute_id}: {str(e)}")

        # If no attributes were updated successfully, return an error
        if not updated_attributes:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="No changes were applied. Please review the provided values.",
                errors={"values": error_messages}
            )

        # Generate export file with updated values only if this is a bank or cc document
        # or if the template is already verified
        is_bank_or_cc = False
        if hasattr(template, 'input_file') and template.input_file and \
           template.input_file.file_type in BANKING_DOCS:
            is_bank_or_cc = True

        if is_bank_or_cc or getattr(template, 'status', None) == 'verified' or template.is_object:
            try:
                self.generate_export_file(template)
            except Exception as e:
                logger.error(f"Error generating export file: {str(e)}")
                # Continue even if export file generation fails

        # Return updated template data
        serializer = self.serializer_class(
            template, context={'request': request})

        # Create appropriate message
        message = f"Successfully updated {len(updated_attributes)} manual entries."
        if len(error_messages) > 0:
            message += f" {len(error_messages)} entries had errors: {'; '.join(error_messages)}"

        # For non-bank/cc documents that aren't verified, remind user to verify
        is_bank_or_cc = False
        if hasattr(template, 'input_file') and template.input_file and \
           template.input_file.file_type in BANKING_DOCS:
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
                message="Please correct the errors and try again.",
                errors=serializer.errors
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
                message="You do not have permission to perform this action."
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
            logger.error(f"Error fetching template snapshot: {str(e)}", exc_info=True)
            return create_api_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Template not found or you do not have access."
            )

        # Check if this is a non-bank/non-credit card template
        input_file = template.input_file if hasattr(
            template, 'input_file') else None
        if input_file and input_file.file_type in BANKING_DOCS:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="This action is only available for non-banking templates."
            )

        # Check if all attached documents are verified
        unverified_docs = []
        input_files_count = template.input_files.count()
        document_count = 0

        # If no input files are attached, we can't verify the template
        if input_files_count == 0:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Cannot verify template because no documents are attached."
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
                        message="Cannot verify template because some attached documents are not yet verified."
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
                message="Verification failed. Please try again."
            )

        # Return updated template data
        serializer = self.serializer_class(
            template, context={'request': request})
        return create_api_response(
            status_code=status.HTTP_200_OK,
            message="Template verified successfully.",
            data=serializer.data
        )


class JEAccountingVerifyView(generics.GenericAPIView):
    """
    View for verifying JE templates and generating export files.

    This replaces the generate_export_file logic from MonthlyAccountingDocumentStatusUpdateView.
    Users will verify the JE template directly instead of the document.

    For bank statements and credit cards:
    - Always has only one file attached
    - User can simply verify and generate the file

    For non-bank/credit card documents:
    - Must check if all attached documents are verified first
    - For non-is_object templates, validates that sum of debit attributes equals sum of credit attributes
    - Raises proper errors if validation fails
    """

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountant]

    serializer_class = JETemplateDataSerializer

    @staticmethod
    def validate_debit_credit_balance(template_snapshot):
        """
        Validate that sum of debits equals sum of credits for non-object templates.
        Also validates that all entries have valid numeric values.
        Returns (is_valid, error_message, debit_sum, credit_sum)
        """

        # Get template attributes data
        template_data = JETemplateDataSerializer(template_snapshot).data
        attributes = template_data.get('attributes', [])

        debit_sum = Decimal('0')
        credit_sum = Decimal('0')
        invalid_entries = []

        for idx, attr in enumerate(attributes):
            debit_value = attr.get('debit', '')
            credit_value = attr.get('credit', '')
            description = attr.get('description', f'Attribute {idx + 1}')

            # Check if both debit and credit are empty or invalid
            has_valid_debit = False
            has_valid_credit = False

            # Validate debit value
            if debit_value and str(debit_value).strip():
                try:
                    debit_decimal = Decimal(str(debit_value))
                    debit_sum += debit_decimal
                    has_valid_debit = True
                except (ValueError, TypeError, Exception) as e:
                    logger.error(
                        f"Error parsing debit value '{debit_value}': {str(e)}")
                    invalid_entries.append(
                        f"'{description}' has invalid debit value: '{debit_value}'")
                    break

            # Validate credit value
            if credit_value and str(credit_value).strip():
                try:
                    credit_decimal = Decimal(str(credit_value))
                    credit_sum += credit_decimal
                    has_valid_credit = True
                except (ValueError, TypeError, Exception) as e:
                    logger.error(
                        f"Error parsing credit value '{credit_value}': {str(e)}")
                    invalid_entries.append(
                        f"'{description}' has invalid credit value: '{credit_value}'")
                    break

            # Check if entry has neither valid debit nor valid credit
            if not has_valid_debit and not has_valid_credit:
                invalid_entries.append(
                    f"'{description}' has no valid debit or credit value")
                break

        # If there are any invalid entries, return error
        if invalid_entries:
            error_msg = "Cannot verify template with incomplete or invalid entries: "
            return False, error_msg, debit_sum, credit_sum

        # Check if debits equal credits
        if debit_sum != credit_sum:
            return False, f"Sum of debits ({debit_sum}) does not equal sum of credits ({credit_sum})", debit_sum, credit_sum

        return True, "", debit_sum, credit_sum

    @staticmethod
    def generate_export_file(template_snapshot):
        """
        Generate CSV export file for JE template
        """

        # Get template attributes
        template_attributes = JETemplateDataSerializer(
            template_snapshot
        ).data['attributes']

        # Generate CSV file
        filename = f"je_template_{template_snapshot.id}.csv"
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(['GL Account Code', 'GL Account Name',
                         'Description', 'Debit', 'Credit'])
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

    def post(self, request, client_id, accounting_id, template_id, *args, **kwargs):
        """
        Verify a JE template and generate the export file.

        POST /api/clients/{client_id}/accounting/monthly/{accounting_id}/je_template/{template_id}/verify/

        Body: {"status": "verified"}
        """
        # Validate IDs
        for var_name, value in [("client ID", client_id), ("accounting ID", accounting_id), ("template ID", template_id)]:
            try:
                int(value)
            except ValueError:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid {var_name}."
                )
        # Validate request data
        serializer = JETemplateStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Please correct the errors and try again.",
                errors=serializer.errors
            )

        # Get user and customer
        user = request.user
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            customer = accountant.customer
        else:
            return create_api_response(
                status_code=status.HTTP_403_FORBIDDEN,
                message="You do not have permission to perform this action."
            )
        # Get the JE template snapshot with proper authorization checks
        try:

            # First verify the monthly accounting session exists and user has access
            if hasattr(user, 'customer_profile'):
                monthly_accounting = get_object_or_404(
                    FactAICMonthlyAccounting.objects.select_related('client'),
                    id=accounting_id,
                    client_id=client_id,
                    client__customer=user.customer_profile,
                    is_deleted=False
                )
            elif hasattr(user, 'accountant_profile'):
                monthly_accounting = get_object_or_404(
                    FactAICMonthlyAccounting.objects.select_related('client'),
                    id=accounting_id,
                    client_id=client_id,
                    client__customer=user.accountant_profile.customer,
                    client__assigned_accountants=user.accountant_profile,
                    is_deleted=False
                )

            # Get the template
            template = get_object_or_404(
                FactAICJETemplateHeaderSnapshot,
                id=template_id,
                monthly_accounting=monthly_accounting,
                client_id=client_id,
                customer=customer.id
            )
        except Exception as e:
            logger.error(f"Error fetching template snapshot for verification: {str(e)}", exc_info=True)
            return create_api_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Template not found or you do not have access."
            )

        # Check if template is already verified
        if template.status == 'verified':
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="This template has already been verified."
            )

        # Determine if this is a bank/credit card template
        is_bank_or_cc = False
        input_file_snapshots = template.input_files.all()

        if input_file_snapshots.exists():
            first_input_file = input_file_snapshots.first()
            if first_input_file and first_input_file.file_type in BANKING_DOCS:
                is_bank_or_cc = True

        # For non-bank/credit card templates, perform additional validations
        if not is_bank_or_cc:
            # Check if any input files are attached
            if input_file_snapshots.exists():

                # Check if all attached documents are verified
                for input_file_snapshot in input_file_snapshots:
                    documents = MonthlyAccountingDocument.objects.filter(
                        input_file_snapshot=input_file_snapshot,
                        monthly_accounting=template.monthly_accounting
                    )

                    for doc in documents:
                        if doc.status != 'verified':
                            return create_api_response(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                message=f"Cannot verify template because document '{input_file_snapshot.name}' is not verified. Please verify all attached documents first."
                            )

            # For non-object templates, validate debit/credit balance
            if not template.is_object:
                is_valid, error_msg, debit_sum, credit_sum = self.validate_debit_credit_balance(
                    template)
                logger.error("debit_sum, credit_sum :: ",
                             debit_sum, credit_sum)
                if not is_valid:
                    return create_api_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=f"Cannot verify template: {error_msg}",
                        data={
                            "error": error_msg,
                            "debit_sum": str(debit_sum),
                            "credit_sum": str(credit_sum)
                        }
                    )

        # All validations passed, update status to verified
        template.status = 'verified'
        template.save(update_fields=['status'])

        # Generate export file
        try:
            self.generate_export_file(template)
        except Exception as e:
            logger.error(
                f"Error generating export file for template {template_id}: {str(e)}")
            # Rollback status change
            template.status = 'pending'
            template.save(update_fields=['status'])

            return create_api_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Verification failed. Please try again."
            )

        # Return updated template data
        response_serializer = self.serializer_class(
            template, context={'request': request})
        return create_api_response(
            status_code=status.HTTP_200_OK,
            message="Template verified successfully.",
            data=response_serializer.data
        )


class JEAttributeEditView(generics.GenericAPIView):
    """
    View for editing JE template attributes.

    Allows editing of:
    1. Manual attributes (where debit='manual' or credit='manual')
    2. All attributes for memo-type documents (sales) where all attributes are manual

    Users can update the debit or credit values with float/int values.
    """

    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomerOrAccountant]

    def patch(self, request, client_id, accounting_id, template_id, attribute_id, *args, **kwargs):
        """
        Update a specific JE template attribute.

        PATCH /api/clients/{client_id}/accounting/monthly/{accounting_id}/je_template/{template_id}/attribute/{attribute_id}/

        Body:
        {
            "debit": 150.50,  // Optional
            "credit": 200.00  // Optional
        }

        Note: Only one of debit or credit should be provided, not both.
        """
        # Validate IDs
        for var_name, value in [
            ("client ID", client_id),
            ("accounting ID", accounting_id),
            ("template ID", template_id),
            ("attribute ID", attribute_id)
        ]:
            try:
                int(value)
            except ValueError:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid {var_name}."
                )

        # Get user and customer
        user = request.user
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            customer = accountant.customer
        else:
            return create_api_response(
                status_code=status.HTTP_403_FORBIDDEN,
                message="You do not have permission to perform this action."
            )

        # Get the JE template snapshot with proper authorization checks
        try:

            # First verify the monthly accounting session exists and user has access
            if hasattr(user, 'customer_profile'):
                monthly_accounting = get_object_or_404(
                    FactAICMonthlyAccounting.objects.select_related('client'),
                    id=accounting_id,
                    client_id=client_id,
                    client__customer=user.customer_profile,
                    is_deleted=False
                )
            elif hasattr(user, 'accountant_profile'):
                monthly_accounting = get_object_or_404(
                    FactAICMonthlyAccounting.objects.select_related('client'),
                    id=accounting_id,
                    client_id=client_id,
                    client__customer=user.accountant_profile.customer,
                    client__assigned_accountants=user.accountant_profile,
                    is_deleted=False
                )

            # Get the template
            template = get_object_or_404(
                FactAICJETemplateHeaderSnapshot,
                id=template_id,
                monthly_accounting=monthly_accounting,
                client_id=client_id,
                customer=customer.id
            )

            # Get the attribute
            attribute = get_object_or_404(
                FactAICJETemplateAttributeSnapshot,
                id=attribute_id,
                je_template_snapshot=template
            )

        except Exception as e:
            logger.error(f"Error fetching template attribute snapshot: {str(e)}", exc_info=True)
            return create_api_response(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Template or attribute not found or you do not have access."
            )

        # Check if template is already verified
        if template.status == 'verified':
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Cannot modify a verified template. Please unverify it first."
            )

        # Determine if this is a memo/sales document (all attributes are manual)
        is_bank = False
        input_file_snapshots = template.input_files.all()

        if input_file_snapshots.exists():
            first_input_file = input_file_snapshots.first()
            if first_input_file and first_input_file.file_type in BANKING_DOCS:
                is_bank = True

        # Check if attribute is editable
        if attribute.debit is not None:
            is_manual_debit = attribute.debit.lower() != 'x' and not attribute.debit.isdigit()
        else:
            is_manual_debit = True

        if attribute.credit is not None:
            is_manual_credit = attribute.credit.lower(
            ) != 'x' and not attribute.credit.isdigit()
        else:
            if not is_manual_debit:
                is_manual_credit = True

        if is_bank or (not is_manual_debit and not is_manual_credit):
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="This field is read-only and cannot be edited."
            )

        # Validate request data
        debit_value = request.data.get('debit')
        credit_value = request.data.get('credit')
        description_value = request.data.get('description')

        if is_manual_debit and debit_value is None:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Please provide a debit amount."
            )

        # Validate that only one value is provided
        if is_manual_credit and credit_value is None:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Please provide a credit amount."
            )

        if is_manual_credit:
            try:
                validated_amount = Decimal(str(credit_value))
            except (ValueError, TypeError, Exception) as e:
                return create_api_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Invalid credit amount. Please enter a valid number."
                )
        else:
            try:
                validated_amount = Decimal(str(debit_value))
            except (ValueError, TypeError, Exception) as e:
                return create_api_response(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Invalid debit amount. Please enter a valid number."
                )

        if validated_amount < 0:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Amount cannot be negative."
            )
        # attribute.monthly_document_attributes
        manual_attribute, _ = MonthlyTemplateManualAttributeItem.objects.get_or_create(
            template_attribute=attribute
        )

        manual_attribute.value = validated_amount
        manual_attribute.transaction_type = "debit" if is_manual_debit else "credit" if is_manual_credit else "unknown"
        manual_attribute.gl_account = attribute.gl_account
        manual_attribute.description = description_value or manual_attribute.description

        manual_attribute.save()

        attribute.attribute_name = description_value or attribute.attribute_name
        attribute.save(update_fields=['attribute_name'])

        # Return success response
        return create_api_response(
            status_code=status.HTTP_200_OK,
            message="Amount updated successfully.",
            data={
                "attribute_id": attribute.id,
                "attribute_name": attribute.attribute_name or (attribute.input_file_attribute.name if attribute.input_file_attribute else "Unknown"),
                "debit": attribute.debit,
                "credit": attribute.credit,
                "gl_account": {
                    "id": attribute.gl_account.id if attribute.gl_account else None,
                    "account_number": attribute.gl_account.account_number if attribute.gl_account else None,
                    "account_name": attribute.gl_account.account_name if attribute.gl_account else None,
                } if attribute.gl_account else None
            }
        )
