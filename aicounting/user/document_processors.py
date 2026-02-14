# System imports
import logging
from decimal import Decimal

# Third-party imports
import pandas as pd
from django.core.exceptions import ValidationError
from django.db import transaction

# Local imports
from account.models import DimAICGLAcct

logger = logging.getLogger(__name__)


class ClientDocumentProcessor:
    """
    Handles processing of uploaded documents (COA, GL History, Vendor List)
    """

    def __init__(self, customer, uploaded_by, client=None):
        self.customer = customer
        self.uploaded_by = uploaded_by
        self.client = client

    def process_document(self, file_path, document_type):
        """
        Main method to process documents based on type
        """
        try:
            if document_type == 'chart_of_account':
                return self.process_coa_file(file_path)
            elif document_type == 'gl_history':
                return self.process_gl_history_file(file_path)
            elif document_type == 'vendor_list':
                return self.process_vendor_list_file(file_path)
            else:
                return {
                    'success': False,
                    'error': f"Unsupported document type: {document_type}",
                    'processed_count': 0,
                    'records': [],
                    'errors': [f"Unsupported document type: {document_type}"]
                }
        except Exception as e:
            logger.error(f"Error processing document: {e}")
            return {
                'success': False,
                'error': str(e),
                'processed_count': 0,
                'records': [],
                'errors': [str(e)]
            }

    def process_coa_file(self, file_path):
        """
        Process Chart of Accounts CSV/Excel file
        Expected columns: Class, SubClass, GL Code, DL Description
        """
        try:
            # Read file (supports both CSV and Excel)
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)

            # Normalize column names (remove spaces, make lowercase)
            df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')

            required_columns = ['class', 'subclass',
                                'gl_code', 'gl_description']
            missing_columns = [
                col for col in required_columns if col not in df.columns]

            if missing_columns:
                raise ValidationError(
                    f"Missing required columns: {missing_columns}")

            processed_records = []
            errors = []

            with transaction.atomic():
                # Clear existing COA for this customer and client (optional)
                # DimAICGLAcct.objects.filter(cust_id=self.customer).delete()

                for index, row in df.iterrows():
                    try:
                        # Clean and validate data
                        gl_code = str(row['gl_code']).strip()
                        account_class = str(row['class']).strip()
                        sub_class = str(row['subclass']).strip()

                        # Handle both 'gl_description' and 'dl_description' column names
                        if 'gl_description' in df.columns:
                            description = str(row['gl_description']).strip()
                        elif 'dl_description' in df.columns:
                            description = str(row['dl_description']).strip()
                        else:
                            description = ''

                        if not all([gl_code, account_class, sub_class, description]):
                            errors.append(
                                f"Row {index + 1}: Missing required data")
                            continue

                        # Use the client passed to the processor, or get the first client
                        client = self.client
                        if not client:
                            client = self.customer.dimaicclient_set.first()
                            if not client:
                                errors.append(
                                    f"Row {index + 1}: No client found for customer")
                                continue

                        # Create or update GL Account record
                        gl_account, created = DimAICGLAcct.objects.update_or_create(
                            customer=self.customer,
                            client_id=client,
                            account_number=gl_code,
                            defaults={
                                'account_name': description,
                                'description': description,
                                'account_class': account_class,
                                'sub_class': sub_class,
                                'input_user': self.uploaded_by,
                                'account_type': None  # Can be null as requested
                            }
                        )

                        processed_records.append({
                            'gl_acct_id': gl_account.id,
                            'gl_code': gl_code,
                            'account_class': account_class,
                            'sub_class': sub_class,
                            'description': description,
                            'created': created
                        })

                    except Exception as e:
                        errors.append(f"Row {index + 1}: {str(e)}")
                        logger.error(
                            f"Error processing COA row {index + 1}: {e}")

            # Check if there were too many errors that should cause failure
            total_rows = len(df)
            if total_rows == 0:
                raise ValidationError("No data rows found in the file")

            # If more than 50% of rows failed, consider it a failure
            error_percentage = len(errors) / total_rows
            if error_percentage > 0.5:
                raise ValidationError(
                    f"Too many processing errors ({len(errors)} out of {total_rows} rows). Please check your file format.")

            return {
                'success': True,
                'processed_count': len(processed_records),
                'records': processed_records,
                'errors': errors
            }

        except Exception as e:
            logger.error(f"Error processing COA file: {e}")
            return {
                'success': False,
                'error': str(e),
                'processed_count': 0,
                'records': [],
                'errors': [str(e)]
            }

    def process_gl_history_file(self, file_path):
        """
        Process Gl History List CSV/Excel file
        For now, just store the file - processing will be implemented later
        """
        return {
            'success': True,
            'message': 'Gl History  uploaded successfully. Processing will be implemented in future updates.',
            'processed_count': 0,
            'records': [],
            'errors': []
        }

    def process_vendor_list_file(self, file_path):
        """
        Process Vendor List CSV/Excel file
        For now, just store the file - processing will be implemented later
        """
        return {
            'success': True,
            'message': 'Vendor list uploaded successfully. Processing will be implemented in future updates.',
            'processed_count': 0,
            'records': [],
            'errors': []
        }
