# Third-party imports
from rest_framework.permissions import BasePermission
from rest_framework.permissions import IsAuthenticated

# Local imports
from user.models import DimAICCustomer, DimAICAccountant

class IsSuperUser(BasePermission):
    """
    Custom permission to only allow superusers to access the view.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_superuser

class IsSuperUserOrReadOnly(BasePermission):
    """
    Custom permission to allow read-only access to authenticated users,
    but write access only to superusers.
    """

    def has_permission(self, request, view):
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return request.user and request.user.is_authenticated
        return request.user and request.user.is_authenticated and request.user.is_superuser



class IsCustomer(BasePermission):
    """
    Custom permission to only allow authenticated users who are associated with a customer.
    """
    
    def has_permission(self, request, view):
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check if the user has an associated User profile
        try:
            DimAICCustomer.objects.get(system_user=request.user)
            return True
        except DimAICCustomer.DoesNotExist:
            return False
        
        return False


class IsAccountant(BasePermission):
    """
    Custom permission to only allow authenticated users who are associated with a customer.
    """
    
    def has_permission(self, request, view):
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check if the user has an associated User profile
        try:
            DimAICAccountant.objects.get(system_user=request.user)
            return True
        except DimAICCustomer.DoesNotExist:
            return False
        
        return False
