> **Historical record — the plan as approved.** One decision has since changed:
> reviewers are now firm-scoped, not platform-level. See
> [02-decisions.md](02-decisions.md).

# Rebuild aicounting-backend as a multi-tenant, API-only v1

## Context

`aicounting-backend` is a Django app that ingests a CPA firm's client documents
(bank statements, credit cards, payroll, sales), extracts transactions or
configured fields from them with LLM pipelines, classifies them against the
client's chart of accounts, and produces journal entries for a monthly close.

The domain is right; the implementation has drifted badly:

- **Tenancy is convention, not structure.** There is no tenant column and no
  central scoping. 177 occurrences of `hasattr(user, 'customer_profile')` /
  `accountant_profile` branching across 14 files hand-roll the filter in every
  view. `DimAicInputFiles.name` and `DimAICClient.client_id` are `unique=True`
  **globally** — two firms cannot name a file the same thing.
- **Snapshots duplicate everything.** Opening a month copies every template,
  template line, input file and attribute into four parallel `*Snapshot` tables
  **and re-uploads a byte copy of each source file to blob storage**
  (`fact_aic_monthly_accounting.py:_create_input_file_snapshot`). Storage and row
  count grow linearly with months × clients.
- **Half the extractor is dead.** Only two routes are wired in
  `extractor/pipeline_registry.py`: Datalabs (bank/credit card) and LandingAI KV
  (sales/payroll/misc). The Gemini, Claude and LandingAI pipelines and the whole
  1,737-line rectifier — the only Document AI consumer — are unreachable.
- **Naming is warehouse cosplay.** `DimAICCustomer` is a CPA firm, `DimAicInputFiles`
  is a configured document source, `FactAICMonthlyAccounting` is an accounting
  period. Table names (`customer`, `client`, `accountant`) are equally vague.
- Two live bugs: migration `0030_remove_zombie_models` deletes `ClassificationQueue`
  and `MonthlyDocumentBankKeyItem`, both still imported and used by
  `account/tasks.py`; and `anthropic` is imported at module scope by
  `extractor/pipelines/datalabs/backends.py` but absent from `requirements.txt`,
  so the only wired bank-statement pipeline cannot import on a clean install.

**Outcome:** a Postgres-backed, API-only Django project under a single `v1/`
package, where a CPA firm is a first-class tenant, its clients are onboarded and
configured per document type, config is versioned instead of copied, storage is
local (GCP-ready), and auth is email/password with an invite + set-password link.

## Decisions

Confirmed with the user:

| | |
|---|---|
| Package layout | Single top-level `v1/` holding all Django apps |
| Database | Postgres, **greenfield** — new schema, one fresh `0001_initial`, existing MySQL data dropped |
| Naming | Rename models **and** tables to domain names |
| Frontend | Backend first. Angular FE is being retired for React + React Native, so **no backward compatibility is owed to the current API contract** |
| Storage | Drop Azure Blob. Local filesystem now, GCS later via `STORAGES` |
| Auth | Drop Azure AD SSO/MSAL. Email + password, invite → set-password link |

Decided by me (user is AFK), flagged for later override:

- **Django admin is dropped**, with `TEMPLATES`, `staticfiles`, `messages` and
  `sessions`. "Just an API" plus a wholesale model rename makes the 1,095 lines
  of `account/admin.py` + `user/admin.py` pure liability. Ops access is psql or a
  future internal endpoint.
- **Reviewers stay platform-level** (a membership with `firm = NULL`), matching
  today's global round-robin in `DimAICReviewer.get_next_reviewer`. ⚠️ This means
  a reviewer sees documents across firms — a deliberate cross-tenant hole that
  needs a yes/no once you're back.
- **The Claude backends in `pipelines/datalabs/backends.py` are kept** (they are
  a one-line provider swap and imported at module scope); `anthropic` gets added
  to requirements. The standalone `pipelines/claude/` is deleted.
- **`extractor/` stays top-level**, outside `v1/`. It is provider code, not an
  API version, and versioning it would fork pipelines for no reason.

## Target shape

