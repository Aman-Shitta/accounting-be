"""
Dashboard aggregates.

Written as ORM aggregates rather than raw SQL. The previous implementation was
hand-written SQL that also used MySQL's ``ELT()``, which does not exist in
Postgres — and it selected by customer id without going through any shared
scoping, so it was one more place tenancy could be got wrong.
"""

from django.db.models import Count
from rest_framework.response import Response

from v1.common.querysets import accessible_clients
from v1.common.views import BaseAPIView
from v1.configuration.models import DocumentSource, JournalTemplate
from v1.ledger.models import LedgerAccount
from v1.periods.models import AccountingPeriod, PeriodDocument
from v1.tenancy.models import FirmMembership

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class DashboardView(BaseAPIView):
    """Counts and recent activity across everything the caller can reach."""

    def get(self, request):
        clients = accessible_clients(request.user)
        periods = AccountingPeriod.objects.filter(client__in=clients, is_deleted=False)
        documents = PeriodDocument.objects.filter(period__in=periods)

        return Response(
            {
                "totals": {
                    "clients": clients.count(),
                    "team_members": self._team_member_count(request.user),
                    "ledger_accounts": LedgerAccount.objects.filter(
                        client__in=clients
                    ).count(),
                    "document_sources": DocumentSource.objects.filter(
                        client__in=clients, is_active=True
                    ).count(),
                    "journal_templates": JournalTemplate.objects.filter(
                        client__in=clients
                    ).count(),
                },
                "periods_by_status": self._counts_by(periods, "status"),
                "documents_by_status": self._counts_by(documents, "status"),
                "needs_attention": {
                    "pending_upload": documents.filter(
                        status=PeriodDocument.Status.PENDING
                    ).count(),
                    "failed": documents.filter(
                        status=PeriodDocument.Status.FAILED
                    ).count(),
                    "awaiting_review": documents.filter(
                        status__in=[
                            PeriodDocument.Status.PENDING_REVIEW,
                            PeriodDocument.Status.IN_REVIEW,
                        ]
                    ).count(),
                },
                "recent_periods": self._recent_periods(periods),
            }
        )

    @staticmethod
    def _counts_by(queryset, field: str) -> dict[str, int]:
        return {
            row[field]: row["count"]
            for row in queryset.values(field).annotate(count=Count("id"))
        }

    @staticmethod
    def _team_member_count(user) -> int:
        membership = FirmMembership.objects.filter(
            user=user, is_active=True, firm__isnull=False
        ).first()
        if membership is None:
            return 0
        return FirmMembership.objects.filter(
            firm=membership.firm, is_active=True
        ).count()

    @staticmethod
    def _recent_periods(periods) -> list[dict]:
        rows = periods.select_related("client").order_by("-created_at")[:10]
        return [
            {
                "id": period.id,
                "client_id": period.client_id,
                "client_name": period.client.name,
                "month": MONTH_NAMES[period.month - 1],
                "year": period.year,
                "status": period.status,
                "created_at": period.created_at,
            }
            for period in rows
        ]
