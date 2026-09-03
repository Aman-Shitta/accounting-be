"""
Endpoint behaviour, and the cross-tenant sweep.

The sweep is the regression net for the 177 hand-rolled scoping checks the old
views carried: every client-scoped route is asked whether a member of one firm
can reach another firm's data. A leak shows up here rather than in production.
"""

import pytest

from v1.configuration.models import ExtractionField
from v1.configuration.services.publish import publish_config
from v1.periods.services.open_period import open_period
from v1.tests.conftest import api_client_for

pytestmark = pytest.mark.django_db


# ---- the envelope -----------------------------------------------------------


def test_every_response_carries_the_envelope(two_firms):
    api = api_client_for(two_firms["a"]["owner"])

    response = api.get("/api/v1/clients/")

    assert response.status_code == 200
    assert set(response.data) >= {"status", "status_code", "message", "data"}
    assert response.data["status"] == "success"


def test_errors_carry_the_envelope_too(two_firms):
    api = api_client_for(two_firms["a"]["owner"])

    response = api.get("/api/v1/clients/999999/")

    assert response.status_code == 404
    assert response.data["status"] == "error"
    assert "message" in response.data


def test_a_server_error_never_returns_a_traceback(two_firms, monkeypatch):
    """
    The old code caught everything and returned the stringified exception.
    The handler logs the traceback and tells the client nothing about it.
    """
    from v1.common import querysets

    def explode(user):
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(querysets, "accessible_clients", explode)

    api = api_client_for(two_firms["a"]["owner"])
    response = api.get("/api/v1/clients/", HTTP_ACCEPT="application/json")

    assert response.status_code == 500
    body = str(response.data)
    assert "on fire" not in body
    assert "Traceback" not in body


# ---- the cross-tenant sweep -------------------------------------------------


CLIENT_SCOPED_PATHS = [
    "",
    "contacts/",
    "reference-documents/",
    "assignments/",
    "ledger-accounts/",
    "document-sources/",
    "journal-templates/",
    "config/",
    "config/check/",
    "periods/",
    "periods/years/",
]


@pytest.mark.parametrize("suffix", CLIENT_SCOPED_PATHS)
def test_a_firm_cannot_read_another_firms_client_data(two_firms, suffix):
    other_client = two_firms["b"]["clients"][0]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.get(f"/api/v1/clients/{other_client.id}/{suffix}")

    assert response.status_code == 404, f"leak on GET .../{suffix}"


@pytest.mark.parametrize("suffix", ["contacts/", "ledger-accounts/", "document-sources/"])
def test_a_firm_cannot_write_into_another_firms_client(two_firms, suffix):
    other_client = two_firms["b"]["clients"][0]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.post(f"/api/v1/clients/{other_client.id}/{suffix}", {}, format="json")

    assert response.status_code == 404, f"leak on POST .../{suffix}"


def test_a_firm_cannot_reach_another_firms_period(two_firms, configured_client):
    period = open_period(configured_client["client"], 2026, 3)

    response = api_client_for(two_firms["b"]["owner"]).get(
        f"/api/v1/periods/{period.id}/documents/"
    )

    assert response.status_code == 404


def test_a_firm_cannot_reach_another_firms_extracted_rows(two_firms, configured_client):
    period = open_period(configured_client["client"], 2026, 3)
    document = period.documents.first()

    for suffix in ("transactions/", "check-details/", "field-values/"):
        response = api_client_for(two_firms["b"]["owner"]).get(
            f"/api/v1/documents/{document.id}/{suffix}"
        )
        assert response.status_code == 404, f"leak on {suffix}"


def test_an_accountant_cannot_reach_an_unassigned_client(two_firms):
    unassigned = two_firms["a"]["clients"][1]

    response = api_client_for(two_firms["a"]["accountant"]).get(
        f"/api/v1/clients/{unassigned.id}/ledger-accounts/"
    )

    assert response.status_code == 404


