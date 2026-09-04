# From single-tenant tool to sellable product

The v1 rebuild fixed the architectural problems (tenancy, config versioning,
naming, the API surface). None of that is wasted — it's the foundation. But
"sell this to any CPA firm" surfaces a different category of gap: the system
still assumes *one kind of client* doing *one kind of close*. This is a survey
of what's in the way, ranked by how much it actually blocks a sale.

## ✅ Done: document types are configurable, not a fixed enum

Shipped in aicounting-backend@a3aa1d7 / aicounting-frontend@ed8bf05.
`DocumentCategory` (firm-scoped, or `firm=None` for a system default)
replaces the `DocumentType` enum below; a firm adds its own kind through
`POST /firm/document-categories/` — no deploy. The frontend's document-source
picker and a new "Manage document types" UI consume it live. Kept the
original writeup for context:

## The core problem (as it was): document types were a fixed enum

```python
class DocumentType(models.TextChoices):
    BANK_STATEMENT = "bank_statement", "Bank Statement"
    CREDIT_CARD = "credit_card", "Credit Card"
    CHECK_REGISTER = "check_register", "Check Register"
    PAYROLL = "payroll", "Payroll"
    SALES = "sales", "Sales"
    MISC = "misc", "Misc"
```

Every firm's clients send different documents — 1099s, expense reports, POS
exports, AP invoices, W-2s, merchant statements, loan schedules. Today, adding
a document type means a code deploy: a new enum value, a pipeline registry
entry, a frontend constant, a migration. That's fine for one firm's fixed
workflow. It is the single biggest thing standing between this and a
configurable product, because **it means every prospect who doesn't process
exactly bank statements + payroll needs an engineering change to onboard.**

The fix is smaller than it sounds, because the schema already separates the
two behaviors that matter (`is_transactional` vs field-configured) — that
distinction just needs to stop being keyed off a hardcoded string. Concretely:
a `DocumentCategory` model holding `{key, label, extraction_mode:
transactional|fields}`, with `DocumentSource` referencing it by FK instead of
a `TextChoices` value. `MISC` already exists as an escape hatch, which tells
you the enum was already straining.

