from rest_framework import serializers
from django.db import transaction
from .models import DimAICClient, DimAICContact, DimAICClientDocument
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


class ClientSerializer(serializers.ModelSerializer):
    """Main serializer for creating DimAICClient with nested contacts and documents"""
    
    contacts = ContactSerializer(write_only=True, required=False)
    # Define the expected document types
    chart_of_account = serializers.FileField(required=True, help_text="Chart Of Accounts file (CSV/Excel)")
    gl_history = serializers.FileField(required=False, help_text="General Ledger History file (CSV/Excel)")
    vendor_list = serializers.FileField(required=False, help_text="Vendor List file (CSV/Excel)")

    class Meta:
        model = DimAICClient
        fields = [
            'id', 'client_id', 'client_name', 'street', 'city', 'state', 'zip_code',
            'contacts', "chart_of_account", "gl_history", "vendor_list"
        ]
        read_only_fields = ['id']


    def validate(self, attrs):
        return super().validate(attrs)

    def __validate_document__(self, data, client):
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
            raise serializers.ValidationError("At least one document file must be provided.")
        
        # Validate each file
        for doc_type, file_obj in data.items():
            if file_obj:
                validate_file_type(file_obj, doc_type)
        

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

        # Use atomic transaction to ensure all or nothing
        with transaction.atomic():
            try:
                # Create the client
                client = DimAICClient.objects.create(
                    customer=customer,
                    input_user=request_user,
                    **validated_data
                )

                self.__validate_document__(documents, client)

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

                            
                            file_path = document.file.path
                            result = processor.process_document(file_path, doc_type)

                            # Check if processing failed
                            if not result['success']:
                                # Processing failed - cleanup files and raise error to rollback transaction
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
                            
                            # Log processing results
                            logger.info(f"Successfully processed {doc_type} document. "
                                      f"Processed {result['processed_count']} records.")
                            if result['errors']:
                                logger.warning(f"Processing completed with {len(result['errors'])} errors: {result['errors']}")
                                
                        except Exception as e:
                            # Processing error - cleanup files and raise error to rollback transaction
                            logger.error(f"Error processing {doc_type} document: {str(e)}")


            except Exception as e:
                import os, sys
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print(exc_type, fname, exc_tb.tb_lineno)

        return client

    def update(self, instance, validated_data):
        # Update basic client fields
        instance.client_name = validated_data.get('client_name', instance.client_name)
        instance.id = validated_data.get('id', instance.id)
        instance.street = validated_data.get('street', instance.street)
        instance.city = validated_data.get('city', instance.city)
        instance.state = validated_data.get('state', instance.state)
        instance.zip_code = validated_data.get('zip_code', instance.zip_code)
        instance.save()
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

    class Meta:
        model = DimAICClient
        fields = [
            'id', 'client_id', 'client_name',
            'contacts', 'documents',
            'created_at', 'updated_at',
        ]


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
                            file_path = document.file.path
                            result = processor.process_document(file_path, doc_type)
                            
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
                            
                            # Delete all uploaded files
                            for doc in created_documents:
                                if doc.file and doc.file.path:
                                    import os
                                    if os.path.exists(doc.file.path):
                                        os.remove(doc.file.path)
                            
                            raise Exception(f"Document processing failed for {doc_type}: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error creating/processing documents: {str(e)}")
            raise serializers.ValidationError(f"Document creation and processing failed: {str(e)}")
        
        return {
            'documents': created_documents,
            'processing_results': results
        }

