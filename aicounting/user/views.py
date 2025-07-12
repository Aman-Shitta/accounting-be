from rest_framework import generics, permissions, status
from .models import DimAICClient, DimAICCustomer
from .serializers import ClientSerializer, ClientRetrieveSerializer

from aicounting.response import create_api_response

import logging
logger = logging.getLogger(__name__)


# aicounting/account/views.py

# class ClientListView(generics.ListAPIView):
#     permission_classes = [permissions.IsAuthenticated]
#     serializer_class = ClientRetrieveSerializer

#     def get_queryset(self):
#         user = self.request.user
#         customer = getattr(user, 'customer_profile', None)
#         return DimAICClient.objects.filter(customer=customer)

#     def get_serializer_context(self):
#         context = super().get_serializer_context()
#         context.update({"request": self.request})
#         return context

# class ClientRetrieveView(generics.RetrieveAPIView):
#     permission_classes = [permissions.IsAuthenticated]
#     serializer_class = ClientRetrieveSerializer

#     def get_queryset(self):
#         user = self.request.user
#         customer = getattr(user, 'customer_profile', None)
#         return DimAICClient.objects.filter(customer=customer)

#     def get_serializer_context(self):
#         context = super().get_serializer_context()
#         context.update({"request": self.request})
#         return context


# class ClientUpdateView(generics.UpdateAPIView):
#     permission_classes = [permissions.IsAuthenticated]
#     serializer_class = ClientRetrieveSerializer  # Use same retrieve serializer

#     def get_queryset(self):
#         user = self.request.user
#         customer = getattr(user, 'customer_profile', None)
#         return DimAICClient.objects.filter(customer=customer)

#     def get_serializer_context(self):
#         context = super().get_serializer_context()
#         context.update({"request": self.request})
#         return context


class ClientCreateView(generics.CreateAPIView):
    # permission_classes = [permissions.IsAuthenticated]
    serializer_class = ClientSerializer

    def get_queryset(self):
        user = self.request.user        
        customer = getattr(user, 'customer_profile', None)
        return DimAICClient.objects.filter(customer=customer)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context

    def create(self, request, *args, **kwargs):

        user = DimAICCustomer.objects.first()
        self.request.user = user.user
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Client creation failed.",
                data=serializer.errors
            )
        self.perform_create(serializer)

        return create_api_response(
            status.HTTP_201_CREATED,
            "Client created successfully.",
            data=serializer.data
        )
