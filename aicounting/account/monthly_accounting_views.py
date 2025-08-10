from django.shortcuts import get_object_or_404
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import generics, status, permissions
from rest_framework.views import APIView

from .models import FactAICMonthlyAccounting
from .monthly_accounting_serializers import (
    MonthlyAccountingCreateSerializer,
    MonthlyAccountingSerializer,
    MonthlyAccountingDetailSerializer
)
from user.models import DimAICClient
from authentication import authenticate
from authentication.permissions import IsCustomerOrAccountant
from aicounting.response import create_api_response

import logging
logger = logging.getLogger(__name__)


class MonthlyAccountingListView(generics.GenericAPIView):
    """List existing monthly accounting sessions for a specific client"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = MonthlyAccountingSerializer

    def get_queryset(self, client_id):
        """Get monthly accounting sessions with proper authorization checks"""
        user = self.request.user
        
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return FactAICMonthlyAccounting.objects.filter(
                client=client_id,
                client__customer=customer
            ).select_related('client', 'created_by').order_by('-created_at')
        
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return FactAICMonthlyAccounting.objects.filter(
                client=client_id,
                client__customer=accountant.customer,
                client__assigned_accountants=accountant
            ).select_related('client', 'created_by').order_by('-created_at')
        
        return FactAICMonthlyAccounting.objects.none()

    def get(self, request, client_id, *args, **kwargs):
        """
        List all monthly accounting sessions for a specific client.
        Supports filtering by year, status
        
        GET /api/clients/{client_id}/accounting/monthly/
        
        Query parameters:
        - year: Filter by year
        - status: Filter by status
        """
        try:
            # Verify client exists and user has access
            user = request.user
            if hasattr(user, 'customer_profile'):
                customer = user.customer_profile
                client = get_object_or_404(DimAICClient, id=client_id, customer=customer)
            elif hasattr(user, 'accountant_profile'):
                accountant = user.accountant_profile
                client = get_object_or_404(
                    DimAICClient, 
                    id=client_id, 
                    customer=accountant.customer,
                    assigned_accountants=accountant
                )
            else:
                return create_api_response(
                    status.HTTP_403_FORBIDDEN,
                    "Access denied."
                )

            queryset = self.get_queryset(client_id)
            
            # Filter by year
            year = request.query_params.get('year')
            if year:
                try:
                    year = int(year)
                    queryset = queryset.filter(year=year)
                except ValueError:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        "Invalid year parameter."
                    )
            
            # Filter by status
            status_filter = request.query_params.get('status')
            if status_filter:
                valid_statuses = [choice[0] for choice in FactAICMonthlyAccounting.STATUS_CHOICES]
                if status_filter in valid_statuses:
                    queryset = queryset.filter(status=status_filter)
                else:
                    return create_api_response(
                        status.HTTP_400_BAD_REQUEST,
                        f"Invalid status. Valid options: {', '.join(valid_statuses)}"
                    )
            
            serializer = self.serializer_class(queryset, many=True)
            
            return create_api_response(
                status.HTTP_200_OK,
                f"Monthly accounting sessions retrieved successfully for client {client.client_name}.",
                data={
                    'client': client.id,
                    'client_name': client.client_name,
                    'total_sessions': queryset.count(),
                    'monthly_accounting': serializer.data
                }
            )
        
        except Exception as e:
            logger.error(f"Error listing monthly accounting sessions for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving monthly accounting sessions.",
                data={"error": str(e)}
            )


class MonthlyAccountingCreateView(generics.GenericAPIView):
    """Create a new monthly accounting session for a specific client"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]

    def post(self, request, client_id, *args, **kwargs):
        """
        Create a new monthly accounting session.
        Snapshots are created automatically in the background for reference.
        
        POST /api/clients/{client_id}/accounting/monthly/create/
        
        Body:
        {
            "month": 8,
            "year": 2025
        }
        """
        try:
            # Verify client exists and user has access
            user = request.user
            if hasattr(user, 'customer_profile'):
                customer = user.customer_profile
                client = get_object_or_404(DimAICClient, id=client_id, customer=customer)
            elif hasattr(user, 'accountant_profile'):
                accountant = user.accountant_profile
                client = get_object_or_404(
                    DimAICClient, 
                    id=client_id, 
                    customer=accountant.customer,
                    assigned_accountants=accountant
                )
            else:
                return create_api_response(
                    status.HTTP_403_FORBIDDEN,
                    "Access denied."
                )

            serializer = MonthlyAccountingCreateSerializer(data=request.data)
            
            if not serializer.is_valid():
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Monthly accounting creation failed due to validation errors.",
                    data=serializer.errors
                )
            
            validated_data = serializer.validated_data
            month = validated_data['month']
            year = validated_data['year']
            
            # Check if accounting for this month/year already exists
            if FactAICMonthlyAccounting.objects.filter(
                client=client,
                month=month,
                year=year
            ).exists():
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Monthly accounting for {month}/{year} already exists for this client."
                )
            
            with transaction.atomic():
                # Create monthly accounting with snapshots (snapshots created automatically)
                monthly_accounting = FactAICMonthlyAccounting.create_monthly_accounting_with_snapshots(
                    client=client,
                    month=month,
                    year=year,
                    created_by=request.user
                )
                
                # Serialize the response (basic details only)
                response_serializer = MonthlyAccountingSerializer(monthly_accounting)
                
                return create_api_response(
                    status.HTTP_201_CREATED,
                    f"Monthly accounting for {client.client_name} - {monthly_accounting.get_month_name()} {year} has been initiated successfully.",
                    data=response_serializer.data
                )
        
        except DjangoValidationError as e:
            logger.error(f"Validation error creating monthly accounting for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Validation error occurred while creating monthly accounting.",
                data={"error": str(e)}
            )
        
        except Exception as e:
            logger.error(f"Error creating monthly accounting for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while creating monthly accounting.",
                data={"error": str(e)}
            )


