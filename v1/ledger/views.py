"""Chart of accounts endpoints."""

from v1.common.views import ClientNestedViewSet
from v1.ledger.models import LedgerAccount
from v1.ledger.serializers import LedgerAccountSerializer


class LedgerAccountViewSet(ClientNestedViewSet):
    """A client's chart of accounts."""

    queryset = LedgerAccount.objects.select_related("account_type")
    serializer_class = LedgerAccountSerializer
    search_fields = ["account_number", "name"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["client"] = self.client
        return context
