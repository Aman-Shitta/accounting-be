"""
The /api/v1/ surface.

Every route is written out. No routers: the URL map is the API's index, and a
reader should be able to see the whole contract here without inferring what a
router generated.

Primary keys are UUIDv7, so detail routes match ``<uuid:pk>``.
"""

from django.urls import include, path

from v1.configuration.views import (
    ConfigCheckView,
    ConfigCurrentView,
    ConfigPublishView,
    ConfigVersionDetailView,
    ConfigVersionListView,
    DocumentCategoryDetailView,
    DocumentCategoryListView,
    DocumentSourceDetailView,
    DocumentSourceFieldsView,
    DocumentSourceListView,
    JournalTemplateDetailView,
    JournalTemplateLinesView,
    JournalTemplateListView,
)
from v1.dashboard.views import DashboardView
from v1.ledger.views import LedgerAccountDetailView, LedgerAccountListView
from v1.periods.views import (
    CheckDetailDetailView,
    CheckDetailListView,
    FieldValueDetailView,
    FieldValueListView,
    PeriodDetailView,
    PeriodDocumentConfigView,
    PeriodDocumentDetailView,
    PeriodDocumentListView,
    PeriodDocumentUploadView,
    PeriodDocumentVerifyView,
    PeriodListView,
    PeriodYearsView,
    TransactionDetailView,
    TransactionListView,
)
from v1.tenancy.views import (
    ClientAssignmentDetailView,
    ClientAssignmentListView,
    ClientContactDetailView,
    ClientContactListView,
    ClientDetailView,
    ClientListView,
    ClientReferenceDocumentDetailView,
    ClientReferenceDocumentListView,
    FirmMemberDetailView,
    FirmMemberListView,
    FirmView,
)

# Everything owned by one client.
client_patterns = [
    path("contacts/", ClientContactListView.as_view(), name="contacts"),
    path("contacts/<uuid:pk>/", ClientContactDetailView.as_view(), name="contact"),

    path(
        "reference-documents/",
        ClientReferenceDocumentListView.as_view(),
        name="reference-documents",
    ),
    path(
        "reference-documents/<uuid:pk>/",
        ClientReferenceDocumentDetailView.as_view(),
        name="reference-document",
    ),

    path("assignments/", ClientAssignmentListView.as_view(), name="assignments"),
    path(
        "assignments/<uuid:pk>/",
        ClientAssignmentDetailView.as_view(),
        name="assignment",
    ),

    path("ledger-accounts/", LedgerAccountListView.as_view(), name="ledger-accounts"),
    path(
        "ledger-accounts/<uuid:pk>/",
        LedgerAccountDetailView.as_view(),
        name="ledger-account",
    ),

    path("document-sources/", DocumentSourceListView.as_view(), name="document-sources"),
    path(
        "document-sources/<uuid:pk>/",
        DocumentSourceDetailView.as_view(),
        name="document-source",
    ),
    path(
        "document-sources/<uuid:pk>/fields/",
        DocumentSourceFieldsView.as_view(),
        name="document-source-fields",
    ),

    path(
        "journal-templates/", JournalTemplateListView.as_view(), name="journal-templates"
    ),
    path(
        "journal-templates/<uuid:pk>/",
        JournalTemplateDetailView.as_view(),
        name="journal-template",
    ),
    path(
        "journal-templates/<uuid:pk>/lines/",
        JournalTemplateLinesView.as_view(),
        name="journal-template-lines",
    ),

    # Ordered before the <uuid:pk> route so the words are not read as ids.
    path("config/publish/", ConfigPublishView.as_view(), name="config-publish"),
    path("config/current/", ConfigCurrentView.as_view(), name="config-current"),
    path("config/check/", ConfigCheckView.as_view(), name="config-check"),
    path("config/", ConfigVersionListView.as_view(), name="config-versions"),
    path("config/<uuid:pk>/", ConfigVersionDetailView.as_view(), name="config-version"),

    path("periods/years/", PeriodYearsView.as_view(), name="period-years"),
    path("periods/", PeriodListView.as_view(), name="periods"),
    path("periods/<uuid:pk>/", PeriodDetailView.as_view(), name="period"),
]

# Documents within a period.
period_patterns = [
    path("documents/", PeriodDocumentListView.as_view(), name="documents"),
    path("documents/<uuid:pk>/", PeriodDocumentDetailView.as_view(), name="document"),
    path(
        "documents/<uuid:pk>/upload/",
        PeriodDocumentUploadView.as_view(),
        name="document-upload",
    ),
    path(
        "documents/<uuid:pk>/config/",
        PeriodDocumentConfigView.as_view(),
        name="document-config",
    ),
    path(
        "documents/<uuid:pk>/verify/",
        PeriodDocumentVerifyView.as_view(),
        name="document-verify",
    ),
]

# Rows extracted from one document.
document_patterns = [
    path("transactions/", TransactionListView.as_view(), name="transactions"),
    path("transactions/<uuid:pk>/", TransactionDetailView.as_view(), name="transaction"),
    path("check-details/", CheckDetailListView.as_view(), name="check-details"),
    path("check-details/<uuid:pk>/", CheckDetailDetailView.as_view(), name="check-detail"),
    path("field-values/", FieldValueListView.as_view(), name="field-values"),
    path("field-values/<uuid:pk>/", FieldValueDetailView.as_view(), name="field-value"),
]

urlpatterns = [
    path("auth/", include(("v1.identity.urls", "identity"), namespace="auth")),

    path("firm/", FirmView.as_view(), name="firm"),
    path("firm/members/", FirmMemberListView.as_view(), name="firm-members"),
    path("firm/members/<uuid:pk>/", FirmMemberDetailView.as_view(), name="firm-member"),
    path(
        "firm/document-categories/",
        DocumentCategoryListView.as_view(),
        name="document-categories",
    ),
    path(
        "firm/document-categories/<uuid:pk>/",
        DocumentCategoryDetailView.as_view(),
        name="document-category",
    ),

    path("clients/", ClientListView.as_view(), name="clients"),
    path("clients/<uuid:pk>/", ClientDetailView.as_view(), name="client"),
    path("clients/<uuid:client_id>/", include((client_patterns, "client-scoped"))),

    path("periods/<uuid:period_id>/", include((period_patterns, "period-scoped"))),
    path("documents/<uuid:document_id>/", include((document_patterns, "document-scoped"))),

    path("review/", include(("v1.review.urls", "review"), namespace="review")),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
]
