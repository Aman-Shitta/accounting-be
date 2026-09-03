"""Chart of accounts endpoints."""

from v1.common.views import ClientScopedView, DetailMixin, ListCreateMixin
from v1.ledger.models import LedgerAccount
from v1.ledger.serializers import LedgerAccountSerializer


class LedgerAccountListView(ListCreateMixin, ClientScopedView):
    """A client's chart of accounts."""

    queryset = LedgerAccount.objects.select_related("account_type")
    serializer_class = LedgerAccountSerializer
    search_fields = ["account_number", "name"]
    ordering_fields = ["account_number", "name"]
    default_ordering = "account_number"

    def get_serializer_context(self):
        return {"request": self.request, "view": self, "client": self.client}

    def serialize(self, instance, many=False, **kwargs):
        return LedgerAccountSerializer(
            instance, many=many, context=self.get_serializer_context(), **kwargs
        ).data

    def perform_create(self, serializer):
        return serializer.save(client=self.client)


class LedgerAccountDetailView(DetailMixin, ClientScopedView):
    queryset = LedgerAccount.objects.select_related("account_type")
    serializer_class = LedgerAccountSerializer

    def get_serializer_context(self):
        return {"request": self.request, "view": self, "client": self.client}

    def serialize(self, instance, many=False, **kwargs):
        return LedgerAccountSerializer(
            instance, many=many, context=self.get_serializer_context(), **kwargs
        ).data
