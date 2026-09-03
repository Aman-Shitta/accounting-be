"""Period, document, transaction and field-value endpoints."""

import logging

from celery import chain
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from v1.common.envelope import EnvelopeMixin
from v1.common.permissions import IsFirmMemberOrReviewer
from v1.common.querysets import accessible_clients
from v1.common.views import ClientNestedViewSet
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
from v1.periods.services.open_period import PeriodAlreadyOpen, open_period, resolved_source
from v1.periods.tasks import process_document_task, validate_control_totals_task

logger = logging.getLogger(__name__)


class AccountingPeriodViewSet(ClientNestedViewSet):
    """A client's monthly closes."""

    queryset = (
        AccountingPeriod.objects.filter(is_deleted=False)
        .select_related("client", "config_version")
        .prefetch_related("documents")
    )
    serializer_class = AccountingPeriodSerializer

    def create(self, request, client_id=None):
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

    def perform_destroy(self, instance):
        """Soft delete, so the month can be reopened and history survives."""
        instance.soft_delete()

    @action(detail=False, methods=["get"], url_path="years")
    def years(self, request, client_id=None):
        """Years this client has periods for, for a year picker."""
        return Response(
            sorted(
                self.get_queryset().values_list("year", flat=True).distinct(),
                reverse=True,
            )
        )


class PeriodDocumentViewSet(EnvelopeMixin, viewsets.ModelViewSet):
    """
    Documents within a period.

    Nested under ``/periods/{period_id}/`` rather than a client, because the
    period is what a user is looking at once a month is open.
    """

    permission_classes = [IsAuthenticated, IsFirmMemberOrReviewer]
    serializer_class = PeriodDocumentSerializer
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "head", "options"]

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

    def get_queryset(self):
        return (
            PeriodDocument.objects.filter(period=self.period)
            .select_related("document_source", "assigned_reviewer__user")
            .annotate(transaction_count=Count("transactions"))
        )

    @action(detail=True, methods=["post"], url_path="upload")
    def upload(self, request, period_id=None, pk=None):
        """
        Attach a file and start extraction.

        Re-uploading replaces the previous extraction rather than adding to it
        — the task clears prior rows before running.
        """
        document = self.get_object()

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
            process_document_task.s(document.id),
            validate_control_totals_task.s(document_id=document.id),
        ).apply_async()

        logger.info(f"Queued extraction for document {document.id} (task {result.id})")

        return Response(
            {
                **PeriodDocumentSerializer(document).data,
                "task_id": result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["get"], url_path="config")
    def config(self, request, period_id=None, pk=None):
        """
        The frozen configuration this document was opened against — not the
        client's current configuration.
        """
        document = self.get_object()
        frozen = resolved_source(document)
        if frozen is None:
            raise NotFound("This document's source is not in the pinned configuration.")
        return Response(frozen)

    @action(detail=True, methods=["post"], url_path="verify")
    def verify(self, request, period_id=None, pk=None):
        """Mark a document reviewed and correct."""
        document = self.get_object()
        document.status = PeriodDocument.Status.VERIFIED
        document.save(update_fields=["status", "updated_at"])
        return Response(PeriodDocumentSerializer(document).data)


class DocumentScopedViewSet(EnvelopeMixin, viewsets.ModelViewSet):
    """Base for rows that belong to one period document."""

    permission_classes = [IsAuthenticated, IsFirmMemberOrReviewer]

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
        return super().get_queryset().filter(document=self.document)

    def perform_create(self, serializer):
        serializer.save(document=self.document)


class PeriodTransactionViewSet(DocumentScopedViewSet):
    """Extracted transactions, and the corrections a reviewer makes to them."""

    queryset = PeriodTransaction.objects.select_related(
        "ledger_account", "offset_ledger_account"
    )
    serializer_class = PeriodTransactionSerializer

    def perform_create(self, serializer):
        """A reviewer adding a transaction the extractor missed."""
        last = (
            PeriodTransaction.objects.filter(document=self.document)
            .order_by("-line_number")
            .first()
        )
        serializer.save(
            document=self.document,
            line_number=(last.line_number + 1) if last else 1,
        )


class PeriodCheckDetailViewSet(DocumentScopedViewSet):
    queryset = PeriodCheckDetail.objects.select_related("transaction")
    serializer_class = PeriodCheckDetailSerializer


class PeriodFieldValueViewSet(DocumentScopedViewSet):
    """
    Extracted field values.

    Rows are created by the pipeline — one per configured field, whether or not
    a value was found — so this is read and correct, not create and delete.
    """

    queryset = PeriodFieldValue.objects.select_related(
        "ledger_account", "offset_ledger_account"
    )
    serializer_class = PeriodFieldValueSerializer
    http_method_names = ["get", "patch", "head", "options"]