class MonthlyAccountingDetailView(generics.GenericAPIView):
    """Retrieve detailed information about a monthly accounting session"""
    
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsCustomerOrAccountant]
    serializer_class = MonthlyAccountingDetailSerializer

    def get_object(self, client_id, accounting_id):
        """Get monthly accounting session with proper authorization checks"""
        user = self.request.user
        
        if hasattr(user, 'customer_profile'):
            customer = user.customer_profile
            return get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related('client', 'created_by'),
                id=accounting_id,
                client=client_id,
                client__customer=customer
            )
        elif hasattr(user, 'accountant_profile'):
            accountant = user.accountant_profile
            return get_object_or_404(
                FactAICMonthlyAccounting.objects.select_related('client', 'created_by'),
                id=accounting_id,
                client=client_id,
                client__customer=accountant.customer,
                client__assigned_accountants=accountant
            )
        else:
            return None

    def get(self, request, client_id, accounting_id, *args, **kwargs):
        """
        Retrieve basic information about a monthly accounting session.
        
        GET /api/clients/{client_id}/accounting/monthly/{accounting_id}/
        """
        try:
            accounting_id = int(accounting_id)
        except ValueError:
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Invalid accounting ID."
            )
        
        try:
            monthly_accounting = self.get_object(client_id, accounting_id)
            if not monthly_accounting:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Monthly accounting session not found or access denied."
                )
            
            serializer = self.serializer_class(monthly_accounting)
            
            return create_api_response(
                status.HTTP_200_OK,
                "Monthly accounting details retrieved successfully.",
                data=serializer.data
            )
        
        except Exception as e:
            logger.error(f"Error retrieving monthly accounting {accounting_id} for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while retrieving monthly accounting details.",
                data={"error": str(e)}
            )

    def patch(self, request, client_id, accounting_id, *args, **kwargs):
        """
        Update the status of a monthly accounting session.
        
        PATCH /api/clients/{client_id}/accounting/monthly/{accounting_id}/
        
        Body:
        {
            "status": "in_progress" | "completed" | "failed"
        }
        """
        try:
            accounting_id = int(accounting_id)
        except ValueError:
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Invalid accounting ID."
            )
        
        try:
            monthly_accounting = self.get_object(client_id, accounting_id)
            if not monthly_accounting:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Monthly accounting session not found or access denied."
                )
            
            new_status = request.data.get('status')
            if not new_status:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Status is required."
                )
            
            valid_statuses = [choice[0] for choice in FactAICMonthlyAccounting.STATUS_CHOICES]
            if new_status not in valid_statuses:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid status. Valid options: {', '.join(valid_statuses)}"
                )
            
            with transaction.atomic():
                monthly_accounting.status = new_status
                
                # Set completed_at timestamp if status is completed
                if new_status == 'completed':
                    monthly_accounting.completed_at = timezone.now()
                
                monthly_accounting.save()
                
                serializer = MonthlyAccountingSerializer(monthly_accounting)
                
                return create_api_response(
                    status.HTTP_200_OK,
                    f"Status updated to '{new_status}' successfully.",
                    data=serializer.data
                )
        
        except Exception as e:
            logger.error(f"Error updating status for accounting {accounting_id}, client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while updating status.",
                data={"error": str(e)}
            )

    def delete(self, request, client_id, accounting_id, *args, **kwargs):
        """
        Delete a monthly accounting session.
        Only accounting sessions with 'initiated' or 'failed' status can be deleted.
        
        DELETE /api/clients/{client_id}/accounting/monthly/{accounting_id}/
        """
        try:
            accounting_id = int(accounting_id)
        except ValueError:
            return create_api_response(
                status.HTTP_400_BAD_REQUEST,
                "Invalid accounting ID."
            )
        
        try:
            monthly_accounting = self.get_object(client_id, accounting_id)
            if not monthly_accounting:
                return create_api_response(
                    status.HTTP_404_NOT_FOUND,
                    "Monthly accounting session not found or access denied."
                )
            
            # Only allow deletion of certain statuses
            if monthly_accounting.status not in ['initiated', 'failed']:
                return create_api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Only accounting sessions with 'initiated' or 'failed' status can be deleted."
                )
            
            client_name = monthly_accounting.client.client_name
            month_name = monthly_accounting.get_month_name()
            year = monthly_accounting.year
            
            monthly_accounting.delete()
            
            return create_api_response(
                status.HTTP_200_OK,
                f"Monthly accounting for {client_name} - {month_name} {year} has been deleted successfully."
            )
        
        except Exception as e:
            logger.error(f"Error deleting monthly accounting {accounting_id} for client {client_id}: {str(e)}")
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while deleting monthly accounting.",
                data={"error": str(e)}
            )
