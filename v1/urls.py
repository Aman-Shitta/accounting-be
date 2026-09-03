"""
The /api/v1/ surface.

Nesting reflects ownership: configuration hangs off a client, extracted data
hangs off a period document. Every list is scoped to the caller's visible
clients by the ViewSet base, not by each view.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from v1.configuration.views import (
    ConfigVersionViewSet,
    DocumentSourceViewSet,
    JournalTemplateViewSet,
)
from v1.dashboard.views import DashboardView
from v1.ledger.views import LedgerAccountViewSet
from v1.periods.views import (
    AccountingPeriodViewSet,
    PeriodCheckDetailViewSet,
    PeriodDocumentViewSet,
    PeriodFieldValueViewSet,
    PeriodTransactionViewSet,
)
from v1.tenancy.views import (
    ClientAssignmentViewSet,
    ClientContactViewSet,
    ClientReferenceDocumentViewSet,
    ClientViewSet,
    FirmMemberViewSet,
    FirmView,
)

# Top level
root = DefaultRouter()
root.register("clients", ClientViewSet, basename="client")

# Firm members
firm = DefaultRouter()
firm.register("members", FirmMemberViewSet, basename="firm-member")

# Everything owned by one client
client_scoped = DefaultRouter()
client_scoped.register("contacts", ClientContactViewSet, basename="client-contact")
client_scoped.register(
    "reference-documents", ClientReferenceDocumentViewSet, basename="client-reference-document"
)
client_scoped.register("assignments", ClientAssignmentViewSet, basename="client-assignment")
client_scoped.register("ledger-accounts", LedgerAccountViewSet, basename="ledger-account")
client_scoped.register("document-sources", DocumentSourceViewSet, basename="document-source")
client_scoped.register("journal-templates", JournalTemplateViewSet, basename="journal-template")
client_scoped.register("config", ConfigVersionViewSet, basename="config-version")
client_scoped.register("periods", AccountingPeriodViewSet, basename="accounting-period")

# Documents within a period
period_scoped = DefaultRouter()
period_scoped.register("documents", PeriodDocumentViewSet, basename="period-document")

# Rows extracted from one document
document_scoped = DefaultRouter()
document_scoped.register("transactions", PeriodTransactionViewSet, basename="period-transaction")
document_scoped.register("check-details", PeriodCheckDetailViewSet, basename="period-check-detail")
document_scoped.register("field-values", PeriodFieldValueViewSet, basename="period-field-value")

urlpatterns = [
    path("auth/", include(("v1.identity.urls", "identity"), namespace="auth")),
    path("firm/", FirmView.as_view(), name="firm"),
    path("firm/", include(firm.urls)),
    path("", include(root.urls)),
    path("clients/<int:client_id>/", include(client_scoped.urls)),
    path("periods/<int:period_id>/", include(period_scoped.urls)),
    path("documents/<int:document_id>/", include(document_scoped.urls)),
    path("review/", include(("v1.review.urls", "review"), namespace="review")),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
]
