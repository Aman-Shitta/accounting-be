from rest_framework import generics, permissions
from .models import DimAICClient
from .serializers import ClientSerializer, ClientRetrieveSerializer

import logging
logger = logging.getLogger(__name__)


class ClientCreateView(generics.CreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ClientSerializer

    def get_queryset(self):
        user = self.request.user
        customer = getattr(user, 'customer_profile', None)
        return DimAICClient.objects.filter(customer=customer)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context

class ClientListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ClientRetrieveSerializer

    def get_queryset(self):
        user = self.request.user
        customer = getattr(user, 'customer_profile', None)
        return DimAICClient.objects.filter(customer=customer)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context

class ClientRetrieveView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ClientRetrieveSerializer

    def get_queryset(self):
        user = self.request.user
        customer = getattr(user, 'customer_profile', None)
        return DimAICClient.objects.filter(customer=customer)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context


class ClientUpdateView(generics.UpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ClientRetrieveSerializer  # Use same retrieve serializer

    def get_queryset(self):
        user = self.request.user
        customer = getattr(user, 'customer_profile', None)
        return DimAICClient.objects.filter(customer=customer)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context
