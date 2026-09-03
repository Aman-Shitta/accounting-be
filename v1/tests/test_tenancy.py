"""
Tenant isolation.

The regression net for the 177 hand-rolled ``hasattr(user, 'customer_profile')``
checks that used to decide scoping in every view. Everything now funnels
through ``accessible_clients``, so these tests pin its behaviour.
"""

import pytest
from django.db import IntegrityError, transaction

from v1.common.querysets import accessible_clients
from v1.configuration.models import DocumentSource, DocumentType
from v1.ledger.models import LedgerAccount
from v1.tenancy.models import Client, Firm, FirmMembership
from v1.tests.conftest import make_user

pytestmark = pytest.mark.django_db


def test_an_owner_sees_every_client_of_their_own_firm_and_no_others(two_firms):
    visible = accessible_clients(two_firms["a"]["owner"])

    assert set(visible) == set(two_firms["a"]["clients"])
    assert not visible.filter(firm=two_firms["b"]["firm"]).exists()


def test_an_accountant_sees_only_assigned_clients(two_firms):
    visible = accessible_clients(two_firms["a"]["accountant"])

    assert list(visible) == [two_firms["a"]["clients"][0]]
    assert two_firms["a"]["clients"][1] not in visible


def test_a_reviewer_sees_across_firms(two_firms, reviewer):
    """
    Deliberate: reviewers are platform-level today. Flagged in
    documentation/02-decisions.md as needing a product decision.
    """
    visible = accessible_clients(reviewer)

    assert set(visible) == set(two_firms["a"]["clients"] + two_firms["b"]["clients"])


def test_a_user_with_no_membership_sees_nothing(db):
    assert not accessible_clients(make_user("nobody@example.com")).exists()


def test_an_anonymous_user_sees_nothing(db):
    from django.contrib.auth.models import AnonymousUser

    assert not accessible_clients(AnonymousUser()).exists()


def test_a_deactivated_membership_grants_nothing(two_firms):
    membership = two_firms["a"]["owner_membership"]
    membership.is_active = False
    membership.save()

    assert not accessible_clients(two_firms["a"]["owner"]).exists()


def test_a_soft_deleted_client_drops_out_of_scope(two_firms):
    client = two_firms["a"]["clients"][0]
    client.soft_delete()

    assert client not in accessible_clients(two_firms["a"]["owner"])


def test_scoped_managers_reach_client_through_their_own_path(two_firms, configured_client):
    """Every tenant-scoped model resolves to the same visible client set."""
    owner_a = two_firms["a"]["owner"]
    owner_b = two_firms["b"]["owner"]

    assert LedgerAccount.objects.for_user(owner_a).count() == 2
    assert LedgerAccount.objects.for_user(owner_b).count() == 0

    assert DocumentSource.objects.for_user(owner_a).count() == 2
    assert DocumentSource.objects.for_user(owner_b).count() == 0


def test_an_accountant_cannot_reach_an_unassigned_clients_data(two_firms):
    """Firm-level access is not enough; the assignment is what grants it."""
    unassigned = two_firms["a"]["clients"][1]
    LedgerAccount.objects.create(client=unassigned, account_number="1000", name="Cash")

    accountant = two_firms["a"]["accountant"]
    assert LedgerAccount.objects.for_user(accountant).count() == 0


# ---- constraints that make isolation structural, not just filtered ----------


def test_two_firms_may_reuse_the_same_client_reference(two_firms):
    """The old schema made client_id globally unique, which blocked this."""
    holders = Client.objects.filter(external_ref="REF1")

    assert holders.count() == 2
    assert {c.firm for c in holders} == {two_firms["a"]["firm"], two_firms["b"]["firm"]}


def test_one_firm_cannot_reuse_a_reference_twice(two_firms):
    with pytest.raises(IntegrityError), transaction.atomic():
        Client.objects.create(
            firm=two_firms["a"]["firm"], name="Duplicate", external_ref="REF1"
        )


def test_two_clients_may_name_a_source_the_same(two_firms, configured_client):
    """The old schema made input file names globally unique."""
    other = two_firms["b"]["clients"][0]
    DocumentSource.objects.create(
        client=other, name="Operating Account", document_type=DocumentType.BANK_STATEMENT
    )
    assert DocumentSource.objects.filter(name="Operating Account").count() == 2


def test_one_client_cannot_name_two_sources_the_same(configured_client):
    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentSource.objects.create(
            client=configured_client["client"],
            name="Operating Account",
            document_type=DocumentType.CREDIT_CARD,
        )


def test_only_reviewers_may_have_no_firm(db):
    user = make_user("orphan@example.com")

    with pytest.raises(IntegrityError), transaction.atomic():
        FirmMembership.objects.create(
            user=user, firm=None, role=FirmMembership.Role.ACCOUNTANT
        )


def test_reviewer_round_robin_cycles(db):
    first = make_user("rev1@example.com")
    second = make_user("rev2@example.com")
    for user in (first, second):
        FirmMembership.objects.create(
            user=user, firm=None, role=FirmMembership.Role.REVIEWER
        )

    picked = [FirmMembership.next_reviewer().user for _ in range(4)]

    assert picked == [first, second, first, second]


def test_round_robin_returns_none_when_there_are_no_reviewers(db):
    assert FirmMembership.next_reviewer() is None


def test_a_firm_gets_a_unique_public_id(db):
    ids = {Firm.objects.create(name=f"Firm {i}").public_id for i in range(5)}
    assert len(ids) == 5
