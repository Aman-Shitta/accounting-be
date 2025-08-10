from rest_framework import serializers
from django.db import transaction
from .models import DimAICAccountant, DimAICClient, DimAICContact, DimAICClientDocument
import logging

from .document_processors import ClientDocumentProcessor

logger = logging.getLogger(__name__)


class ContactSerializer(serializers.ModelSerializer):
    """Serializer for DimAICContact model"""
    
    class Meta:
        model = DimAICContact
        fields = ['contact_name', 'contact_email', 'contact_phone']
        
    def validate_contact_email(self, value):
        """Validate email format"""
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError as DjangoValidationError
        
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")
        return value


class DimAICAccountantSerializer(serializers.ModelSerializer):
    """Serializer for DimAICAccountant model"""
    email = serializers.CharField(source='system_user.email', read_only=True)
    
    class Meta:
        model = DimAICAccountant
        fields = [
            'id', 'username', 'first_name', 'last_name', 
            'email', 'verified', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']



class ClientCreateUpdateSerializer(serializers.ModelSerializer):
    """Main serializer for creating DimAICClient with nested contacts and documents"""
    
    contacts = ContactSerializer(many=True, write_only=True, required=False)
    # Define the expected document types
    chart_of_account = serializers.FileField(required=True, help_text="Chart Of Accounts file (CSV/Excel)")
    gl_history = serializers.FileField(required=False, help_text="General Ledger History file (CSV/Excel)")
    vendor_list = serializers.FileField(required=False, help_text="Vendor List file (CSV/Excel)")

    class Meta:
        model = DimAICClient
        fields = [
            'id', 'client_id', 'client_name', 
            'contacts', "chart_of_account", "gl_history", "vendor_list"
        ]
        read_only_fields = ['id']


    def validate(self, attrs):

        return super().validate(attrs)

    def __validate_document__(self, data, client, is_update=False):
        """Ensure at least one file is provided and validate file types"""

        def validate_file_type(file_obj, doc_type):
            """Validate file extensions"""
            import os
            ext = os.path.splitext(file_obj.name)[1].lower()
            if ext not in ['.csv', '.xls', '.xlsx']:
                raise serializers.ValidationError(
                    f"{doc_type} file must be CSV or Excel format (.csv, .xls, .xlsx)"
                )
            return file_obj

        if not any(data.values()):
            if not is_update:
                raise serializers.ValidationError("At least one document file must be provided.")
            # For updates, it's okay to have no documents if just updating client info
            return data

        # Validate each file
        for doc_type, file_obj in data.items():
            if file_obj:
                validate_file_type(file_obj, doc_type)
                
                # For create operations, check if document type already exists
                if not is_update:
                    if DimAICClientDocument.objects.filter(client=client, document_type=doc_type).exists():
                        raise serializers.ValidationError({
                            "non_field_errors": [f"A file of type '{doc_type}' already exists for this client."]
                        })
        return data


    def create(self, validated_data):
        
        contacts_data = validated_data.pop('contacts', [])

        documents = {
            'chart_of_account': validated_data.pop('chart_of_account', None),
            'gl_history': validated_data.pop('gl_history', None),
            'vendor_list': validated_data.pop('vendor_list', None)
        }

        request_user = self.context['request'].user
        customer = getattr(request_user, 'customer_profile', None)

        if not customer:
            raise serializers.ValidationError("User must have a customer profile.")

        created_documents = []
        doc_process_results = {}
        client = None
        # Use atomic transaction to ensure all or nothing
        with transaction.atomic():
            try:
                # Create the client
                client = DimAICClient.objects.create(
                    customer=customer,
                    input_user=request_user,
                    **validated_data
                )

                self.__validate_document__(documents, client, is_update=False)

                # Create contacts
                for contact_data in contacts_data:
                    # Try creating the contact with explicit field assignment
                    contact = DimAICContact(
                        client_id=client,
                        contact_name=contact_data['contact_name'],
                        contact_email=contact_data['contact_email'],
                        contact_phone=contact_data['contact_phone']
                    )
                    contact.save()

                for doc_type, file_obj in documents.items():
                    if file_obj:
                        try:
                            document = DimAICClientDocument.objects.create(
                                client=client,
                                document_type=doc_type,
                                file=file_obj,
                                uploaded_by=request_user
                            )
                                        
                            # Create the document record
                            created_documents.append(document)
                            
                            # Process the document
                            # Initialize the document processor
                            processor = ClientDocumentProcessor(
                                customer=client.customer, 
                                uploaded_by=request_user,
                                client=client
                            )

                            # For Azure storage, we need to download the file content
                            from django.core.files.storage import default_storage
                            with default_storage.open(document.file.name, 'rb') as azure_file:
                                # Create a temporary file for processing
                                import tempfile
                                import os
                                
                                with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as temp_file:
                                    temp_file.write(azure_file.read())
                                    temp_file_path = temp_file.name
                                
                                try:
                                    result = processor.process_document(temp_file_path, doc_type)
                                except Exception as e:
                                    raise e
                                finally:
                                    # Clean up temporary file
                                    if os.path.exists(temp_file_path):
                                        os.remove(temp_file_path)

                            # Check if processing failed
                            if not result['success']:
                                # Processing failed - cleanup files and raise error to rollback transaction
                                from django.core.files.storage import default_storage
                                for doc in created_documents:
                                    if doc.file:
                                        try:
                                            default_storage.delete(doc.file.name)
                                            logger.info(f"Cleaned up file from Azure: {doc.file.name}")
                                        except Exception as cleanup_error:
                                            logger.error(f"Error cleaning up file {doc.file.name}: {cleanup_error}")
                                
                                raise Exception(f"Processing failed for {doc_type}: {result.get('error', 'Unknown error')}")
                            
                            doc_process_results[doc_type] = {
                                'document_id': document.id,
                                'processing_result': result,
                                'success': result['success']
                            }
                            
                            # Log processing results
                            logger.info(f"Successfully processed {doc_type} document. "
                                      f"Processed {result['processed_count']} records.")
                            if result['errors']:
                                logger.warning(f"Processing completed with {len(result['errors'])} errors: {result['errors']}")
                                
                        except Exception as e:
                            # Processing error - cleanup files and raise error to rollback transaction
                            logger.error(f"Error processing {doc_type} document: {str(e)}")
                            import os, sys
                            exc_type, exc_obj, exc_tb = sys.exc_info()
                            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                            print(exc_type, fname, exc_tb.tb_lineno)
                            raise e


            except Exception as e:
                import os, sys
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print(exc_type, fname, exc_tb.tb_lineno)

        return client

    def update(self, instance, validated_data):
        """
        Update client with support for contacts and documents
        - Only one contact allowed per client (update existing or create new)
        - Documents: Allow adding missing documents, error if document type already exists
        """
        contacts_data = validated_data.pop('contacts', [])
        documents = {
            'chart_of_account': validated_data.pop('chart_of_account', None),
            'gl_history': validated_data.pop('gl_history', None),
            'vendor_list': validated_data.pop('vendor_list', None)
        }

        request_user = self.context['request'].user

        with transaction.atomic():
            try:
                # Update basic client fields
                # instance.client_name = validated_data.get('client_name', instance.client_name)
                # not allowing name change as this chnages blob storgae path
                instance.street = validated_data.get('street', instance.street)
                instance.city = validated_data.get('city', instance.city)
                instance.state = validated_data.get('state', instance.state)
                instance.zip_code = validated_data.get('zip_code', instance.zip_code)
                instance.save()

                # Handle contacts update (only one contact allowed)
                if contacts_data:
                    if len(contacts_data) > 1:
                        raise serializers.ValidationError("Only one contact is allowed per client.")
                    
                    contact_data = contacts_data[0]
                    existing_contact = DimAICContact.objects.filter(client_id=instance).first()
                    
                    if existing_contact:
                        # Update existing contact
                        existing_contact.contact_name = contact_data.get('contact_name', existing_contact.contact_name)
                        existing_contact.contact_email = contact_data.get('contact_email', existing_contact.contact_email)
                        existing_contact.contact_phone = contact_data.get('contact_phone', existing_contact.contact_phone)
                        existing_contact.save()
                        logger.info(f"Updated existing contact for client {instance.client_id}")
                    else:
                        # Create new contact
                        DimAICContact.objects.create(
                            client_id=instance,
                            contact_name=contact_data['contact_name'],
                            contact_email=contact_data['contact_email'],
                            contact_phone=contact_data['contact_phone']
                        )
                        logger.info(f"Created new contact for client {instance.client_id}")

                # Handle documents update
                created_documents = []
                doc_process_results = {}
                
                for doc_type, file_obj in documents.items():
                    if file_obj:
                        
                        
                        # Check if document type already exists
                        existing_doc = DimAICClientDocument.objects.filter(
                            client=instance, 
                            document_type=doc_type
                        ).first()
                        
                        if existing_doc:
                            raise serializers.ValidationError({
                                doc_type: [f"A document of type '{doc_type}' already exists for this client. Please delete the existing document first if you want to replace it."]
                            })
                        
                        try:
                            # Create new document
                            document = DimAICClientDocument.objects.create(
                                client=instance,
                                document_type=doc_type,
                                file=file_obj,
                                uploaded_by=request_user
                            )
                            
                            created_documents.append(document)
                            
                            # Process the document
                            processor = ClientDocumentProcessor(
                                customer=instance.customer,
                                uploaded_by=request_user,
                                client=instance
                            )
                            
                            # For Azure storage, we need to download the file content
                            from django.core.files.storage import default_storage
                            with default_storage.open(document.file.name, 'rb') as azure_file:
                                # Create a temporary file for processing
                                import tempfile
                                import os
                                
                                with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as temp_file:
                                    temp_file.write(azure_file.read())
                                    temp_file_path = temp_file.name
                                
                                try:
                                    result = processor.process_document(temp_file_path, doc_type)
                                finally:
                                    # Clean up temporary file
                                    if os.path.exists(temp_file_path):
                                        os.remove(temp_file_path)
                            
                            if not result['success']:
                                # Processing failed - cleanup files and raise error
                                for doc in created_documents:
                                    if doc.file and doc.file.path:
                                        import os
                                        if os.path.exists(doc.file.path):
                                            os.remove(doc.file.path)
                                
                                raise Exception(f"Processing failed for {doc_type}: {result.get('error', 'Unknown error')}")
                            
                            doc_process_results[doc_type] = {
                                'document_id': document.id,
                                'processing_result': result,
                                'success': result['success']
                            }
                            
                            logger.info(f"Successfully processed {doc_type} document for client {instance.client_id}. "
                                      f"Processed {result['processed_count']} records.")
                            
                        except Exception as e:
                            logger.error(f"Error processing {doc_type} document: {str(e)}")
                            raise

            except Exception as e:
                import os, sys
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print(exc_type, fname, exc_tb.tb_lineno)
                raise

        return instance


class ClientDocumentSerializer(serializers.ModelSerializer):
    """Serializer for DimAICClientDocument model"""

    class Meta:
        model = DimAICClientDocument
        fields = ['document_type', 'file']


class ClientRetrieveSerializer(serializers.ModelSerializer):
    """Serializer for retrieving DimAICClient with nested contacts and documents"""
    
    contacts = ContactSerializer(many=True, read_only=True)
    documents = ClientDocumentSerializer(many=True, read_only=True)
    assigned_accountants = DimAICAccountantSerializer(many=True, read_only=True)

    class Meta:
        model = DimAICClient
        fields = [
            'id', 'client_id', 'client_name',
            'contacts', 'documents', 'assigned_accountants',
            'created_at', 'updated_at',
        ]


class ClientAccountantAssignmentSerializer(serializers.Serializer):
    """Serializer for appending accountants to a client (not replacing)"""
    
    assigned_accountants = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        help_text="List of accountant IDs to add to the client"
    )
    
    def validate_assigned_accountants(self, value):
        """Validate that all accountant IDs exist and belong to the customer"""
        customer = self.context.get('customer')
        if not customer:
            raise serializers.ValidationError("Customer context is required")
        
        # Check if all provided accountants belong to the customer and exist
        valid_accountants = customer.accountants.filter(id__in=value)
        valid_ids = set(valid_accountants.values_list('id', flat=True))
        invalid_ids = set(value) - valid_ids
        
        if invalid_ids:
            raise serializers.ValidationError(
                f"Invalid accountant IDs: {list(invalid_ids)}. Accountants must belong to your organization."
            )
        
        return list(valid_accountants)
    
    def update(self, instance, validated_data):
        """Append accountants to the client"""
        accountants_to_add = validated_data.get('assigned_accountants', [])
        
        # Get currently assigned accountant IDs
        current_accountants = set(instance.assigned_accountants.values_list('id', flat=True))
        
        # Add new accountants without removing existing ones
        for accountant in accountants_to_add:
            if accountant.id not in current_accountants:
                instance.assigned_accountants.add(accountant)
        
        return instance


