"""
Per-firm extraction provider.

Which LLM reads a firm's bank/credit-card statements used to be a hardcoded
import in ``pipeline.py`` — a code deploy to recover from a single provider's
outage. It is a firm setting now: ``Firm.extraction_provider`` picks the
backend classes at construction time.
"""

import pytest

from extractor.pipelines.datalabs import backends
from extractor.pipelines.datalabs.pipeline import ExtractorPipeline
from v1.periods.services.open_period import open_period
from v1.tenancy.models import Firm
from v1.tests.conftest import api_client_for

pytestmark = pytest.mark.django_db


# ---- resolve_backends --------------------------------------------------


def test_resolve_backends_returns_the_gemini_set_by_default():
    classes = backends.resolve_backends("gemini")
    assert classes == (
        backends.GeminiTransactionExtractor,
        backends.GeminiSummaryExtractor,
        backends.GeminiCheckImageExtractor,
    )


def test_resolve_backends_returns_the_claude_set():
    classes = backends.resolve_backends("claude")
    assert classes == (
        backends.ClaudeTransactionExtractor,
        backends.ClaudeSummaryExtractor,
        backends.ClaudeCheckImageExtractor,
    )


def test_resolve_backends_falls_back_to_gemini_for_an_unrecognized_value():
    """A bad setting should degrade, not take down extraction."""
    assert backends.resolve_backends("something-typo'd") == backends.resolve_backends(
        "gemini"
    )


# ---- the pipeline picks them up -----------------------------------------


def test_the_pipeline_uses_its_firms_configured_provider(configured_client, monkeypatch):
    client = configured_client["client"]
    client.firm.extraction_provider = Firm.ExtractionProvider.CLAUDE
    client.firm.save(update_fields=["extraction_provider"])

    period = open_period(client, 2026, 3)
    document = period.documents.get(category_key="bank_statement")

    seen_provider = {}

    def fake_resolve(provider):
        seen_provider["value"] = provider
        # Real classes call out to a provider SDK on construction; stand in
        # with something harmless that just remembers it was built.
        stub = type("Stub", (), {"__init__": lambda self, doc: None})
        return stub, stub, stub

    monkeypatch.setattr(
        "extractor.pipelines.datalabs.pipeline.resolve_backends", fake_resolve
    )

    ExtractorPipeline(document)

    assert seen_provider["value"] == Firm.ExtractionProvider.CLAUDE


def test_a_firms_default_provider_is_gemini(configured_client, monkeypatch):
    client = configured_client["client"]
    period = open_period(client, 2026, 3)
    document = period.documents.get(category_key="bank_statement")

    seen_provider = {}

    def fake_resolve(provider):
        seen_provider["value"] = provider
        stub = type("Stub", (), {"__init__": lambda self, doc: None})
        return stub, stub, stub

    monkeypatch.setattr(
        "extractor.pipelines.datalabs.pipeline.resolve_backends", fake_resolve
    )

    ExtractorPipeline(document)

    assert seen_provider["value"] == Firm.ExtractionProvider.GEMINI


# ---- the API --------------------------------------------------------------


def test_a_firm_owner_can_change_the_extraction_provider(two_firms):
    owner = two_firms["a"]["owner"]
    api = api_client_for(owner)

    response = api.patch(
        "/api/v1/firm/", {"extraction_provider": "claude"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["data"]["extraction_provider"] == "claude"
    two_firms["a"]["firm"].refresh_from_db()
    assert two_firms["a"]["firm"].extraction_provider == "claude"


def test_an_accountant_cannot_change_the_extraction_provider(two_firms):
    accountant = two_firms["a"]["accountant"]
    api = api_client_for(accountant)

    response = api.patch(
        "/api/v1/firm/", {"extraction_provider": "claude"}, format="json"
    )

    assert response.status_code == 403


def test_an_invalid_provider_is_rejected(two_firms):
    owner = two_firms["a"]["owner"]
    api = api_client_for(owner)

    response = api.patch(
        "/api/v1/firm/", {"extraction_provider": "chatgpt"}, format="json"
    )

    assert response.status_code == 400


def test_the_default_provider_is_gemini_for_a_new_firm(two_firms):
    assert two_firms["a"]["firm"].extraction_provider == Firm.ExtractionProvider.GEMINI
