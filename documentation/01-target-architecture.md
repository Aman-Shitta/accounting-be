# Target architecture — v1

A Postgres-backed, API-only Django project where a CPA firm is a first-class
tenant, client configuration is versioned rather than copied, and the HTTP
surface lives under one `v1/` package.

## Package layout

```
aicounting-backend/
  documentation/
  v1/
    common/        BaseModel, TenantScopedQuerySet, permissions, exception handler
    identity/      UserProfile, PasswordSetToken, auth endpoints
    tenancy/       Firm, FirmMembership, Client, ClientAssignment,
                   ClientContact, ClientReferenceDocument
    ledger/        LedgerAccount, LedgerAccountType, ClientClassifierProfile
    configuration/ DocumentSource, ExtractionField, JournalTemplate,
                   JournalTemplateLine, ConfigVersion
    periods/       AccountingPeriod, PeriodDocument, PeriodTransaction,
                   PeriodCheckDetail, PeriodFieldValue,
                   PeriodManualJournalLine, ClassificationJob, tasks
    review/        reviewer queue endpoints (no models)
    dashboard/     read-only aggregates
  extractor/       datalabs + kv pipelines, classification, persistence
  storage/         path builder, local/GCS backends, authenticated file serving
  aicounting/      settings, celery, root urls
```

`INSTALLED_APPS = ['v1.identity', 'v1.tenancy', 'v1.ledger', 'v1.configuration',
'v1.periods', 'v1.review', 'v1.dashboard']`.

Django derives an app label from the last path segment, so the labels are
`identity`, `tenancy`, `ledger`, `configuration`, `periods`, `review`,
`dashboard`. The auth app is named `identity` rather than `auth` specifically to
avoid colliding with `django.contrib.auth`'s label.

`extractor/` stays outside `v1/`. It is provider code, not an API version;
versioning it would fork the pipelines for no reason.

## Tenancy

```
User ─1:1─ UserProfile
  │
  └─< FirmMembership(firm, role) >─ Firm
                                      │
                                      └─< Client ─< ClientAssignment >─ FirmMembership
```

- **`Firm`** is the tenant — one CPA firm. Everything else hangs off it.
- **`FirmMembership(user, firm, role)`** replaces three near-duplicate models
  (`DimAICCustomer` as owner, `DimAICAccountant`, `DimAICReviewer`), each of
  which separately carried `system_user`, `azure_id`, `refresher_token` and
  `verified`. Roles: `owner`, `accountant`, `reviewer`.
- **`UserProfile`** absorbs the per-user fields those three duplicated.
- **`ClientAssignment`** replaces the `assigned_accountants` M2M, so the join
  carries `assigned_at` / `assigned_by`.
- A `FirmMembership` with `firm = NULL` and `role = reviewer` is a
  **platform-level reviewer** — see `02-decisions.md`, this is a deliberate
  cross-tenant hole inherited from today's behaviour and needs confirmation.

### Enforcement

`v1/common/querysets.py` provides one scoping entry point:

```python
class TenantScopedQuerySet(models.QuerySet):
    def for_user(self, user):
        """Restrict to rows the user's firm membership can see."""
```

Every list view starts from `Model.objects.for_user(request.user)`. Every
detail view goes through `HasClientAccess`. Nothing re-derives the tenant
inline — that pattern is what the 177 hand-rolled checks were.

Backed by constraints, not just code:

| Model | Constraint |
|---|---|
| `Client` | `UniqueConstraint(firm, external_ref)` — was globally unique |
| `DocumentSource` | `UniqueConstraint(client, name)` — was globally unique |
| `LedgerAccount` | `UniqueConstraint(client, account_number)`; no separate firm FK |
| `AccountingPeriod` | `UniqueConstraint(client, year, month) WHERE NOT is_deleted` |

## Document types

`DocumentSource.document_type` splits into two behaviours, enforced in
`DocumentSource.clean()` and by the API serializer:

### Transactional — `bank_statement`, `credit_card`, `check_register`

No `ExtractionField` rows are allowed. The document *is* a list of transactions;
there is nothing to name in advance. Configuration is only:

- `ledger_account` — the account the statement represents
- `default_offset_account` — where the other side of each entry lands

The pipeline emits `PeriodTransaction` rows and the classifier assigns a
`LedgerAccount` per transaction from the client's chart of accounts.

### Field-configured — `payroll`, `sales`, `misc`

