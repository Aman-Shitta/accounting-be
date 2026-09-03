"""Firm profile, members, clients, contacts, reference documents, assignments."""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from v1.common.pagination import paginate
from v1.common.permissions import IsFirmMember, IsFirmOwner
from v1.common.querysets import firm_for
from v1.common.views import BaseAPIView, ClientScopedView, DetailMixin, ListCreateMixin
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

# --------------------------------------------------------------------- firm


class FirmView(BaseAPIView):
    """The caller's own firm."""

    permission_classes = [IsAuthenticated, IsFirmMember]

    def get(self, request):
        firm = firm_for(request.user)
        firm.client_count = firm.clients.filter(is_deleted=False).count()
        return Response(FirmSerializer(firm).data)

    def patch(self, request):
        if not IsFirmOwner().has_permission(request, self):
            raise PermissionDenied("Only a firm owner can change firm details.")

        firm = firm_for(request.user)
        serializer = FirmSerializer(firm, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class FirmMemberListView(BaseAPIView):
    """The roster. Invites are issued through /auth/invite/."""

    permission_classes = [IsAuthenticated, IsFirmMember]

    def get(self, request):
        members = (
            FirmMembership.objects.filter(firm=firm_for(request.user))
            .select_related("user", "firm", "user__profile")
            .order_by("role", "user__email")
        )
        page, meta = paginate(members, request)
        return Response({**meta, "results": MembershipSerializer(page, many=True).data})


class FirmMemberDetailView(BaseAPIView):
    permission_classes = [IsAuthenticated, IsFirmMember]

    def _membership(self, request, pk):
        return get_object_or_404(
            FirmMembership.objects.select_related("user", "firm"),
            pk=pk,
            firm=firm_for(request.user),
        )

    def get(self, request, pk):
        return Response(MembershipSerializer(self._membership(request, pk)).data)

    def delete(self, request, pk):
        """Deactivate rather than delete — memberships are referenced by history."""
        if not IsFirmOwner().has_permission(request, self):
            raise PermissionDenied("Only a firm owner can remove members.")

        membership = self._membership(request, pk)
        if membership.user_id == request.user.id:
            raise PermissionDenied("You cannot remove your own membership.")

        membership.is_active = False
        membership.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ clients


class ClientListView(ListCreateMixin, BaseAPIView):
    queryset = Client.objects.select_related("firm").prefetch_related("contacts")
    serializer_class = ClientSerializer
    search_fields = ["name", "external_ref"]
    ordering_fields = ["name", "external_ref", "created_at"]
    default_ordering = "name"

    def get_queryset(self):
        return self.queryset.for_user(self.request.user)

    def get_serializer_context(self):
        return {"request": self.request, "view": self, "firm": firm_for(self.request.user)}

    def serialize(self, instance, many=False, **kwargs):
        return ClientSerializer(
            instance, many=many, context=self.get_serializer_context(), **kwargs
        ).data

    def perform_create(self, serializer):
        if not IsFirmMember().has_permission(self.request, self):
            raise PermissionDenied("Only firm members can onboard clients.")
        return serializer.save(firm=firm_for(self.request.user))


class ClientDetailView(DetailMixin, BaseAPIView):
    queryset = Client.objects.select_related("firm").prefetch_related("contacts")
    serializer_class = ClientSerializer

    def get_queryset(self):
        return self.queryset.for_user(self.request.user)

    def get_object(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get_serializer_context(self):
        return {"request": self.request, "view": self, "firm": firm_for(self.request.user)}

    def serialize(self, instance, many=False, **kwargs):
        return ClientSerializer(
            instance, many=many, context=self.get_serializer_context(), **kwargs
        ).data

    def perform_destroy(self, instance):
        """Soft delete — periods and extracted data outlive the client row."""
        instance.soft_delete()


# ---------------------------------------------------------- under a client


class ClientContactListView(ListCreateMixin, ClientScopedView):
    queryset = ClientContact.objects.all()
    serializer_class = ClientContactSerializer
    default_ordering = "name"

    def perform_create(self, serializer):
        return serializer.save(client=self.client)


class ClientContactDetailView(DetailMixin, ClientScopedView):
    queryset = ClientContact.objects.all()
    serializer_class = ClientContactSerializer


class ClientReferenceDocumentListView(ListCreateMixin, ClientScopedView):
    """Chart of accounts, vendor list and GL history uploads."""

    queryset = ClientReferenceDocument.objects.all()
    serializer_class = ClientReferenceDocumentSerializer
    default_ordering = "-created_at"

    def perform_create(self, serializer):
        return serializer.save(client=self.client, uploaded_by=self.request.user)


class ClientReferenceDocumentDetailView(DetailMixin, ClientScopedView):
    queryset = ClientReferenceDocument.objects.all()
    serializer_class = ClientReferenceDocumentSerializer


class ClientAssignmentListView(ListCreateMixin, ClientScopedView):
    """Which firm members may work on this client."""

    queryset = ClientAssignment.objects.select_related("membership__user")
    serializer_class = ClientAssignmentSerializer

    def get_serializer_context(self):
        return {"request": self.request, "view": self, "client": self.client}

    def serialize(self, instance, many=False, **kwargs):
        return ClientAssignmentSerializer(
            instance, many=many, context=self.get_serializer_context(), **kwargs
        ).data

    def perform_create(self, serializer):
        if not IsFirmOwner().has_permission(self.request, self):
            raise PermissionDenied("Only a firm owner can assign staff to clients.")
        return serializer.save(client=self.client, assigned_by=self.request.user)


class ClientAssignmentDetailView(DetailMixin, ClientScopedView):
    queryset = ClientAssignment.objects.select_related("membership__user")
    serializer_class = ClientAssignmentSerializer
