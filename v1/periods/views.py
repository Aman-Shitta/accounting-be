"""Period, document, transaction and field-value endpoints."""

import logging

from celery import chain
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from v1.common.querysets import accessible_clients
from v1.common.views import BaseAPIView, ClientScopedView, DetailMixin, ListCreateMixin
from v1.periods.models import (
    AccountingPeriod,
    PeriodCheckDetail,
    PeriodDocument,
    PeriodFieldValue,
    PeriodTransaction,
)
from v1.periods.serializers import (
    AccountingPeriodSerializer,
    DocumentUploadSerializer,
    OpenPeriodSerializer,
    PeriodCheckDetailSerializer,
    PeriodDocumentSerializer,
    PeriodFieldValueSerializer,
    PeriodTransactionSerializer,
)
from v1.periods.services.journal_export import build_journal_lines, render_csv, render_iif
from v1.periods.services.open_period import PeriodAlreadyOpen, open_period, resolved_source
from v1.periods.tasks import process_document_task, validate_control_totals_task

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ periods


class PeriodListView(ListCreateMixin, ClientScopedView):
    """A client's monthly closes."""

    queryset = (
        AccountingPeriod.objects.filter(is_deleted=False)
        .select_related("client", "config_version")
        .prefetch_related("documents")
    )
    serializer_class = AccountingPeriodSerializer
    ordering_fields = ["year", "month", "created_at"]
    default_ordering = "-year"

    def post(self, request, client_id):
        """Open a month, pinning the client's current configuration."""
        serializer = OpenPeriodSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            period = open_period(
                self.client,
                year=serializer.validated_data["year"],
                month=serializer.validated_data["month"],
                opened_by=request.user,
            )
        except PeriodAlreadyOpen as e:
            raise ValidationError({"period": e.messages}) from e
        except DjangoValidationError as e:
            raise ValidationError({"configuration": e.messages}) from e

        return Response(
            AccountingPeriodSerializer(period).data, status=status.HTTP_201_CREATED
        )


class PeriodDetailView(DetailMixin, ClientScopedView):
    queryset = (
        AccountingPeriod.objects.filter(is_deleted=False)
        .select_related("client", "config_version")
        .prefetch_related("documents")
    )
    serializer_class = AccountingPeriodSerializer

    def perform_destroy(self, instance):
        """Soft delete, so the month can be reopened and history survives."""
        instance.soft_delete()


class PeriodYearsView(ClientScopedView):
    """Years this client has periods for, for a year picker."""

    queryset = AccountingPeriod.objects.filter(is_deleted=False)
    serializer_class = AccountingPeriodSerializer

    def get(self, request, client_id):
        years = self.get_queryset().values_list("year", flat=True).distinct()
        return Response(sorted(years, reverse=True))


# ---------------------------------------------------------------- documents


class PeriodScopedView(BaseAPIView):
    """
    A view under ``/periods/{period_id}/``.

    Nested on the period rather than the client, because a period is what a
    user is looking at once a month is open.
    """

    @property
    def period(self):
        if not hasattr(self, "_period"):
            period = (
                AccountingPeriod.objects.filter(
                    pk=self.kwargs["period_id"],
                    is_deleted=False,
                    client__in=accessible_clients(self.request.user),
                )
                .select_related("client", "config_version")
                .first()
            )
            if period is None:
                raise NotFound("No such accounting period.")
            self._period = period
        return self._period

    def documents(self):
        return (
            PeriodDocument.objects.filter(period=self.period)
            .select_related("document_source", "assigned_reviewer__user")
            .annotate(transaction_count=Count("transactions"))
        )


class PeriodDocumentListView(PeriodScopedView):
    def get(self, request, period_id):
        documents = self.documents().order_by("source_name")
        return Response(
            {
                "count": documents.count(),
                "next": None,
                "previous": None,
                "results": PeriodDocumentSerializer(documents, many=True).data,
            }
        )


class PeriodDocumentDetailView(PeriodScopedView):
    def get(self, request, period_id, pk):
        document = get_object_or_404(self.documents(), pk=pk)
        return Response(PeriodDocumentSerializer(document).data)

    def patch(self, request, period_id, pk):
        document = get_object_or_404(self.documents(), pk=pk)
        serializer = PeriodDocumentSerializer(document, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PeriodDocumentUploadView(PeriodScopedView):
    """
    Attach a file and start extraction.

    Re-uploading replaces the previous extraction rather than adding to it —
    the task clears prior rows before running.
    """

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, period_id, pk):
        document = get_object_or_404(self.documents(), pk=pk)

        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        document.file = serializer.validated_data["file"]
        document.status = PeriodDocument.Status.UPLOADED
        document.uploaded_by = request.user
        document.failure_reason = ""
        document.save(
            update_fields=["file", "status", "uploaded_by", "failure_reason", "updated_at"]
        )

        result = chain(
            process_document_task.s(str(document.id)),
            validate_control_totals_task.s(document_id=str(document.id)),
        ).apply_async()

        logger.info(f"Queued extraction for document {document.id} (task {result.id})")

        return Response(
            {**PeriodDocumentSerializer(document).data, "task_id": result.id},
            status=status.HTTP_202_ACCEPTED,
        )


