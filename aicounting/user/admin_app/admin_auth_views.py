from rest_framework.generics import GenericAPIView
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser
from django.contrib.auth import authenticate
from aicounting.response import create_api_response
import jwt
from datetime import datetime, timedelta
from django.conf import settings
from .serializers import (
    AdminLoginSerializer,
    AdminDashboardSerializer,
    RecentCustomerSerializer,
    CustomerStatisticsSerializer,
    CustomerDetailSerializer
)
from user.models import DimAICCustomer
from django.contrib.auth import get_user_model
from authentication.authenticate import AdminJWTAuthentication

User = get_user_model()

class AdminLoginView(GenericAPIView):
    """
    Admin login API that provides JWT tokens for superadmin users.
    Only superusers can access the invite functionality.
    """
    serializer_class = AdminLoginSerializer
    permission_classes = [AllowAny]

    def generate_jwt_token(self, user):
        """Generate JWT token for the user"""
        payload = {
            'user_id': user.id,
            'username': user.username,
            'email': user.email,
            'is_superuser': user.is_superuser,
            'is_staff': user.is_staff,
            'exp': datetime.now() + timedelta(hours=24),
            'iat': datetime.now(),
        }
        
        # Use Django SECRET_KEY for JWT signing
        secret_key = getattr(settings, 'SECRET_KEY', 'your-secret-key')
        token = jwt.encode(payload, secret_key, algorithm='HS256')
        return token

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        
        if not serializer.is_valid():
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid credentials format",
                errors=serializer.errors
            )

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        # Authenticate user
        user = authenticate(username=username, password=password)
        
        if not user:
            return create_api_response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message="Invalid credentials"
            )

        # Check if user is superuser
        if not user.is_superuser:
            return create_api_response(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Access denied. Superuser privileges required."
            )

        # Generate JWT token
        access_token = self.generate_jwt_token(user)

        return create_api_response(
            status_code=status.HTTP_200_OK,
            message="Login successful",
            data={
                'access_token': access_token,
                'token_type': 'Bearer',
                'expires_in': 86400,  # 24 hours in seconds
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'is_superuser': user.is_superuser,
                    'is_staff': user.is_staff
                }
            }
        )


class CustomerListView(GenericAPIView):
    """
    List all customers with their verification status.
    Only accessible by superadmin users.
    """
    permission_classes = [IsAdminUser]
    authentication_classes = [AdminJWTAuthentication]

    def get(self, request):
        # Double check superuser status
        if not request.user.is_superuser:
            return create_api_response(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Superuser privileges required"
            )

        # Get all customers with their status
        customers = DimAICCustomer.objects.select_related('system_user', 'input_user').all()
        
        # Serialize customer data
        customer_serializer = CustomerDetailSerializer(customers, many=True)
        
        # Calculate counts
        customer_data = customer_serializer.data
        verified_count = len([c for c in customer_data if c['verification_status'] == 'verified'])
        pending_count = len([c for c in customer_data if c['verification_status'] == 'pending'])

        return create_api_response(
            status_code=status.HTTP_200_OK,
            message="Customers retrieved successfully",
            data={
                'customers': customer_data,
                'total_count': len(customer_data),
                'verified_count': verified_count,
                'pending_count': pending_count
            }
        )


class AdminDashboardView(GenericAPIView):
    """
    Admin dashboard with summary statistics.
    """
    permission_classes = [IsAdminUser]
    authentication_classes = [AdminJWTAuthentication]

    def get(self, request):
        if not request.user.is_superuser:
            return create_api_response(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Superuser privileges required"
            )

        # Calculate statistics
        total_customers = DimAICCustomer.objects.count()
        verified_customers = DimAICCustomer.objects.filter(system_user__is_active=True).count()
        pending_customers = DimAICCustomer.objects.filter(system_user__is_active=False).count()
        verification_rate = (verified_customers / total_customers * 100) if total_customers > 0 else 0

        # Prepare statistics data
        statistics_data = {
            'total_customers': total_customers,
            'verified_customers': verified_customers,
            'pending_customers': pending_customers,
            'verification_rate': round(verification_rate, 2)
        }

        # Get recent customers
        recent_customers_queryset = DimAICCustomer.objects.select_related('system_user').order_by('-id')[:5]

        # Serialize the data
        # statistics_serializer = CustomerStatisticsSerializer(statistics_data)
        # recent_customers_serializer = RecentCustomerSerializer(recent_customers_queryset, many=True)

        dashboard_data = {
            'statistics': statistics_data,
            'recent_customers': recent_customers_queryset
        }
        dashboard_serializer = AdminDashboardSerializer(dashboard_data)

        return create_api_response(
            status_code=status.HTTP_200_OK,
            message="Dashboard data retrieved successfully",
            data=dashboard_serializer.data
        )
