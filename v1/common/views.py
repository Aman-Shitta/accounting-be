"""ViewSet bases that apply tenant scoping automatically."""

from rest_framework import viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated

from v1.common.envelope import EnvelopeMixin
from v1.common.permissions import HasClientAccess, IsFirmMemberOrReviewer
from v1.common.querysets import accessible_clients


class TenantScopedViewSet(EnvelopeMixin, viewsets.ModelViewSet):
    """
    A ViewSet whose queryset is restricted to the caller's visible clients.

    Subclasses supply ``queryset``; scoping is applied here rather than in each
    ``get_queryset`` override, so a subclass cannot forget it.
    """

    permission_classes = [IsAuthenticated, IsFirmMemberOrReviewer, HasClientAccess]

    def get_queryset(self):
        return super().get_queryset().for_user(self.request.user)


class ClientNestedViewSet(TenantScopedViewSet):
    """
    A ViewSet for resources under ``/clients/{client_id}/``.

    The client is resolved once, through the caller's visible set, so a client
    belonging to another firm is reported as missing rather than forbidden —
    existence does not leak across tenants.
    """

    client_field = "client"

    @property
    def client(self):
        if not hasattr(self, "_client"):
            client = (
                accessible_clients(self.request.user)
                .filter(pk=self.kwargs["client_id"])
                .first()
            )
            if client is None:
                raise NotFound("No such client.")
            self._client = client
        return self._client

    def get_queryset(self):
        return super().get_queryset().filter(**{self.client_field: self.client})

    def perform_create(self, serializer):
        serializer.save(**{self.client_field: self.client})