class ClientUpdateSerializer(serializers.ModelSerializer):
    """Separate serializer for updating client basic information"""
    
    class Meta:
        model = DimAICClient
        fields = [
            'client_name', 'street', 'city', 'state', 'zip_code'
        ]
        
    def update(self, instance, validated_data):
        instance.client_name = validated_data.get('client_name', instance.client_name)
        instance.street = validated_data.get('street', instance.street)
        instance.city = validated_data.get('city', instance.city)
        instance.state = validated_data.get('state', instance.state)
        instance.zip_code = validated_data.get('zip_code', instance.zip_code)
        instance.save()
        return instance


class ClientDocumentSerializer(serializers.ModelSerializer):
    """Serializer for viewing client documents with secure URLs"""
    
    secure_url = serializers.SerializerMethodField()
    
    class Meta:
        model = DimAICClientDocument
        fields = [
            'id', 'document_type', 'created_at', 'updated_at',
            'secure_url',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_secure_url(self, obj):
        """Get secure temporary URL for the document with 10-minute expiry"""
        return obj.get_secure_url(expire_minutes=10)


class ClientDocumentUploadSerializer(serializers.Serializer):
    """Serializer for uploading multiple documents with file types as keys"""
    
    # Define the expected document types
    gl_history = serializers.FileField(required=False, help_text="General Ledger History file (CSV/Excel)")
    vendor_list = serializers.FileField(required=False, help_text="Vendor List file (CSV/Excel)")
    
    def validate(self, data):
        """Ensure at least one file is provided and validate file types"""
        if not any(data.values()):
            raise serializers.ValidationError("At least one document file must be provided.")
        
        # Validate each file
        for doc_type, file_obj in data.items():
            if file_obj:
                self.validate_file_type(file_obj, doc_type)
        
                client = self.context["client"]

                if DimAICClientDocument.objects.filter(client=client, document_type=doc_type).exists():
                    raise serializers.ValidationError({
                        "non_field_errors": [f"A file of type '{doc_type}' already exists for this client."]
                    })
        return data
    
    def validate_file_type(self, file_obj, doc_type):
        """Validate file extensions"""
        import os
        ext = os.path.splitext(file_obj.name)[1].lower()
        if ext not in ['.csv', '.xls', '.xlsx']:
            raise serializers.ValidationError(
                f"{doc_type} file must be CSV or Excel format (.csv, .xls, .xlsx)"
            )
        return file_obj
    
    def create(self, validated_data):
        """Create multiple document records and process them"""
        client = self.context['client']
        uploaded_by = self.context['uploaded_by']
        
        results = {}
        created_documents = []
        
        try:
            # Initialize the document processor
            processor = ClientDocumentProcessor(
                customer=client.customer, 
                uploaded_by=uploaded_by,
                client=client
            )
            
            with transaction.atomic():
                for doc_type, file_obj in validated_data.items():
                    if file_obj:
                        # Create the document record
                        document = DimAICClientDocument.objects.create(
                            client=client,
                            document_type=doc_type,
                            file=file_obj,
                            uploaded_by=uploaded_by
                        )
                        created_documents.append(document)
                        
                        # Process the document
                        try:
                            # For Azure storage, we need to download the file content
                            from django.core.files.storage import default_storage
                            with default_storage.open(document.file.name, 'rb') as azure_file:
                                # Create a temporary file for processing
                                import tempfile
                                import os
                                
                                with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as temp_file:
                                    temp_file.write(azure_file.read())
                                    temp_file_path = temp_file.name
                                
                                try:
                                    result = processor.process_document(temp_file_path, doc_type)
                                finally:
                                    # Clean up temporary file
                                    if os.path.exists(temp_file_path):
                                        os.remove(temp_file_path)
                            
                            # Check if processing failed
                            if not result['success']:
                                # Processing failed - cleanup files and raise error to rollback transaction
                                for doc in created_documents:
                                    if doc.file and doc.file.path:
                                        import os
                                        if os.path.exists(doc.file.path):
                                            os.remove(doc.file.path)
                                
                                raise Exception(f"Processing failed for {doc_type}: {result.get('error', 'Unknown error')}")
                            
                            results[doc_type] = {
                                'document_id': document.id,
                                'processing_result': result,
                                'success': result['success']
                            }
                            
                            # Log processing results
                            logger.info(f"Successfully processed {doc_type} document. "
                                      f"Processed {result['processed_count']} records.")
                            if result['errors']:
                                logger.warning(f"Processing completed with {len(result['errors'])} errors: {result['errors']}")
                                
                        except Exception as e:
                            # Processing error - cleanup files and raise error to rollback transaction
                            logger.error(f"Error processing {doc_type} document: {str(e)}")
                            
                            # Delete all uploaded files from Azure storage
                            from django.core.files.storage import default_storage
                            for doc in created_documents:
                                if doc.file:
                                    try:
                                        default_storage.delete(doc.file.name)
                                        logger.info(f"Cleaned up file from Azure: {doc.file.name}")
                                    except Exception as cleanup_error:
                                        logger.error(f"Error cleaning up file {doc.file.name}: {cleanup_error}")
                            
                            raise Exception(f"Document processing failed for {doc_type}: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error creating/processing documents: {str(e)}")
            raise serializers.ValidationError(f"Document creation and processing failed: {str(e)}")
        
        return {
            'documents': created_documents,
            'processing_results': results
        }

