"""
Reviewer assignment.

A document whose control totals do not balance is parked for review and handed
to a reviewer at the firm that owns it. Reviewers are firm-scoped, so this is
where that boundary has to hold — the assignment happens in a Celery task with
no request and no user, so nothing else is checking it.
"""

from decimal import Decimal

import pytest

from v1.periods.models import PeriodDocument, PeriodTransaction
from v1.periods.services.open_period import open_period
from v1.periods.tasks import _assign_reviewer, validate_control_totals_task
from v1.tenancy.models import FirmMembership
from v1.tests.conftest import make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def bank_document(configured_client):
    """A bank statement document in an open period, with two transactions."""
    client = configured_client["client"]
    client.allow_review = True
    client.save(update_fields=["allow_review"])

    period = open_period(client, 2026, 3)
    document = period.documents.get(category_key="bank_statement")

    for line, (amount, direction) in enumerate(
        [(Decimal("100.00"), "debit"), (Decimal("40.00"), "credit")], start=1
    ):
        PeriodTransaction.objects.create(
            document=document,
            page_number=1,
            line_number=line,
            description=f"Transaction {line}",
            amount=amount,
            direction=direction,
        )
    return document


def test_assignment_picks_a_reviewer_from_the_documents_own_firm(
    bank_document, reviewer, reviewer_b
):
    _assign_reviewer(bank_document, {"difference": "10.00"})

    bank_document.refresh_from_db()
    assert bank_document.assigned_reviewer.user == reviewer
    assert bank_document.assigned_reviewer.firm == bank_document.period.client.firm


def test_a_firm_with_no_reviewers_parks_the_document_unassigned(
    bank_document, reviewer_b
):
    """
    reviewer_b belongs to firm B; the document belongs to firm A. Reaching
    across would be the bug, so the document stays parked with nobody on it.
    """
    _assign_reviewer(bank_document, {"difference": "10.00"})

    bank_document.refresh_from_db()
    assert bank_document.assigned_reviewer is None
    assert bank_document.status == PeriodDocument.Status.PENDING_REVIEW


def test_a_mismatch_routes_the_document_to_review(bank_document, reviewer):
    # 0 - 100 + 40 = -60, not the 500 the statement claims.
    bank_document.control_totals = {"beginning_balance": 0, "ending_balance": 500}
    bank_document.save(update_fields=["control_totals"])

    result = validate_control_totals_task(document_id=bank_document.id)

    assert result["status"] == "pending_review"
    assert result["assigned_reviewer"] == reviewer.email
    assert result["mismatch"]["calculated_ending"] == "-60.00"

    bank_document.refresh_from_db()
    assert bank_document.status == PeriodDocument.Status.PENDING_REVIEW


def test_balanced_control_totals_skip_review(bank_document, reviewer, monkeypatch):
    enqueued = []
    monkeypatch.setattr(
        "v1.periods.tasks.enqueue_classification_task.delay",
        lambda **kwargs: enqueued.append(kwargs),
    )

    # 0 - 100 + 40 = -60, which is what the statement says.
    bank_document.control_totals = {"beginning_balance": 0, "ending_balance": -60}
    bank_document.save(update_fields=["control_totals"])

    result = validate_control_totals_task(document_id=bank_document.id)

    assert result["status"] == "validation_passed"
    assert enqueued == [{"document_id": bank_document.id}]

    bank_document.refresh_from_db()
    assert bank_document.assigned_reviewer is None


def test_a_client_without_review_enabled_never_reaches_a_reviewer(
    bank_document, reviewer, monkeypatch
):
    monkeypatch.setattr(
        "v1.periods.tasks.enqueue_classification_task.delay", lambda **kwargs: None
    )
    client = bank_document.period.client
    client.allow_review = False
    client.save(update_fields=["allow_review"])

    bank_document.control_totals = {"beginning_balance": 0, "ending_balance": 999}
    bank_document.save(update_fields=["control_totals"])

    result = validate_control_totals_task(document_id=bank_document.id)

    assert result["status"] == "skipped_validation"
    bank_document.refresh_from_db()
    assert bank_document.assigned_reviewer is None


def test_the_review_queue_shows_only_the_callers_own_firm(
    bank_document, reviewer, reviewer_b
):
    from v1.tests.conftest import api_client_for

    _assign_reviewer(bank_document, {"difference": "10.00"})

    own = api_client_for(reviewer).get("/api/v1/review/documents/")
    other = api_client_for(reviewer_b).get("/api/v1/review/documents/")

    assert own.data["data"]["count"] == 1
    assert other.data["data"]["count"] == 0


def test_round_robin_spreads_work_across_a_firms_reviewers(bank_document, two_firms):
    firm = two_firms["a"]["firm"]
    reviewers = [make_user(f"rev{i}@example.com") for i in range(3)]
    for user in reviewers:
        FirmMembership.objects.create(
            user=user, firm=firm, role=FirmMembership.Role.REVIEWER
        )

    picked = [FirmMembership.next_reviewer(firm).user for _ in range(6)]

    assert picked == reviewers + reviewers