```
aicounting-backend/
  documentation/            ← plan + decisions + API contract (Phase 0)
  v1/
    identity/     UserProfile, PasswordSetToken, auth endpoints
    tenancy/      Firm, FirmMembership, Client, ClientAssignment,
                  ClientContact, ClientReferenceDocument
    ledger/       LedgerAccount, LedgerAccountType, ClientClassifierProfile
    configuration/ DocumentSource, ExtractionField, JournalTemplate,
                  JournalTemplateLine, ConfigVersion
    periods/      AccountingPeriod, PeriodDocument, PeriodTransaction,
                  PeriodCheckDetail, PeriodFieldValue,
                  PeriodManualJournalLine, ClassificationJob
    review/       reviewer endpoints (no models)
    dashboard/    read-only aggregates
    common/       BaseModel, TenantScopedQuerySet, permissions, responses
  extractor/      datalabs + kv pipelines, classification, persistence
  storage/        path builder + local/GCS backends
  aicounting/     settings, celery, urls
```

`INSTALLED_APPS = ['v1.identity', 'v1.tenancy', ...]`. Django derives app labels
from the last path segment, so `identity`, `tenancy`, `ledger`, `configuration`,
`periods`, `review`, `dashboard` — no collision with `django.contrib.auth`
(which is why the auth app is named `identity`, not `auth`).

### Model and table renames

| Today | New model | New table |
|---|---|---|
| `DimAICCustomer` | `Firm` + `FirmMembership(role=owner)` | `firm`, `firm_membership` |
| `DimAICAccountant` | `FirmMembership(role=accountant)` | `firm_membership` |
| `DimAICReviewer` | `FirmMembership(firm=NULL, role=reviewer)` | `firm_membership` |
| — (Azure fields, x3 models) | `UserProfile` | `user_profile` |
| `DimAICClient` | `Client` | `client` |
| `DimAICContact` | `ClientContact` | `client_contact` |
| `DimAICClientDocument` | `ClientReferenceDocument` | `client_reference_document` |
| `DimAICGLAcct` | `LedgerAccount` | `ledger_account` |
| `DimAICAcctType` | `LedgerAccountType` | `ledger_account_type` |
| `DimAICAssistant` | `ClientClassifierProfile` | `client_classifier_profile` |
| `DimAicInputFiles` | `DocumentSource` | `document_source` |
| `DimAicInputFileAttributes` | `ExtractionField` | `extraction_field` |
| `DimAICJETemplateHeader` | `JournalTemplate` | `journal_template` |
| `DimAICJETemplateAttribute` | `JournalTemplateLine` | `journal_template_line` |
| 4 × `*Snapshot` tables | `ConfigVersion` (one JSONB row) | `config_version` |
| `FactAICMonthlyAccounting` | `AccountingPeriod` | `accounting_period` |
| `MonthlyAccountingDocument` | `PeriodDocument` | `period_document` |
| `MonthlyDocumentBankLineItem` | `PeriodTransaction` | `period_transaction` |
| `MonthlyDocumentBankCheckItem` | `PeriodCheckDetail` | `period_check_detail` |
| `MonthlyDocumentAttributeItem` | `PeriodFieldValue` | `period_field_value` |
| `MonthlyTemplateManualAttributeItem` | `PeriodManualJournalLine` | `period_manual_journal_line` |
| `ClassificationQueue` | `ClassificationJob` | `classification_job` |
| `DimAICJEFreq`, `DimAICJEType` | `TextChoices` enums | *(dropped)* |
| `DimAICJETemplateGL`, `FactAICJETransBank`, `FactAICJEMonthlyStat`, `MonthlyDocumentBankKeyItem` | *(deleted)* | *(dropped)* |

### Document types: transactional vs field-configured

This is the distinction the current schema fails to express. `DocumentSource.document_type`
drives it, enforced in `DocumentSource.clean()`:

- **Transactional** — `bank_statement`, `credit_card`, `check_register`.
  No `ExtractionField` rows allowed. The pipeline emits `PeriodTransaction` rows;
  configuration is just the statement's `LedgerAccount` plus a default offset.
  GL assignment happens per-transaction via the classifier.
