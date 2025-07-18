from rest_framework.permissions import BasePermission

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
