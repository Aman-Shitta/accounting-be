"""
The reviewer queue.

A document lands here when its control totals do not balance and the client has
``allow_review`` set. Reviewers are scoped to their firm: the round-robin that
assigns work only considers reviewers at the firm that owns the document.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from v1.common.pagination import paginate
from v1.common.permissions import IsReviewer
from v1.common.views import BaseAPIView
from v1.periods.models import PeriodDocument
from v1.periods.serializers import PeriodDocumentSerializer
from v1.tenancy.models import FirmMembership


class SubmitReviewSerializer(serializers.Serializer):
    notes = serializers.CharField(allow_blank=True, required=False, default="")
    approved = serializers.BooleanField(default=True)


class ReviewerView(BaseAPIView):
    """Base for the queue: everything here is reviewer-only."""

    permission_classes = [IsAuthenticated, IsReviewer]

    def assigned_documents(self):
        # Assignment is already firm-scoped, so filtering by the caller's own
        # reviewer memberships cannot reach another firm's documents.
        memberships = FirmMembership.objects.filter(
            user=self.request.user, role=FirmMembership.Role.REVIEWER, is_active=True
        )
        return PeriodDocument.objects.filter(
            assigned_reviewer__in=memberships
        ).select_related("period__client", "document_source")


class ReviewQueueView(ReviewerView):
    def get(self, request):
        documents = self.assigned_documents().filter(
            status__in=[
                PeriodDocument.Status.PENDING_REVIEW,
                PeriodDocument.Status.IN_REVIEW,
            ]
        ).order_by("updated_at")

        page, meta = paginate(documents, request)
        return Response(
            {**meta, "results": PeriodDocumentSerializer(page, many=True).data}
        )


class ReviewDocumentView(ReviewerView):
    def get(self, request, pk):
        document = get_object_or_404(self.assigned_documents(), pk=pk)
        return Response(PeriodDocumentSerializer(document).data)


class ReviewClaimView(ReviewerView):
    """Take a document out of the queue and start working on it."""

    def post(self, request, pk):
        document = get_object_or_404(self.assigned_documents(), pk=pk)
        document.status = PeriodDocument.Status.IN_REVIEW
        document.save(update_fields=["status", "updated_at"])
        return Response(PeriodDocumentSerializer(document).data)


class ReviewSubmitView(ReviewerView):
    """
    Finish a review.

    Approving sends the document on to classification; the pipeline skips
    control-total validation for anything already reviewed.
    """

    def post(self, request, pk):
        from v1.periods.tasks import enqueue_classification_task

        document = get_object_or_404(self.assigned_documents(), pk=pk)

        serializer = SubmitReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        approved = serializer.validated_data["approved"]
        document.review_notes = serializer.validated_data["notes"]
        document.status = (
            PeriodDocument.Status.REVIEWED if approved else PeriodDocument.Status.FAILED
        )
        document.save(update_fields=["review_notes", "status", "updated_at"])

        if approved:
            enqueue_classification_task.delay(document_id=str(document.id))

        return Response(PeriodDocumentSerializer(document).data)
