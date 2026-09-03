"""
Role and tenancy permissions.

Roles come from ``FirmMembership``. Object access is decided by
``accessible_clients`` rather than re-derived per view — see
:mod:`v1.common.querysets`.
"""

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


class HasClientAccess(BasePermission):
    """
    The client named in the URL is one the user can see.

    Views expose the client id as ``client_id`` or ``client_pk`` in the URL
    kwargs. A client outside the user's scope is reported as missing, not
    forbidden, so existence does not leak across firms.
    """

    message = "No such client."

    def has_permission(self, request, view):
        client_id = view.kwargs.get("client_id") or view.kwargs.get("client_pk")
        if client_id is None:
            return True
        return accessible_clients(request.user).filter(pk=client_id).exists()

    def has_object_permission(self, request, view, obj):
        client = getattr(obj, "client", None) or obj
        client_id = getattr(client, "pk", None)
        if client_id is None:
            return False
        return accessible_clients(request.user).filter(pk=client_id).exists()
