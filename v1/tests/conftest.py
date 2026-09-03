"""
Shared fixtures.

``two_firms`` is the backbone of the tenancy tests: two firms with their own
owners, accountants and clients, so any endpoint can be asked whether it lets
one firm see the other's data.
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from v1.configuration.models import ConfigVersion, DocumentSource, DocumentType, ExtractionField
from v1.ledger.models import LedgerAccount
from v1.tenancy.models import Client, ClientAssignment, Firm, FirmMembership

User = get_user_model()

PASSWORD = "correct-horse-battery-staple"


def make_user(email: str, *, active: bool = True):
    user = User.objects.create_user(
        username=email, email=email, password=PASSWORD, is_active=active
    )
    from v1.identity.models import UserProfile

    UserProfile.objects.create(user=user, is_verified=active)
    return user


def api_client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}"
    )
    return client


@pytest.fixture(autouse=True)
def clear_throttle_history():
    """
    DRF keeps throttle counters in the default cache, which outlives a test.
    Without this, whichever test happens to run fourth against a credential
    endpoint fails with a 429. Throttling itself is covered explicitly in
    test_auth.py.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def two_firms(db):
    """
    Two complete firms, each with an owner, an accountant and two clients.
    The accountant is assigned to only the first client of their firm.
    """
    built = {}

    for tag in ("a", "b"):
        firm = Firm.objects.create(name=f"Firm {tag.upper()}")

        owner = make_user(f"owner-{tag}@example.com")
        owner_membership = FirmMembership.objects.create(
            user=owner, firm=firm, role=FirmMembership.Role.OWNER
        )

        accountant = make_user(f"accountant-{tag}@example.com")
        accountant_membership = FirmMembership.objects.create(
            user=accountant, firm=firm, role=FirmMembership.Role.ACCOUNTANT
        )

        clients = [
            Client.objects.create(firm=firm, name=f"Client {tag}{i}", external_ref=f"REF{i}")
            for i in (1, 2)
        ]
        ClientAssignment.objects.create(
            client=clients[0], membership=accountant_membership
        )

        built[tag] = {
            "firm": firm,
            "owner": owner,
            "owner_membership": owner_membership,
            "accountant": accountant,
            "accountant_membership": accountant_membership,
            "clients": clients,
        }

    return built


@pytest.fixture
def reviewer(db, two_firms):
    """A reviewer at firm A."""
    user = make_user("reviewer@example.com")
    FirmMembership.objects.create(
        user=user, firm=two_firms["a"]["firm"], role=FirmMembership.Role.REVIEWER
    )
    return user


@pytest.fixture
def reviewer_b(db, two_firms):
    """A reviewer at firm B, for checking the two do not see each other."""
    user = make_user("reviewer-b@example.com")
    FirmMembership.objects.create(
        user=user, firm=two_firms["b"]["firm"], role=FirmMembership.Role.REVIEWER
    )
    return user


@pytest.fixture
def configured_client(db, two_firms):
    """
    Firm A's first client, with a chart of accounts, one transactional source
    and one field-configured source carrying two fields.
    """
    client = two_firms["a"]["clients"][0]

    cash = LedgerAccount.objects.create(
        client=client, account_number="1000", name="Operating Cash"
    )
    wages = LedgerAccount.objects.create(
        client=client, account_number="6000", name="Wages Expense"
    )

    bank = DocumentSource.objects.create(
        client=client,
        name="Operating Account",
        document_type=DocumentType.BANK_STATEMENT,
        ledger_account=cash,
        default_offset_account=cash,
    )

    payroll = DocumentSource.objects.create(
        client=client, name="ADP Payroll", document_type=DocumentType.PAYROLL
    )
    ExtractionField.objects.create(
        document_source=payroll,
        key="gross_wages",
        label="Gross Wages",
        prompt_hint="Total gross wages on the payroll summary",
        direction=ExtractionField.Direction.DEBIT,
        ledger_account=wages,
        offset_ledger_account=cash,
        position=0,
    )
    ExtractionField.objects.create(
        document_source=payroll,
        key="employer_taxes",
        label="Employer Taxes",
        direction=ExtractionField.Direction.DEBIT,
        ledger_account=wages,
        offset_ledger_account=cash,
        position=1,
    )

    return {
        "client": client,
        "cash": cash,
        "wages": wages,
        "bank_source": bank,
        "payroll_source": payroll,
    }


@pytest.fixture
def config_version(db, configured_client):
    return ConfigVersion.objects.create(
        client=configured_client["client"], version=1, payload={"document_sources": []}
    )