- **Field-configured** — `payroll`, `sales`, `misc`.
  At least one `ExtractionField` required. Each field carries `key` (slug),
  `label`, `prompt_hint`, `direction` (debit/credit), `ledger_account`,
  `offset_ledger_account`. `extractor/pipelines/kv/landing_pipeline.py:build_dynamic_extraction_model`
  already consumes exactly this — it will read live `ExtractionField` rows instead
  of `FactAICInputFileAttributeSnapshot`.

### Config versioning replaces snapshots

`ConfigVersion(client, version, payload JSONB, published_at, published_by)` —
one immutable row per publish of a client's configuration. `AccountingPeriod`
carries `config_version` (PROTECT). Opening a month reuses the current version;
publishing a config change mints a new one.

Why JSONB and not mirrored tables: the frozen config is only ever read whole, at
period open and at JE generation — never joined or aggregated across periods. One
row replaces ~4N rows per period, and **no file bytes are copied at all**.

Extracted rows stop pointing at snapshot rows. `PeriodTransaction` and
`PeriodFieldValue` denormalize what they need at write time —
`field_key`, `resolved_ledger_account_id`, `resolved_offset_account_id` — with
`SET_NULL` FKs to the live rows for convenience. History survives config edits.

## Execution

### Phase 0 — Documentation and safety net

