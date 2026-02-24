from rest_framework.permissions import BasePermission
from rest_framework.permissions import IsAuthenticated

from user.models import DimAICAccountant, DimAICCustomer, DimAICReviewer


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
    Uses cached role from JWT authentication when available to avoid DB queries.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Use cached role from JWT auth (set in authenticate.py)
        cached_role = getattr(request.user, '_cached_role', None)
        if cached_role:
            return cached_role == 'customer'

        # Fallback to DB query for non-JWT auth paths (e.g., admin)
        return DimAICCustomer.objects.filter(system_user=request.user).exists()


class IsAccountant(BasePermission):
    """
    Custom permission to only allow authenticated users who are accountants.
    Uses cached role from JWT authentication when available to avoid DB queries.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        cached_role = getattr(request.user, '_cached_role', None)
        if cached_role:
            return cached_role == 'accountant'

        return DimAICAccountant.objects.filter(system_user=request.user).exists()


class IsReviewer(BasePermission):
    """
    Custom permission to only allow authenticated users who are verified reviewers.
    Uses cached role from JWT authentication when available to avoid DB queries.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        cached_role = getattr(request.user, '_cached_role', None)
        if cached_role:
            return cached_role == 'reviewer'

        # Fallback: DB query + verified check for non-JWT auth paths
        try:
            reviewer = DimAICReviewer.objects.get(system_user=request.user)
            return reviewer.verified
        except DimAICReviewer.DoesNotExist:
            return False


class IsCustomerOrAccountant(BasePermission):
    def has_permission(self, request, view):
        return (
            IsAccountant().has_permission(request, view) or
            IsCustomer().has_permission(request, view)
        )


class IsCustomerOrAccountantOrReviewer(BasePermission):
    def has_permission(self, request, view):
        return (
            IsAccountant().has_permission(request, view) or
            IsCustomer().has_permission(request, view) or
            IsReviewer().has_permission(request, view)
        )
