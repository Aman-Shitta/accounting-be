"""
The reviewer queue.

A document lands here when its control totals do not balance. Reviewers are
platform-level today — see documentation/02-decisions.md, which flags that as
crossing firm boundaries.
"""

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from v1.common.envelope import EnvelopeMixin
from v1.common.permissions import IsReviewer
from v1.periods.models import PeriodDocument
from v1.periods.serializers import PeriodDocumentSerializer
from v1.tenancy.models import FirmMembership


class SubmitReviewSerializer(serializers.Serializer):
    notes = serializers.CharField(allow_blank=True, required=False, default="")
    approved = serializers.BooleanField(default=True)


class ReviewQueueViewSet(EnvelopeMixin, viewsets.ReadOnlyModelViewSet):
    """Documents assigned to the calling reviewer."""

    permission_classes = [IsAuthenticated, IsReviewer]
    serializer_class = PeriodDocumentSerializer

    def get_queryset(self):
        memberships = FirmMembership.objects.filter(
            user=self.request.user, role=FirmMembership.Role.REVIEWER, is_active=True
        )
        return (
            PeriodDocument.objects.filter(
                assigned_reviewer__in=memberships,
                status__in=[
                    PeriodDocument.Status.PENDING_REVIEW,
                    PeriodDocument.Status.IN_REVIEW,
                ],
            )
            .select_related("period__client", "document_source")
            .order_by("updated_at")
        )

    @action(detail=True, methods=["post"], url_path="claim")
    def claim(self, request, pk=None):
        """Take a document out of the queue and start working on it."""
        document = self.get_object()
        document.status = PeriodDocument.Status.IN_REVIEW
        document.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        """
        Finish a review.

        Approving sends the document on to classification; the pipeline skips
        control-total validation for anything already reviewed.
        """
        from v1.periods.tasks import enqueue_classification_task

        document = self.get_object()

        serializer = SubmitReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        document.review_notes = serializer.validated_data["notes"]
        document.status = (
            PeriodDocument.Status.REVIEWED
            if serializer.validated_data["approved"]
            else PeriodDocument.Status.FAILED
        )
        document.save(update_fields=["review_notes", "status", "updated_at"])

        if serializer.validated_data["approved"]:
            enqueue_classification_task.delay(document_id=document.id)

        return Response(self.get_serializer(document).data)