1. Create `documentation/` with `00-current-state.md` (the findings above),
   `01-target-architecture.md`, `02-decisions.md` (the tables above, with the
   flagged open items), `03-api-v1-contract.md` (filled in during Phase 6 — this
   is the React team's handoff).
2. Add the four secret files still untracked from the last commit to `.gitignore`:
   `aicounting-2025v1-*.json`, `mysql.cnf.prod`, `.prod.dep.md`, `dump.rdb`.
   The DB password `6MnV1hXY!4` appears in two of them and dies with MySQL anyway.
3. Branch `refactor/v1-multitenant` off `development`.

### Phase 1 — Delete dead weight, remove Document AI

Pure deletion against the current tree, so it can land and be verified before
anything is restructured.

Delete: `extractor/rectifier/` (2,212 lines, the only Document AI consumer),
`extractor/pipelines/gemini/`, `extractor/pipelines/claude/`,
`extractor/pipelines/landing_ai/`, `extractor/pipelines/kv/gemini_pipeline.py`.
These cascade to `extractor/prompter.py`, `extractor/statement_models.py` and
`GeminiDocumentProcessor` in `extractor/base.py` — all then unreferenced.

Also delete: `user/manual_tool.py` (337 lines, zero references),
`account/models.py` and `user/models.py` (3-line stubs shadowed by the packages
of the same name), `account/management/commands/migrate_files_to_new_structure.py`,
`celerybeat-schedule.db`.

Trim `extractor/pipeline_registry.py` to the two live routes. Drop the unused
`agentic_doc` imports at `account/tasks.py:23-24`. Drop
`DOCUMENT_AI_*` from `aicounting/env_settings.py`.

Re-save `requirements.txt` as UTF-8 (it is currently UTF-16, which is why git
treats it as binary). Remove `google-cloud-documentai`, `agentic-doc`,
`landingai`; add the missing `anthropic`.

Delete migration `0030_remove_zombie_models.py` — it is inconsistent with the
models still defined, and the greenfield migration in Phase 3 supersedes it.

### Phase 2 — Postgres, local storage, API-only settings

- `DATABASES` → `django.db.backends.postgresql` from env vars. Delete `mysql.cnf`,
  `mysql.cnf.prod`; swap `mysqlclient` for `psycopg[binary]`.
- Delete `aicounting/azure_storage_backends.py` and `aicounting/msal_conf.py`.
  Move `aicounting/azure_storage_paths.py` → `storage/paths.py`, stripped of SAS
  logic and of the `05_document_ai` / `06_rectification` artifact stages.
  `aicounting/file_upload_helper.py` → `storage/uploads.py`.
- `STORAGES["default"]` → `FileSystemStorage` with `MEDIA_ROOT = BASE_DIR/media`.
  Every call site goes through `django.core.files.storage.default_storage` already,
  so GCS later is a settings change plus `django-storages[google]`.
- File access moves behind an authenticated Django view that checks tenancy and
  streams (local) or 302s to a signed URL (GCS) — replacing
  `DimAICClientDocument.get_secure_url`'s Azure SAS call.
- Remove `django.contrib.admin`, `staticfiles`, `messages`, `sessions`, the whole
  `TEMPLATES` block, and the `static()` lines in `aicounting/urls.py`. Delete
  `account/admin.py`, `user/admin.py`, `authentication/admin.py`, `dashboard/admin.py`.
- Fix `CORS_ALLOW_ALL_ORIGINS = True` + `CORS_ALLOW_CREDENTIALS = True`
  (`settings.py:187-190`) — that combination is rejected by browsers and is wide
  open regardless. Explicit origin list from env.

### Phase 3 — `v1/` package and the new schema

1. Create the `v1/` tree above; each app gets `apps.py`, `models/`, `serializers/`,
   `views/`, `urls.py`, `migrations/`.
2. `v1/common/models.py`: `TimeStampedModel` (created_at/updated_at/created_by),
   `SoftDeleteModel`, and `TenantScopedQuerySet.for_user(user)` — one place that
   resolves a user's firm and visible clients, replacing all 177 hand-rolled checks.
3. Write the models per the rename table. Constraint fixes that matter:
   - `Client`: `UniqueConstraint(firm, external_ref)` — was global `unique=True`.
   - `DocumentSource`: `UniqueConstraint(client, name)` — was global `unique=True`.
   - `LedgerAccount`: drop the redundant `customer` FK (derivable from `client`,
     and today the two can disagree); `UniqueConstraint(client, account_number)`.
   - `ExtractionField.document_source` becomes non-nullable `CASCADE` (was
     `SET_NULL`, which orphans fields).
   - `AccountingPeriod`: `UniqueConstraint(client, year, month)` with a
     `condition=Q(is_deleted=False)` — currently enforced only in `clean()`,
     which DRF never calls.
   - Indexes on every tenant-scoping path: `(client, ...)` on periods, documents,
     transactions.
4. One `0001_initial` per app. No data migration — greenfield.
5. Delete `account/`, `user/`, `authentication/`, `dashboard/` once ported.

### Phase 4 — Auth without SSO

Replace `authentication/` (416-line MSAL view module) with `v1/identity/`:

- `UserProfile(user OneToOne, is_verified, last_login_at)` — absorbs the
  `azure_id` / `refresher_token` / `verified` triplication across the three old
  role models.
- `PasswordSetToken(user, token_hash, purpose[invite|reset], expires_at, used_at)` —
  single-use, hashed at rest, 48h for invite / 1h for reset.
- Flow: a firm owner invites by email → inactive `User` + `FirmMembership` +
  token → email link `{APP_URL}/set-password?token=…` → `POST /api/v1/auth/set-password/`
  sets the password, marks verified, activates. Same machinery for
  `POST /api/v1/auth/forgot-password/`.
- `POST /api/v1/auth/login/` returns access + refresh via
  `djangorestframework-simplejwt`; `PASSWORD_HASHERS` led by Argon2. Throttle
  login and set-password.
- Email: `console.EmailBackend` in dev, SMTP from env in prod.
- Keep `JWTAuthenticationMiddleware`'s caching idea (`authentication/middleware.py`),
  drop the Azure token-refresh path in `authentication/authenticate.py`.
- `authentication/permissions.py` → `v1/common/permissions.py`: `IsFirmOwner`,
  `IsFirmMember`, `IsReviewer`, `HasClientAccess` — the last one resolving through
  `TenantScopedQuerySet` rather than re-deriving per view.

### Phase 5 — Config versioning

- `v1/configuration/services/publish.py`: `publish_config(client, user) -> ConfigVersion`
  serialises sources, fields, templates and lines into `payload`, bumps `version`.
- `v1/periods/services/open_period.py`: creates `AccountingPeriod` pinned to the
  client's current `ConfigVersion` and one `PeriodDocument` per configured source —
  replacing `create_monthly_accounting_with_snapshots`, `create_snapshots`,
  `_create_input_file_snapshot`, `_create_template_snapshot` **and the per-period
  file copy into blob storage**.
- Delete the four `*Snapshot` models and `account/models/dim_aic_snapshot_models.py`.
- `je_freq__icontains='monthly'` (a string `LIKE` against a lookup table to decide
  which templates are monthly) becomes `JournalTemplate.frequency == Frequency.MONTHLY`.

### Phase 6 — API v1 surface

Same URL prefix (`/api/v1/`), redesigned resources — nothing owed to the Angular client.

```
/api/v1/auth/          login, refresh, set-password, forgot-password, me
/api/v1/firm/          profile, members (invite/list/deactivate)
/api/v1/clients/       CRUD, contacts, reference documents, assignments
/api/v1/clients/{id}/ledger-accounts/
/api/v1/clients/{id}/document-sources/        + /{id}/fields/
/api/v1/clients/{id}/journal-templates/       + /{id}/lines/
/api/v1/clients/{id}/config/publish|versions/
/api/v1/clients/{id}/periods/                 open, list, detail, delete
/api/v1/periods/{id}/documents/{id}/          upload, status, transactions, fields
/api/v1/periods/{id}/journal-templates/{id}/  detail, verify, export
/api/v1/review/documents/                     reviewer queue
/api/v1/dashboard/
```

- ViewSets + routers over the current 30+ hand-written `GenericAPIView` classes.
- All list querysets start from `Model.objects.for_user(request.user)`.
- One DRF exception handler replaces the 178 `except Exception` blocks that
  currently swallow errors into 500s with a stringified traceback in the log.
- `dashboard/queries.py` raw SQL is rewritten as ORM aggregates — it uses MySQL's
  `ELT()`, which does not exist in Postgres.
- Record the finished contract in `documentation/03-api-v1-contract.md`.

### Phase 7 — Rewire the extractor

`extractor/` keeps its shape; only its model touchpoints change.

- `kv/landing_pipeline.py:_build_dynamic_schema` reads `ExtractionField` for the
  document's `DocumentSource` instead of `FactAICInputFileAttributeSnapshot`.
- `persistence/attribute_saver.py`, `persistence/bank_statement_saver.py`,
  `classification/service.py` move to the new model names; the classifier's
  `_get_default_offset_gl` reads the pinned `ConfigVersion` payload.
- `account/tasks.py` → `v1/periods/tasks.py`, unchanged in structure
  (`process_document_task` → `validate_control_totals_task` → `enqueue_classification_task`,
  plus the beat-driven `process_classification_queue_task` over `ClassificationJob`).
- `DimAICAssistant` → `ClientClassifierProfile`. Note that
  `classification/service.py:110` silently no-ops when `vector_store_ids` is empty —
  add an explicit failure so a missing profile surfaces instead of producing zero
  classifications.

## Verification

Per phase, not just at the end:

1. **Phase 1** — `python manage.py check` and `python manage.py makemigrations --check`
   still pass against MySQL; `grep -r "documentai\|rectifier\|agentic_doc"` returns nothing.
2. **Phase 2** — Postgres up via a `docker-compose.yml` added in this phase;
   `manage.py check` clean with no `django.contrib.admin`.
3. **Phase 3** — `migrate` on an empty Postgres DB from zero;
   `makemigrations --check --dry-run` reports no drift.
4. **Phase 4** — pytest covering: invite → set-password → login → refresh;
   expired token rejected; token single-use; login throttled.
5. **Phase 5** — test that publishing config after a period is open leaves that
   period's resolved config unchanged, and that opening a period creates zero
   new blob objects.
6. **Tenancy (the one that matters)** — a test fixture with two firms, two clients
   each, then a parametrised sweep asserting every `/api/v1/` endpoint returns
   403/404 for a member of the other firm. This is the regression net for the
   177 checks being replaced.
7. **End to end** — seed one firm, one client, a chart of accounts, one
   `bank_statement` source and one `payroll` source with three fields; publish
   config; open a period; upload a real PDF to each; assert `PeriodTransaction`
   rows from Datalabs and `PeriodFieldValue` rows from the KV pipeline, then
   classification populating `resolved_ledger_account`.
8. `pytest` + `ruff` wired into `.github/workflows/`.

## Out of scope

- The Angular frontend. It is left untouched and will break against the new
  contract by design; the React/React Native rewrite consumes
  `documentation/03-api-v1-contract.md`.
- GCP deployment (Cloud Run, Cloud SQL, GCS). The storage and settings layers are
  built so it is a configuration change, but no infra work happens here.
- Migrating existing MySQL data.
