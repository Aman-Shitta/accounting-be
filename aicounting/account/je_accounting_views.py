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
