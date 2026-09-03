"""Firm profile, clients, contacts, reference documents and assignments."""

from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from v1.common.envelope import EnvelopeMixin
from v1.common.permissions import IsFirmMember, IsFirmMemberOrReviewer, IsFirmOwner
from v1.common.querysets import firm_for
from v1.common.views import ClientNestedViewSet, TenantScopedViewSet
from v1.identity.serializers import MembershipSerializer
from v1.tenancy.models import (
    Client,
    ClientAssignment,
    ClientContact,
    ClientReferenceDocument,
    FirmMembership,
)
from v1.tenancy.serializers import (
    ClientAssignmentSerializer,
    ClientContactSerializer,
    ClientReferenceDocumentSerializer,
    ClientSerializer,
    FirmSerializer,
)


class FirmView(EnvelopeMixin, GenericAPIView):
    """The caller's own firm."""

    permission_classes = [IsAuthenticated, IsFirmMember]
    serializer_class = FirmSerializer

    def get(self, request):
        firm = firm_for(request.user)
        firm.client_count = firm.clients.filter(is_deleted=False).count()
        return Response(self.get_serializer(firm).data)

    def patch(self, request):
        firm = firm_for(request.user)
        if not IsFirmOwner().has_permission(request, self):
            raise PermissionDenied("Only a firm owner can change firm details.")

        serializer = self.get_serializer(firm, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class FirmMemberViewSet(EnvelopeMixin, viewsets.ReadOnlyModelViewSet):
    """
    The people in the caller's firm.

    Invites are issued through ``/auth/invite/``; this is the roster.
    """

    permission_classes = [IsAuthenticated, IsFirmMember]
    serializer_class = MembershipSerializer

    def get_queryset(self):
        return (
            FirmMembership.objects.filter(firm=firm_for(self.request.user))
            .select_related("user", "firm", "user__profile")
            .order_by("role", "user__email")
        )

    def destroy(self, request, *args, **kwargs):
        """Deactivate rather than delete — memberships are referenced by history."""
        if not IsFirmOwner().has_permission(request, self):
            raise PermissionDenied("Only a firm owner can remove members.")

        membership = self.get_object()
        if membership.user_id == request.user.id:
            raise PermissionDenied("You cannot remove your own membership.")

        membership.is_active = False
        membership.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClientViewSet(TenantScopedViewSet):
    """Clients the caller can reach."""

    queryset = Client.objects.select_related("firm").prefetch_related("contacts")
    serializer_class = ClientSerializer
    search_fields = ["name", "external_ref"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            try:
                context["firm"] = firm_for(self.request.user)
            except NotFound:
                pass
        return context

    def perform_create(self, serializer):
        if not IsFirmMember().has_permission(self.request, self):
            raise PermissionDenied("Only firm members can onboard clients.")
        serializer.save(firm=firm_for(self.request.user))

    def perform_destroy(self, instance):
        """Soft delete — periods and extracted data outlive the client row."""
        instance.soft_delete()


class ClientContactViewSet(ClientNestedViewSet):
    queryset = ClientContact.objects.all()
    serializer_class = ClientContactSerializer


class ClientReferenceDocumentViewSet(ClientNestedViewSet):
    """Chart of accounts, vendor list and GL history uploads."""

    queryset = ClientReferenceDocument.objects.all()
    serializer_class = ClientReferenceDocumentSerializer

    def perform_create(self, serializer):
        serializer.save(client=self.client, uploaded_by=self.request.user)


class ClientAssignmentViewSet(ClientNestedViewSet):
    """Which firm members may work on this client."""

    queryset = ClientAssignment.objects.select_related("membership__user")
    serializer_class = ClientAssignmentSerializer
    permission_classes = [IsAuthenticated, IsFirmMemberOrReviewer]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["client"] = self.client
        return context

    def perform_create(self, serializer):
        if not IsFirmOwner().has_permission(self.request, self):
            raise PermissionDenied("Only a firm owner can assign staff to clients.")
        serializer.save(client=self.client, assigned_by=self.request.user)