At least one `ExtractionField` is required. Each field declares what to pull and
where it books:

| Field | Purpose |
|---|---|
| `key` | slug used as the JSON schema property |
| `label` | human name shown in the UI |
| `prompt_hint` | free text fed to the extractor as the field description |
| `direction` | `debit` or `credit` |
| `ledger_account` | where the value books |
| `offset_ledger_account` | the contra account |

The KV pipeline already consumes exactly this shape —
`extractor/pipelines/kv/landing_pipeline.py:build_dynamic_extraction_model`
turns the field list into a Pydantic model and drops properties from the schema
as they are found, page by page. It changes only in where it reads the fields
from.

This is the distinction the current schema fails to express: today a bank
statement and a payroll register are both "input files with attributes", and
nothing stops someone configuring attributes on a bank statement, where they are
silently ignored.

## Config versioning replaces snapshots

```
Client ─< ConfigVersion(version, payload JSONB, published_at, published_by)
              ▲
              │ PROTECT
         AccountingPeriod ─< PeriodDocument ─< PeriodTransaction / PeriodFieldValue
```

`publish_config(client, user)` serialises the client's document sources,
extraction fields, journal templates and template lines into one immutable
JSONB `payload` and bumps `version`. Opening a period pins the client's current
`ConfigVersion`. Editing config afterwards mints a new version and leaves open
periods untouched.

**Why JSONB and not mirrored tables.** The frozen config is only ever read as a
whole document — at period open, and again at JE generation. It is never joined
against, filtered on, or aggregated across periods. One row replaces roughly 4N
rows per period, and no file bytes are copied at all.

**Extracted rows carry their own resolved values.** `PeriodTransaction` and
`PeriodFieldValue` denormalize `field_key`, `resolved_ledger_account_id` and
`resolved_offset_account_id` at write time, with `SET_NULL` FKs to the live rows
for convenience. A later config edit cannot rewrite history, and nothing has to
point at a snapshot row to stay meaningful.

## Storage

Local filesystem now, GCS later, one seam:

- `STORAGES["default"]` → `FileSystemStorage`, `MEDIA_ROOT = BASE_DIR / "media"`.
- Every call site already goes through `django.core.files.storage.default_storage`,
  so GCS is a settings change plus `django-storages[google]`.
- `storage/paths.py` (from `aicounting/azure_storage_paths.py`) keeps the
  `<firm>/<client>/<period>/<doc>/` layout and the numbered processing-artifact
  stages, minus the Document AI and rectification stages that no longer exist.
- Files are never served by URL directly. An authenticated view checks tenancy,
  then streams the file (local) or 302s to a signed URL (GCS) — replacing
  `DimAICClientDocument.get_secure_url`'s Azure SAS call.

## Auth

Azure AD SSO and MSAL are gone. Email and password, with invite-based onboarding:

```
owner invites email
  → inactive User + FirmMembership + PasswordSetToken(purpose=invite, 48h)
  → email link {APP_URL}/set-password?token=…
  → POST /api/v1/auth/set-password/  → password set, verified, activated
  → POST /api/v1/auth/login/         → access + refresh JWT
```

`PasswordSetToken` stores a hash, is single-use, and expires (48h invite / 1h
reset). The same machinery serves `forgot-password`. Argon2 leads
`PASSWORD_HASHERS`. Login and set-password are throttled.

The JWT middleware's authenticate-once-and-cache behaviour is kept from
`authentication/middleware.py`; the Azure token-refresh path in
`authentication/authenticate.py` is dropped.

## API-only

`django.contrib.admin`, `staticfiles`, `messages`, `sessions` and the entire
`TEMPLATES` block are removed, along with `account/admin.py` and `user/admin.py`
(1,095 lines). The project serves JSON and nothing else.

Consequences: no Django admin UI for ops. Access is psql, or a future internal
endpoint. See `02-decisions.md`.

## Processing flow (unchanged in shape)

```
POST upload → process_document_task
  → get_pipeline_class(document_type)
       bank_statement, credit_card, check_register → Datalabs
       sales, payroll, misc                        → LandingAI KV
  → validate_control_totals_task
  → enqueue_classification_task → ClassificationJob
  → process_classification_queue_task  [beat, one job per client at a time]
```

The pipeline registry, the Celery chain and the per-client classification
serialisation all survive as-is. Only their model touchpoints change.
