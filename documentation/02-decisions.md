# Decisions

Recorded so the reasoning survives the rewrite. Anything marked ⚠️ is an open
question with a working default, not a settled call.

## Confirmed with the product owner

| Decision | Choice | Why |
|---|---|---|
| Package layout | Single top-level `v1/` holding all Django apps | Asked for explicitly. A future `v2` sits beside it. |
| Database | Postgres, **greenfield** — new schema, fresh `0001_initial`, existing MySQL data dropped | The existing schema is being redesigned anyway and holds no data worth keeping. |
| Naming | Rename models **and** tables to domain names | The `Dim*`/`Fact*` prefixes describe a star schema that does not exist, and the table names are too generic. Greenfield is the only cheap moment to fix both. |
| Frontend | Backend first; Angular is being retired for React + React Native | **No backward compatibility is owed to the current API contract.** The v1 surface is redesigned freely. |
| Storage | Drop Azure Blob. Local filesystem now, GCS later | Deployment target moved to GCP. |
| Auth | Drop Azure AD SSO/MSAL. Email + password, invite → set-password link | Self-service registration without an Azure tenant. |

## Made without the owner present

These were decided to keep momentum. Each is cheap to reverse.

### Django admin is dropped

Removing `django.contrib.admin` also removes `TEMPLATES`, `staticfiles`,
`messages` and `sessions` — the whole non-API half of Django.

- **For:** the brief is "just an API". The 1,095 lines in `account/admin.py` and
  `user/admin.py` would all need rewriting against renamed models, for a UI
  nobody uses in the product.
- **Against:** no ops UI. Inspecting or fixing data means psql.
- **Reversible?** Yes, but the admin classes would have to be written fresh.

### Reviewers stay platform-level ⚠️

`FirmMembership` allows `firm = NULL` for `role = reviewer`, matching today's
`DimAICReviewer.get_next_reviewer()`, which round-robins over every verified
reviewer on the platform regardless of firm.

**This is a cross-tenant hole.** A reviewer at the platform level sees documents
belonging to any firm. It is inherited behaviour, not a new design, and it is
preserved so the review queue keeps working — but a genuinely multi-tenant
product probably wants reviewers scoped to a firm, with a platform pool as an
explicit opt-in per firm.

**Needs a yes/no.** If reviewers should be firm-scoped, `FirmMembership.firm`
becomes non-nullable and `get_next_reviewer` takes a firm argument. That is a
small change now and an expensive one later.

### Claude backends kept, standalone Claude pipeline deleted

`extractor/pipelines/datalabs/backends.py` defines Gemini *and* Claude variants
of all three extractors and imports `ClaudeMixin` at module scope; switching
provider is a one-line import change in `pipeline.py`. Those stay, and
`anthropic` is added to `requirements.txt` where it was missing.

The standalone `extractor/pipelines/claude/` pipeline (356 lines, unreferenced
by the registry) is deleted.

### `extractor/` stays outside `v1/`

It holds LLM provider integrations, not an API contract. Versioning it would
mean forking the pipelines whenever the HTTP surface changes, which is backwards.

### Lookup tables become enums

`DimAICJEFreq` and `DimAICJEType` are dropped as tables in favour of
`TextChoices`. They hold a handful of fixed rows and are queried with string
matching — `create_snapshots` does
`DimAICJEFreq.objects.get(je_freq__icontains='monthly')`, a `LIKE` against a
lookup table to decide which templates are monthly.

### `MonthlyDocumentBankKeyItem` is dropped entirely

Its content is control totals, which already live in
`MonthlyAccountingDocument.control_item` (JSONB). The only writer was the Gemini
pipeline, which is being deleted.

### auditlog is kept, scoped to user-editable rows

`django-auditlog` stays registered on rows a human edits — transactions, field
values, templates — because an accounting product needs to show who changed a
number. It is *not* extended to config or period tables. If write volume becomes
a problem, this is the first knob to turn.

## Rejected alternatives

**Mirror tables for config versioning instead of JSONB.** Keeps the config
relational and queryable across periods. Rejected: that is exactly what the four
`*Snapshot` tables do today, and nothing ever queries across periods — the
payload is read whole, twice per period. The row-count problem is the thing
being fixed.

**Keep `Dim*`/`Fact*` names to shrink the diff.** Rejected: the frontend is
being rewritten anyway, so the usual reason to preserve names (client breakage)
does not apply, and the names actively mislead.

**Versioning the models under `v1/` rather than only the HTTP layer.** Noted as
the cleaner architecture — a `v2` API should reuse `v1` models rather than fork
them — but the owner asked for the literal single-`v1/` layout, and a fork can
be avoided by convention when `v2` arrives.

**Migrating the MySQL data.** Rejected by the owner; the existing data has no
value.

## Follow-ups not handled here

- **Rotate the GCP service-account key** in `aicounting-2025v1-*.json`. It was
  sitting untracked in the working tree with a live private key; it is now
  gitignored but was never rotated.
- The MySQL production password appeared in plaintext in `mysql.cnf.prod` and
  `.prod.dep.md`. It dies with the MySQL migration.
- GCP deployment (Cloud Run, Cloud SQL, GCS buckets) is out of scope. The
  storage and settings layers are built so it is a configuration change.