(Shipped firm-scoped rather than platform-owned-only as first sketched here:
`firm=None` is a system default visible to everyone, but a firm can also add
its own — "1099-NEC" for one firm doesn't have to mean every firm sees it.
That's the more direct read of "sell to any CPA firm.")

## Everything else, ranked by how hard it blocks a sale

### Blocks selling to more than one firm's worth of documents (do first)

1. ~~**Document types are a fixed enum.**~~ Done — see above.
2. ~~**No export to what a firm actually files with.**~~ Done —
   `GET /periods/{id}/journal-export/?type=csv|iif` (aicounting-backend@99236f6,
   aicounting-frontend@b4848c6). Built directly off `PeriodTransaction` and
   `PeriodFieldValue` — each already carries a resolved account and its
   offset — rather than `JournalTemplate`/`JournalTemplateLine`, which no
   seeded or tested data actually exercises yet; templates remain the way to
   model a multi-line entry assembled from several fields, and are a
   reasonable next export source once a firm is actually using them.
3. ~~**The extraction provider is chosen globally, not per firm.**~~ Done for
   the axis that actually had two providers sitting behind an import swap —
   `Firm.extraction_provider` ("gemini" | "claude") now decides which
   `datalabs/backends.py` classes read a firm's bank/credit-card statements,
   settable through the firm page (aicounting-backend@b61f46f,
   aicounting-frontend@8803e5e). Two things this does *not* cover, both
   because there is nothing to switch to yet: field-configured documents
   (payroll, sales, ...) go through LandingAI's KV pipeline with no second
   provider, and `pipeline_registry.py`'s transactional/fields routing
   itself is still one Datalabs entry and one LandingAI entry — a real
   per-category provider override is still a future feature, not this one.

### Blocks operating it as a hosted product (do second)

4. **Local filesystem storage.** `STORAGES["default"]` is
   `FileSystemStorage`. Fine for one server; a second app server, a redeploy,
   or a container restart means missing files. This has to be GCS (or S3)
   before there's a second customer, not before there's a hundred.
5. ~~**No platform operator surface.**~~ Partly done — a read-only one, at
   least. `UserProfile.is_platform_staff` plus a `v1.platform` app
   (`GET /platform/{overview,firms,firms/:id}/`, and the matching `/platform`
   pages in the React app) let a platform account see every firm, its
   client/member/failed-document counts, and the fleet split by extraction
   provider, without `psql` (aicounting-backend@69fa2de,
   aicounting-frontend@0348ebc). `manage.py create_platform_admin` seeds the
   login. Still missing, and the harder half: no *action* surface —
   suspending a firm, looking inside a stuck classification queue, or
   resetting a locked-out owner all still need `psql` or a Django shell.
   That's the natural next slice once someone actually needs it.
6. ~~**No error tracking.**~~ Done — Sentry (Django + Celery +
   LoggingIntegration) and a real `LOGGING` config, JSON everywhere but
   DEBUG (aicounting-backend@ffeba55). The load-bearing detail: this
   codebase catches its own exceptions almost everywhere rather than letting
   them propagate (a provider timeout becomes a failed-status row, not a
   crash), so Sentry's usual "catch what Django/Celery would otherwise
   raise" hook had nothing to catch — `LoggingIntegration` is what actually
   surfaces the existing `logger.error(..., exc_info=True)` calls already
   in `v1/periods/tasks.py` as real events, with no call site touched. Set
   `SENTRY_DSN` per environment to turn it on; nothing changes with it unset.
7. **No usage metering.** Whatever the pricing model ends up being — per
   document, per seat, per client — there's no `ClassificationJob`-adjacent
   counter tracking pages processed or documents extracted per firm per
   month. This is table stakes before anyone can be billed accurately for
   Datalabs/LandingAI/Claude costs incurred on their behalf.
8. **No billing.** No Stripe, no plan, no seat limit. `FirmMembership` and
   `Client` have no enforcement of "you're on the 5-client plan." This can
   come after usage metering, since metering is the harder half.

### Real, but not a blocker to a first sale

9. **Console email backend is the default.** Works for one deployment where
   someone reads server logs; needs a transactional email provider (SES,
   Postmark) configured before invite emails reliably land in a real firm's
   inbox.
10. **No MFA.** Reasonable for now given email+password is already a step up
    from nothing; worth revisiting once a firm's IT department asks, which
    they will.
11. **Celery tasks have no explicit retry policy.** `process_document_task`
    fails hard on a transient provider timeout rather than retrying with
    backoff. `ClassificationJob` already has its own attempt-counting; the
    extraction task itself doesn't.
12. **No data retention or export-and-close-account story.** Soft delete
    exists (`SoftDeleteModel`) but nothing purges after a retention window,
    and there's no "firm requests their data, then leaves" flow. Matters more
    once a contract has a term.
13. **Reviewers are still platform-scoped in spirit if unattended** — no,
    this one's actually fixed (firm-scoped as of the last session). Leaving
    the line here as a note that it *was* a blocker and now isn't.

## What I'd build first

In order, because each unblocks the next kind of conversation:

1. **Configurable document categories** — turns "we only do bank statements
   and payroll" into "tell us what your clients send you." This is the
   product pitch, not a technical nicety.
2. **Journal export (CSV, then QBO IIF)** — closes the loop the pitch
   promises: extract → classify → *use it*.
3. **GCS storage** — required before a second real customer's files are at
   risk from anything less than a full outage.
4. **Usage metering** — required before billing can be honest, and useful
   internally (cost-per-firm) even before there's a paying second customer.
5. Platform operator surface, error tracking, per-client provider override —
   roughly parallel, pick based on which one bites first in practice.

Everything past that (billing, MFA, retention policy) is real but is a "when
you have paying customers" problem, not a "can I get a first paying customer"
problem.
