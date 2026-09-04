"""
The platform operator's surface.

Nothing here is tenant-scoped — that's the point — so the property that
matters is the opposite of every other view in the API: a firm owner must be
locked out, and a platform account must see every firm, not just its own
(which it typically has none of).
"""

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from v1.identity.models import UserProfile
from v1.periods.services.open_period import open_period
from v1.tenancy.models import Firm
from v1.tests.conftest import api_client_for, make_user

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def platform_staff(db):
    user = make_user("ops@aicounting.app")
    UserProfile.objects.filter(user=user).update(is_platform_staff=True)
    return user


# ---- access control ---------------------------------------------------


def test_a_firm_owner_cannot_reach_the_platform_surface(two_firms):
    api = api_client_for(two_firms["a"]["owner"])

    response = api.get("/api/v1/platform/overview/")

    assert response.status_code == 403


def test_a_reviewer_cannot_reach_the_platform_surface(reviewer):
    api = api_client_for(reviewer)

    response = api.get("/api/v1/platform/overview/")

    assert response.status_code == 403


def test_platform_staff_can_reach_it(platform_staff):
    api = api_client_for(platform_staff)

    response = api.get("/api/v1/platform/overview/")

    assert response.status_code == 200


def test_who_am_i_reports_platform_staff_status(platform_staff, two_firms):
    staff_response = api_client_for(platform_staff).get("/api/v1/auth/me/")
    owner_response = api_client_for(two_firms["a"]["owner"]).get("/api/v1/auth/me/")

    assert staff_response.json()["data"]["is_platform_staff"] is True
    assert owner_response.json()["data"]["is_platform_staff"] is False


# ---- the overview sees across every firm --------------------------------


def test_the_overview_counts_every_firm_not_just_ones_the_caller_belongs_to(
    platform_staff, two_firms
):
    api = api_client_for(platform_staff)

    response = api.get("/api/v1/platform/overview/")

    data = response.json()["data"]
    assert data["totals"]["firms"] == 2
    assert data["totals"]["clients"] == 4  # two clients per firm


def test_the_overview_breaks_firms_down_by_extraction_provider(platform_staff, two_firms):
    two_firms["b"]["firm"].extraction_provider = Firm.ExtractionProvider.CLAUDE
    two_firms["b"]["firm"].save(update_fields=["extraction_provider"])

    response = api_client_for(platform_staff).get("/api/v1/platform/overview/")

    breakdown = response.json()["data"]["firms_by_extraction_provider"]
    assert breakdown == {"gemini": 1, "claude": 1}


def test_a_failed_document_counts_toward_needs_attention(
    platform_staff, configured_client
):
    period = open_period(configured_client["client"], 2026, 3)
    document = period.documents.get(category_key="bank_statement")
    document.mark_failed("provider timeout")

    response = api_client_for(platform_staff).get("/api/v1/platform/overview/")

    assert response.json()["data"]["needs_attention"]["failed_documents"] == 1


# ---- the firm list and detail -------------------------------------------


def test_the_firm_list_includes_every_firm_with_its_counts(platform_staff, two_firms):
    response = api_client_for(platform_staff).get("/api/v1/platform/firms/")

    results = response.json()["data"]["results"]
    names = {row["name"] for row in results}
    assert names == {"Firm A", "Firm B"}

    firm_a = next(row for row in results if row["name"] == "Firm A")
    assert firm_a["client_count"] == 2
    assert firm_a["member_count"] == 2  # owner + accountant


def test_the_firm_list_can_be_searched_by_name_or_reference(platform_staff, two_firms):
    response = api_client_for(platform_staff).get(
        "/api/v1/platform/firms/", {"search": "Firm A"}
    )

    results = response.json()["data"]["results"]
    assert [row["name"] for row in results] == ["Firm A"]


def test_the_firm_detail_lists_its_clients(platform_staff, two_firms):
    firm = two_firms["a"]["firm"]

    response = api_client_for(platform_staff).get(f"/api/v1/platform/firms/{firm.id}/")

    data = response.json()["data"]
    assert data["name"] == "Firm A"
    assert {c["name"] for c in data["clients"]} == {"Client a1", "Client a2"}


def test_an_unknown_firm_is_a_404(platform_staff):
    response = api_client_for(platform_staff).get(
        "/api/v1/platform/firms/00000000-0000-7000-0000-000000000000/"
    )

    assert response.status_code == 404


# ---- the seeding command -------------------------------------------------


def test_create_platform_admin_creates_a_platform_only_account():
    call_command(
        "create_platform_admin", "ops@aicounting.app", "--password=correcthorse123",
        stdout=StringIO(),
    )

    user = User.objects.get(username="ops@aicounting.app")
    assert user.check_password("correcthorse123")
    assert user.profile.is_platform_staff is True
    assert user.profile.is_verified is True
    assert user.firm_memberships.count() == 0


def test_create_platform_admin_is_idempotent():
    call_command(
        "create_platform_admin", "ops@aicounting.app", "--password=first-password",
        stdout=StringIO(),
    )
    call_command(
        "create_platform_admin", "ops@aicounting.app", "--password=second-password",
        stdout=StringIO(),
    )

    assert User.objects.filter(username="ops@aicounting.app").count() == 1
    user = User.objects.get(username="ops@aicounting.app")
    assert user.check_password("second-password")
