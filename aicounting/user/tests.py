from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from .models import DimAICClient, DimAICCustomer, DimAICContact, DimAICClientDocument

User = get_user_model()


class ClientCreateViewTestCase(APITestCase):
    """Test cases for client creation functionality"""
    
    def setUp(self):
        # Create a test user and customer
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.customer = DimAICCustomer.objects.create(
            user=self.user,
            # Add other required fields based on your DimAICCustomer model
        )
    
    def test_create_client_basic(self):
        """Test creating a client with basic information"""
        client_data = {
            'client_name': 'Test Client',
            'id': 'TC001',
            'street': '123 Test Street',
            'city': 'Test City',
            'state': 'TX',
            'zip_code': 12345,
        }
        
        url = reverse('client:client-create')
        response = self.client.post(url, client_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(DimAICClient.objects.count(), 1)
        
        client = DimAICClient.objects.first()
        self.assertEqual(client.client_name, 'Test Client')
        self.assertEqual(client.id, 'TC001')
    
    def test_create_client_with_contacts_and_documents(self):
        """Test creating a client with nested contacts and documents"""
        client_data = {
            'client_name': 'Test Client with Relations',
            'id': 'TC002',
            'street': '456 Test Avenue',
            'city': 'Test Town',
            'state': 'CA',
            'zip_code': 67890,
            'contacts': [
                {
                    'contact_name': 'John Doe',
                    'contact_email': 'john@example.com',
                    'contact_phone': '+1234567890'
                }
            ],
            # Note: Documents would need actual file upload for proper testing
        }
        
        url = reverse('client:client-create')
        response = self.client.post(url, client_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(DimAICClient.objects.count(), 1)
        self.assertEqual(DimAICContact.objects.count(), 1)
        
        client = DimAICClient.objects.first()
        contact = DimAICContact.objects.first()
        self.assertEqual(contact.client, client)
        self.assertEqual(contact.contact_name, 'John Doe')


# Create your tests here.
