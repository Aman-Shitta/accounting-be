from rest_framework import serializers
from .models import DimAICClient, DimAICContact, DimAICClientDocument


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = DimAICContact
        fields = ['contact_type', 'contact']


class ClientDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DimAICClientDocument
        fields = ['document_type', 'file']


class ClientSerializer(serializers.ModelSerializer):
    contacts = ContactSerializer(many=True, write_only=True)
    documents = ClientDocumentSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = DimAICClient
        fields = [
            'client_id', 'name', 'street', 'city', 'state', 'zip_code',
            'contacts', 'documents'
        ]

    def create(self, validated_data):
        contacts_data = validated_data.pop('contacts', [])
        documents_data = validated_data.pop('documents', [])

        request_user = self.context['request'].user
        customer = getattr(request_user, 'customer_profile', None)

        if not customer:
            raise serializers.ValidationError("Not a customer.")

        client = DimAICClient.objects.create(
            customer=customer,
            input_user=request_user,
            **validated_data
        )

        # Save contacts
        for contact in contacts_data:
            DimAICContact.objects.create(
                client_id=client,
                contact_type=contact['contact_type'],
                contact=contact['contact'],
                reg_flg=False,
                input_user=request_user
            )

        # Save documents
        for doc in documents_data:
            DimAICClientDocument.objects.create(
                client=client,
                document_type=doc['document_type'],
                file=doc['file'],
                uploaded_by=request_user
            )

        return client

    def update(self, instance, validated_data):
        instance.name = validated_data.get('name', instance.name)
        instance.street = validated_data.get('street', instance.street)
        instance.city = validated_data.get('city', instance.city)
        instance.state = validated_data.get('state', instance.state)
        instance.zip_code = validated_data.get('zip_code', instance.zip_code)
        instance.save()
        return instance


class ClientRetrieveSerializer(serializers.ModelSerializer):
    contacts = serializers.SerializerMethodField()
    documents = ClientDocumentSerializer(many=True, read_only=True, source="documents")

    class Meta:
        model = DimAICClient
        fields = [
            'client_id', 'name', 'street', 'city', 'state', 'zip_code',
            'contacts', 'documents'
        ]

    def get_contacts(self, obj):
        contacts = DimAICContact.objects.filter(client_id=obj)
        return ContactSerializer(contacts, many=True).data