class PeriodDocumentConfigView(PeriodScopedView):
    """
    The frozen configuration this document was opened against — not the
    client's current configuration.
    """

    def get(self, request, period_id, pk):
        document = get_object_or_404(self.documents(), pk=pk)
        frozen = resolved_source(document)
        if frozen is None:
            raise NotFound("This document's source is not in the pinned configuration.")
        return Response(frozen)


class PeriodDocumentVerifyView(PeriodScopedView):
    def post(self, request, period_id, pk):
        document = get_object_or_404(self.documents(), pk=pk)
        document.status = PeriodDocument.Status.VERIFIED
        document.save(update_fields=["status", "updated_at"])
        return Response(PeriodDocumentSerializer(document).data)


# ------------------------------------------------------------ journal export


class PeriodJournalExportCheckView(PeriodScopedView):
    """What would export, and what would be left out, without downloading anything."""

    def get(self, request, period_id):
        lines, problems = build_journal_lines(self.period)
        entry_count = len({line.entry for line in lines})
        return Response({"entry_count": entry_count, "problems": problems})


class PeriodJournalExportView(PeriodScopedView):
    """
    This period's classified transactions and extracted field values as a
    journal, in a format an outside system can take: a plain CSV, or
    QuickBooks Desktop's IIF import.
    """

    def get(self, request, period_id):
        # Not named "format": DRF's own content negotiation reserves that query
        # parameter for picking a renderer, and 404s when it doesn't recognize
        # the value — a client asking for our export format collides with it.
        fmt = request.query_params.get("type", "csv")
        renderers = {"csv": (render_csv, "text/csv", "csv"), "iif": (render_iif, "application/x-iif", "iif")}

        if fmt not in renderers:
            raise ValidationError(
                {"type": [f"Unsupported export format {fmt!r}. Use 'csv' or 'iif'."]}
            )
        render, content_type, extension = renderers[fmt]

        lines, _problems = build_journal_lines(self.period)
        content = render(lines)

        client_slug = self.period.client.external_ref or self.period.client.name
        filename = f"{client_slug}-{self.period.year}-{self.period.month:02d}-journal.{extension}"

        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# ----------------------------------------------------------- extracted rows


class DocumentScopedView(ListCreateMixin, BaseAPIView):
    """Rows belonging to one period document."""

    queryset = None
    serializer_class = None

    @property
    def document(self):
        if not hasattr(self, "_document"):
            document = (
                PeriodDocument.objects.filter(
                    pk=self.kwargs["document_id"],
                    period__client__in=accessible_clients(self.request.user),
                )
                .select_related("period__client", "document_source")
                .first()
            )
            if document is None:
                raise NotFound("No such document.")
            self._document = document
        return self._document

    def get_queryset(self):
        return self.queryset.filter(document=self.document)

    def get_object(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get_serializer_context(self):
        return {"request": self.request, "view": self}

    def serialize(self, instance, many=False, **kwargs):
        return self.serializer_class(
            instance, many=many, context=self.get_serializer_context(), **kwargs
        ).data

    def perform_create(self, serializer):
        return serializer.save(document=self.document)


class DocumentRowDetailView(DetailMixin, DocumentScopedView):
    """Detail for one extracted row. Inherits the document scoping above."""


class TransactionListView(DocumentScopedView):
    """Extracted transactions, and the corrections a reviewer makes to them."""

    queryset = PeriodTransaction.objects.select_related(
        "ledger_account", "offset_ledger_account"
    )
    serializer_class = PeriodTransactionSerializer
    search_fields = ["description", "check_number"]
    ordering_fields = ["page_number", "line_number", "amount", "transaction_date"]
    default_ordering = "page_number"

    def perform_create(self, serializer):
        """A reviewer adding a transaction the extractor missed."""
        last = (
            PeriodTransaction.objects.filter(document=self.document)
            .order_by("-line_number")
            .first()
        )
        return serializer.save(
            document=self.document, line_number=(last.line_number + 1) if last else 1
        )


class TransactionDetailView(DocumentRowDetailView):
    queryset = PeriodTransaction.objects.select_related(
        "ledger_account", "offset_ledger_account"
    )
    serializer_class = PeriodTransactionSerializer


class CheckDetailListView(DocumentScopedView):
    queryset = PeriodCheckDetail.objects.select_related("transaction")
    serializer_class = PeriodCheckDetailSerializer
    default_ordering = "page_number"


class CheckDetailDetailView(DocumentRowDetailView):
    queryset = PeriodCheckDetail.objects.select_related("transaction")
    serializer_class = PeriodCheckDetailSerializer


class FieldValueListView(DocumentScopedView):
    """
    Extracted field values.

    Rows are created by the pipeline — one per configured field, whether or not
    a value was found — so this is read and correct, not create and delete.
    """

    queryset = PeriodFieldValue.objects.select_related(
        "ledger_account", "offset_ledger_account"
    )
    serializer_class = PeriodFieldValueSerializer
    default_ordering = "field_key"

    def post(self, request, **kwargs):
        raise NotFound()


class FieldValueDetailView(DocumentRowDetailView):
    queryset = PeriodFieldValue.objects.select_related(
        "ledger_account", "offset_ledger_account"
    )
    serializer_class = PeriodFieldValueSerializer

    def delete(self, request, **kwargs):
        raise NotFound()
