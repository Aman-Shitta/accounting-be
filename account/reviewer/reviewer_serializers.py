"""
Serializers for the Reviewer workflow.

Provides serializers for:
  - Listing reviewer-assigned documents (compact)
  - Detailed document view (with line-item summary & mismatch info)
  - Review submission (approve / reject action input)
  - Review submission response
"""

from django.db.models import Q, Sum

from rest_framework import serializers

from account.models import MonthlyAccountingDocument, MonthlyDocumentBankLineItem


# ---------------------------------------------------------------------------
# Input serializer — validates the POST body for review submission
# ---------------------------------------------------------------------------

class ReviewSubmitSerializer(serializers.Serializer):
    """Validates the reviewer's approve / reject action."""

    ACTION_CHOICES = [('approve', 'Approve'), ('reject', 'Reject')]

    action = serializers.ChoiceField(
        choices=ACTION_CHOICES,
        help_text="Must be 'approve' or 'reject'.",
    )
    review_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        help_text="Optional notes from the reviewer.",
    )


# ---------------------------------------------------------------------------
# Output serializers — shape the JSON responses
# ---------------------------------------------------------------------------

class BalanceMismatchSerializer(serializers.Serializer):
    """Read-only representation of control-total mismatch details."""

    beginning_balance = serializers.CharField(read_only=True)
    sum_debits = serializers.CharField(read_only=True)
    sum_credits = serializers.CharField(read_only=True)
    calculated_ending = serializers.CharField(read_only=True)
    expected_ending = serializers.CharField(read_only=True)
    difference = serializers.CharField(read_only=True)


class ReviewerDocumentListSerializer(serializers.ModelSerializer):
    """Compact representation used when listing reviewer-assigned documents."""

    doc_type_display = serializers.CharField(
        source='get_doc_type_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    input_file_name = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    monthly_accounting_id = serializers.IntegerField(
        source='monthly_accounting.id', read_only=True)
    balance_mismatch_details = BalanceMismatchSerializer(read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyAccountingDocument
        fields = [
            'id',
            'doc_type',
            'doc_type_display',
            'status',
            'status_display',
            'input_file_name',
            'client_name',
            'monthly_accounting_id',
            'balance_mismatch_details',
            'file_url',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    # -- helpers --
    def get_input_file_name(self, obj):
        return obj.input_file_snapshot.name if obj.input_file_snapshot else None

    def get_client_name(self, obj):
        try:
            return obj.monthly_accounting.client.client_name
        except AttributeError:
            return None

    def get_file_url(self, obj):
        return obj.file_url


class LineItemSummarySerializer(serializers.Serializer):
    """Aggregated line-item totals shown on the detail view."""

    total_count = serializers.IntegerField(read_only=True)
    total_debits = serializers.CharField(read_only=True)
    total_credits = serializers.CharField(read_only=True)


class ReviewerDocumentDetailSerializer(serializers.ModelSerializer):
    """Full representation of a document assigned for review."""

    doc_type_display = serializers.CharField(
        source='get_doc_type_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    input_file_name = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    monthly_accounting_id = serializers.IntegerField(
        source='monthly_accounting.id', read_only=True)
    balance_mismatch_details = BalanceMismatchSerializer(read_only=True)
    line_item_summary = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyAccountingDocument
        fields = [
            'id',
            'doc_type',
            'doc_type_display',
            'status',
            'status_display',
            'input_file_name',
            'client_name',
            'monthly_accounting_id',
            'file_url',
            'control_item',
            'balance_mismatch_details',
            'review_notes',
            'line_item_summary',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    # -- helpers --
    def get_input_file_name(self, obj):
        return obj.input_file_snapshot.name if obj.input_file_snapshot else None

    def get_client_name(self, obj):
        try:
            return obj.monthly_accounting.client.client_name
        except AttributeError:
            return None

    def get_file_url(self, obj):
        return obj.file_url

    def get_line_item_summary(self, obj):
        """Compute aggregated debit / credit totals from related line items."""

        qs = MonthlyDocumentBankLineItem.objects.filter(document=obj)
        sums = qs.aggregate(
            total_debits=Sum('amount', filter=Q(transaction_type='debit')),
            total_credits=Sum('amount', filter=Q(transaction_type='credit')),
        )
        return LineItemSummarySerializer({
            'total_count': qs.count(),
            'total_debits': str(sums['total_debits'] or 0),
            'total_credits': str(sums['total_credits'] or 0),
        }).data


class ReviewActionResponseSerializer(serializers.Serializer):
    """Minimal response after a review action is submitted."""

    id = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
