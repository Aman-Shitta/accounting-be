"""
The platform operator's surface: everything, across every firm.

Nothing here goes through ``accessible_clients`` or any other tenant
scoping — that is the entire point. A firm owner cannot reach these
endpoints (``IsPlatformStaff`` has nothing to do with ``FirmMembership``),
and a platform account typically holds no membership at all.
"""

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from v1.common.envelope import EnvelopeMixin
from v1.common.pagination import paginate
from v1.common.permissions import IsPlatformStaff
from v1.periods.models import AccountingPeriod, PeriodDocument
from v1.tenancy.models import Client, Firm, FirmMembership


class PlatformView(EnvelopeMixin, APIView):
    """Authenticated, enveloped, platform-staff-only — the root of this app."""

    permission_classes = [IsAuthenticated, IsPlatformStaff]


class PlatformOverviewView(PlatformView):
    """
    Fleet-wide counts and the signals an operator actually watches for:
    documents stuck failing, periods that never got past "initiated", and
    how firms split across the extraction providers from
    ``Firm.extraction_provider`` — useful the day one provider has an outage.
    """

    def get(self, request):
        documents = PeriodDocument.objects.all()
        periods = AccountingPeriod.objects.filter(is_deleted=False)

        return Response(
            {
                "totals": {
                    "firms": Firm.objects.count(),
                    "active_firms": Firm.objects.filter(is_active=True).count(),
                    "clients": Client.objects.filter(is_deleted=False).count(),
                    "members": FirmMembership.objects.filter(is_active=True).count(),
                    "periods": periods.count(),
                    "documents": documents.count(),
                },
                "documents_by_status": self._counts_by(documents, "status"),
                "periods_by_status": self._counts_by(periods, "status"),
                "firms_by_extraction_provider": self._counts_by(
                    Firm.objects.all(), "extraction_provider"
                ),
                "needs_attention": {
                    "failed_documents": documents.filter(
                        status=PeriodDocument.Status.FAILED
                    ).count(),
                    "awaiting_review": documents.filter(
                        status__in=[
                            PeriodDocument.Status.PENDING_REVIEW,
                            PeriodDocument.Status.IN_REVIEW,
                        ]
                    ).count(),
                    "inactive_firms": Firm.objects.filter(is_active=False).count(),
                },
            }
        )

    @staticmethod
    def _counts_by(queryset, field: str) -> dict[str, int]:
        return {
            row[field]: row["count"]
            for row in queryset.values(field).annotate(count=Count("id"))
        }


class PlatformFirmListView(PlatformView):
    """Every firm, with enough per-firm health to spot trouble without a drill-down."""

    def get(self, request):
        firms = (
            Firm.objects.all()
            .annotate(
                client_count=Count("clients", filter=Q(clients__is_deleted=False), distinct=True),
                member_count=Count("memberships", filter=Q(memberships__is_active=True), distinct=True),
                failed_document_count=Count(
                    "clients__periods__documents",
                    filter=Q(
                        clients__periods__documents__status=PeriodDocument.Status.FAILED
                    ),
                    distinct=True,
                ),
            )
            .order_by("name")
        )

        search = request.query_params.get("search", "").strip()
        if search:
            firms = firms.filter(Q(name__icontains=search) | Q(public_id__icontains=search))

        page, meta = paginate(firms, request)
        return Response(
            {
                **meta,
                "results": [
                    {
                        "id": firm.id,
                        "name": firm.name,
                        "public_id": firm.public_id,
                        "extraction_provider": firm.extraction_provider,
                        "is_active": firm.is_active,
                        "client_count": firm.client_count,
                        "member_count": firm.member_count,
                        "failed_document_count": firm.failed_document_count,
                        "created_at": firm.created_at,
                    }
                    for firm in page
                ],
            }
        )


class PlatformFirmDetailView(PlatformView):
    """One firm's clients and where each stands."""

    def get(self, request, pk):
        firm = get_object_or_404(Firm, pk=pk)
        clients = firm.clients.filter(is_deleted=False).annotate(
            period_count=Count("periods", filter=Q(periods__is_deleted=False), distinct=True),
            failed_document_count=Count(
                "periods__documents",
                filter=Q(periods__documents__status=PeriodDocument.Status.FAILED),
                distinct=True,
            ),
        )

        return Response(
            {
                "id": firm.id,
                "name": firm.name,
                "public_id": firm.public_id,
                "extraction_provider": firm.extraction_provider,
                "is_active": firm.is_active,
                "created_at": firm.created_at,
                "member_count": firm.memberships.filter(is_active=True).count(),
                "clients": [
                    {
                        "id": client.id,
                        "name": client.name,
                        "external_ref": client.external_ref,
                        "period_count": client.period_count,
                        "failed_document_count": client.failed_document_count,
                    }
                    for client in clients.order_by("name")
                ],
            }
        )
