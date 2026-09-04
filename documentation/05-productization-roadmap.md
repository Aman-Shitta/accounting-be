# From single-tenant tool to sellable product

The v1 rebuild fixed the architectural problems (tenancy, config versioning,
naming, the API surface). None of that is wasted — it's the foundation. But
"sell this to any CPA firm" surfaces a different category of gap: the system
still assumes *one kind of client* doing *one kind of close*. This is a survey
of what's in the way, ranked by how much it actually blocks a sale.

## The core problem: document types are a fixed enum

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
a `DocumentCategory` model owned by the platform (not per-firm — the two
extraction *behaviors* are real, categories within them are not) holding
`{key, label, extraction_mode: transactional|fields}`, with `DocumentSource`
referencing it by FK instead of a `TextChoices` value. `MISC` already exists
as an escape hatch, which tells you the enum was already straining.

## Everything else, ranked by how hard it blocks a sale

### Blocks selling to more than one firm's worth of documents (do first)

1. **Document types are a fixed enum.** Covered above.
2. **No export to what a firm actually files with.** `JournalTemplate` and
   `JournalTemplateLine` model the entry correctly, but nothing renders one —
   no QBO IIF, no Xero-shaped CSV, not even a plain CSV. Right now the product
   extracts and classifies, and then the firm re-keys the entry by hand
   into whatever they file with. That's the last mile of the actual pitch.
3. **The extraction provider is chosen by document type, globally**
   (`pipeline_registry.py`), not per firm or per client. One firm's Datalabs
   outage is every firm's outage, and there's no way to say "this client's
   statements are weird, use the Claude backend for them" without a code
   change — even though `datalabs/backends.py` already has Claude variants
   sitting unused for exactly this.

### Blocks operating it as a hosted product (do second)

4. **Local filesystem storage.** `STORAGES["default"]` is
   `FileSystemStorage`. Fine for one server; a second app server, a redeploy,
   or a container restart means missing files. This has to be GCS (or S3)
   before there's a second customer, not before there's a hundred.
5. **No platform operator surface.** Django admin was removed as dead weight
   for a single-tenant tool, which was the right call then — but a product
   with paying firms needs *someone* who can see every firm, suspend one,
   look at a stuck classification queue, or reset a locked-out owner, without
   `psql`. There is currently no `is_superuser` check anywhere in `v1/`.
6. **No error tracking.** No Sentry, no structured logging config. A
   provider timeout or a bad extraction currently surfaces as a log line on
   whichever server happened to run the Celery worker. At one firm that's
   tolerable; at ten, you find out about outages from angry emails.
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
