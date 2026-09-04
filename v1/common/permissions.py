"""
Role and tenancy permissions.

Roles come from ``FirmMembership``. Object access is decided by
``accessible_clients`` rather than re-derived per view — see
:mod:`v1.common.querysets`.
"""

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission

from v1.common.querysets import accessible_clients


def _roles(request) -> set[str]:
    """
    Active roles for the requesting user.

    The authentication class caches these on the request so a permission check
    costs no query.
    """
    cached = getattr(request, "_membership_roles", None)
    if cached is not None:
        return cached

    from v1.tenancy.models import FirmMembership

    user = request.user
    if not user or not user.is_authenticated:
        roles: set[str] = set()
    else:
        roles = set(
            FirmMembership.objects.filter(user=user, is_active=True).values_list(
                "role", flat=True
            )
        )

    request._membership_roles = roles
    return roles


class IsFirmOwner(BasePermission):
    """The user owns a firm."""

    message = "This action is restricted to firm owners."

    def has_permission(self, request, view):
        from v1.tenancy.models import FirmMembership

        return FirmMembership.Role.OWNER in _roles(request)


class IsFirmMember(BasePermission):
    """The user belongs to a firm in any capacity."""

    message = "You must belong to a firm to do this."

    def has_permission(self, request, view):
        from v1.tenancy.models import FirmMembership

        return bool(
            _roles(request)
            & {FirmMembership.Role.OWNER, FirmMembership.Role.ACCOUNTANT}
        )


class IsReviewer(BasePermission):
    """The user is a reviewer."""

    message = "This action is restricted to reviewers."

    def has_permission(self, request, view):
        from v1.tenancy.models import FirmMembership

        return FirmMembership.Role.REVIEWER in _roles(request)


class IsFirmMemberOrReviewer(BasePermission):
    def has_permission(self, request, view):
        return IsFirmMember().has_permission(request, view) or IsReviewer().has_permission(
            request, view
        )


class IsPlatformStaff(BasePermission):
    """
    The user operates the platform itself, not any one firm.

    Unrelated to ``FirmMembership`` — a platform account typically belongs to
    none — so this checks ``UserProfile.is_platform_staff`` directly rather
    than going through ``_roles``.
    """

    message = "This is restricted to platform staff."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return getattr(getattr(user, "profile", None), "is_platform_staff", False)


class HasClientAccess(BasePermission):
    """
    The client named in the URL is one the user can see.

    Raises ``NotFound`` rather than returning ``False``: a 403 would confirm
    that a client id exists, which is exactly what must not leak across firms.
    Views expose the id as ``client_id`` or ``client_pk`` in their URL kwargs.
    """

    def has_permission(self, request, view):
        client_id = view.kwargs.get("client_id") or view.kwargs.get("client_pk")
        if client_id is None:
            return True

        if not accessible_clients(request.user).filter(pk=client_id).exists():
            raise NotFound("No such client.")
        return True

    def has_object_permission(self, request, view, obj):
        client = getattr(obj, "client", None) or obj
        client_id = getattr(client, "pk", None)

        if client_id is None or not accessible_clients(request.user).filter(
            pk=client_id
        ).exists():
            raise NotFound("No such client.")
        return True