def test_a_client_list_shows_only_the_callers_own(two_firms):
    response = api_client_for(two_firms["a"]["owner"]).get("/api/v1/clients/")

    names = {row["name"] for row in response.data["data"]["results"]}
    assert names == {"Client a1", "Client a2"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/clients/",
        "/api/v1/firm/",
        "/api/v1/firm/members/",
        "/api/v1/dashboard/",
        "/api/v1/review/documents/",
    ],
)
def test_every_endpoint_needs_authentication(api, path):
    assert api.get(path).status_code == 401


# ---- clients ----------------------------------------------------------------


def test_onboarding_a_client(two_firms):
    api = api_client_for(two_firms["a"]["owner"])

    response = api.post(
        "/api/v1/clients/",
        {"name": "New Client", "external_ref": "NEW1", "state": "CA"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["data"]["firm"] == two_firms["a"]["firm"].id


def test_a_client_reference_must_be_unique_within_the_firm(two_firms):
    api = api_client_for(two_firms["a"]["owner"])

    response = api.post(
        "/api/v1/clients/", {"name": "Clash", "external_ref": "REF1"}, format="json"
    )

    assert response.status_code == 400
    assert "external_ref" in response.data["errors"]


def test_the_same_reference_is_fine_in_a_different_firm(two_firms):
    """Uniqueness is per firm, so both firms may use the same code."""
    first = api_client_for(two_firms["a"]["owner"]).post(
        "/api/v1/clients/", {"name": "Acme", "external_ref": "SHARED"}, format="json"
    )
    second = api_client_for(two_firms["b"]["owner"]).post(
        "/api/v1/clients/", {"name": "Acme too", "external_ref": "SHARED"}, format="json"
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.data["data"]["firm"] != second.data["data"]["firm"]


def test_deleting_a_client_is_a_soft_delete(two_firms):
    client = two_firms["a"]["clients"][0]
    api = api_client_for(two_firms["a"]["owner"])

    assert api.delete(f"/api/v1/clients/{client.id}/").status_code == 204

    client.refresh_from_db()
    assert client.is_deleted is True
    assert api.get(f"/api/v1/clients/{client.id}/").status_code == 404


# ---- configuration ----------------------------------------------------------


def test_fields_cannot_be_put_on_a_transactional_source(configured_client, two_firms):
    client = configured_client["client"]
    bank = configured_client["bank_source"]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.put(
        f"/api/v1/clients/{client.id}/document-sources/{bank.id}/fields/",
        [{"key": "total", "label": "Total", "direction": "debit"}],
        format="json",
    )

    assert response.status_code == 400
    assert "transaction list" in str(response.data)


def test_fields_can_be_replaced_on_a_field_configured_source(configured_client, two_firms):
    client = configured_client["client"]
    payroll = configured_client["payroll_source"]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.put(
        f"/api/v1/clients/{client.id}/document-sources/{payroll.id}/fields/",
        [
            {"key": "net_pay", "label": "Net Pay", "direction": "credit", "position": 0},
            {"key": "taxes", "label": "Taxes", "direction": "debit", "position": 1},
        ],
        format="json",
    )

    assert response.status_code == 200
    assert [f["key"] for f in response.data["data"]] == ["net_pay", "taxes"]
    assert set(payroll.fields.values_list("key", flat=True)) == {"net_pay", "taxes"}


def test_publishing_returns_a_new_version(configured_client, two_firms):
    client = configured_client["client"]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.post(f"/api/v1/clients/{client.id}/config/publish/", {}, format="json")

    assert response.status_code == 201
    assert response.data["data"]["version"] == 1
    assert len(response.data["data"]["payload"]["document_sources"]) == 2


def test_publishing_an_incomplete_configuration_is_refused(configured_client, two_firms):
    client = configured_client["client"]
    configured_client["payroll_source"].fields.all().delete()
    api = api_client_for(two_firms["a"]["owner"])

    response = api.post(f"/api/v1/clients/{client.id}/config/publish/", {}, format="json")

    assert response.status_code == 400
    assert "extraction field" in str(response.data)


def test_the_check_endpoint_reports_what_is_missing(configured_client, two_firms):
    client = configured_client["client"]
    configured_client["payroll_source"].fields.all().delete()
    api = api_client_for(two_firms["a"]["owner"])

    response = api.get(f"/api/v1/clients/{client.id}/config/check/")

    assert response.data["data"]["publishable"] is False
    assert response.data["data"]["problems"]


def test_the_version_list_omits_the_payload(configured_client, two_firms):
    client = configured_client["client"]
    publish_config(client)
    api = api_client_for(two_firms["a"]["owner"])

    response = api.get(f"/api/v1/clients/{client.id}/config/")

    row = response.data["data"]["results"][0]
    assert "payload" not in row
    assert row["source_count"] == 2


# ---- periods ----------------------------------------------------------------


def test_opening_a_period_through_the_api(configured_client, two_firms):
    client = configured_client["client"]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.post(
        f"/api/v1/clients/{client.id}/periods/", {"year": 2026, "month": 3}, format="json"
    )

    assert response.status_code == 201
    assert len(response.data["data"]["documents"]) == 2
    assert response.data["data"]["config_version_number"] == 1


def test_reopening_the_same_month_is_refused(configured_client, two_firms):
    client = configured_client["client"]
    api = api_client_for(two_firms["a"]["owner"])
    api.post(f"/api/v1/clients/{client.id}/periods/", {"year": 2026, "month": 3}, format="json")

    response = api.post(
        f"/api/v1/clients/{client.id}/periods/", {"year": 2026, "month": 3}, format="json"
    )

    assert response.status_code == 400


def test_an_invalid_month_is_rejected(configured_client, two_firms):
    client = configured_client["client"]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.post(
        f"/api/v1/clients/{client.id}/periods/", {"year": 2026, "month": 13}, format="json"
    )

    assert response.status_code == 400
    assert "month" in response.data["errors"]


def test_a_document_reports_its_frozen_configuration(configured_client, two_firms):
    period = open_period(configured_client["client"], 2026, 3)
    document = period.documents.get(source_name="ADP Payroll")

    # Change the live configuration after the period was opened.
    ExtractionField.objects.create(
        document_source=configured_client["payroll_source"],
        key="bonus",
        label="Bonus",
        direction=ExtractionField.Direction.DEBIT,
    )

    response = api_client_for(two_firms["a"]["owner"]).get(
        f"/api/v1/periods/{period.id}/documents/{document.id}/config/"
    )

    keys = [f["key"] for f in response.data["data"]["fields"]]
    assert keys == ["gross_wages", "employer_taxes"], "the period keeps its pinned config"


def test_a_reviewer_can_reach_documents_across_firms(configured_client, reviewer):
    """
    Platform-scoped by design today — flagged in
    documentation/02-decisions.md as needing a product decision.
    """
    period = open_period(configured_client["client"], 2026, 3)

    response = api_client_for(reviewer).get(f"/api/v1/periods/{period.id}/documents/")

    assert response.status_code == 200


# ---- dashboard --------------------------------------------------------------


def test_the_dashboard_counts_only_what_the_caller_can_reach(configured_client, two_firms):
    open_period(configured_client["client"], 2026, 3)

    own = api_client_for(two_firms["a"]["owner"]).get("/api/v1/dashboard/").data["data"]
    other = api_client_for(two_firms["b"]["owner"]).get("/api/v1/dashboard/").data["data"]

    assert own["totals"]["clients"] == 2
    assert own["totals"]["ledger_accounts"] == 2
    assert own["totals"]["document_sources"] == 2

    assert other["totals"]["ledger_accounts"] == 0
    assert other["totals"]["document_sources"] == 0
    assert other["recent_periods"] == []
