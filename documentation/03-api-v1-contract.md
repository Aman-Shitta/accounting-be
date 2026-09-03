# API v1 contract

> **Status: skeleton.** Endpoint shapes are settled; request/response bodies are
> filled in during Phase 6 as each ViewSet lands. This document is the handoff to
> the React / React Native client — it is the only thing that client should need.

Base URL: `/api/v1/`. All responses are JSON. All endpoints except
`auth/login`, `auth/set-password` and `auth/forgot-password` require
`Authorization: Bearer <access token>`.

## Conventions

- **Envelope.** Every response is `{"status": <int>, "message": <string>, "data": <object|null>, "errors": <object|null>}`.
- **Errors.** A single DRF exception handler maps validation errors to 400 with
  `errors` populated, permission failures to 403, missing or out-of-tenant rows
  to 404. There is no code path that returns a stringified traceback.
- **Tenancy.** A row belonging to another firm returns 404, not 403 — existence
  is not leaked across tenants.
- **Pagination.** Cursor pagination on every list endpoint:
  `?limit=&cursor=`, with `data.next` / `data.previous`.
- **IDs.** Integer primary keys in URLs. `client.external_ref` is the firm's own
  code for a client and is unique per firm, never globally.

## Endpoints

### Auth — `/api/v1/auth/`

| Method | Path | Purpose |
|---|---|---|
| POST | `login/` | email + password → access + refresh |
| POST | `refresh/` | refresh → new access |
| POST | `set-password/` | consume an invite or reset token, set a password |
| POST | `forgot-password/` | issue a reset token by email |
| GET | `me/` | current user, profile, firm, role, visible client count |

### Firm — `/api/v1/firm/`

| Method | Path | Purpose |
|---|---|---|
| GET, PATCH | `` | the caller's firm profile |
| GET, POST | `members/` | list members; invite by email + role |
| GET, PATCH, DELETE | `members/{id}/` | role change, deactivate |

### Clients — `/api/v1/clients/`

| Method | Path | Purpose |
|---|---|---|
| GET, POST | `` | list / onboard a client |
| GET, PATCH, DELETE | `{id}/` | detail |
| GET, POST | `{id}/contacts/` | client contacts |
| GET, POST | `{id}/reference-documents/` | COA, vendor list, GL history upload |
| GET, PUT | `{id}/assignments/` | which members can see this client |
| GET, POST | `{id}/ledger-accounts/` | chart of accounts |

### Configuration — `/api/v1/clients/{id}/`

| Method | Path | Purpose |
|---|---|---|
| GET, POST | `document-sources/` | list / create a configured source |
| GET, PATCH, DELETE | `document-sources/{id}/` | detail |
| GET, PUT | `document-sources/{id}/fields/` | extraction fields — **field-configured types only** |
| GET, POST | `journal-templates/` | JE templates |
| GET, PATCH, DELETE | `journal-templates/{id}/` | detail |
| GET, PUT | `journal-templates/{id}/lines/` | template lines |
| POST | `config/publish/` | freeze current config into a new `ConfigVersion` |
| GET | `config/versions/` | version history |

`POST document-sources/` with a transactional `document_type` and a non-empty
`fields` array is a 400. A field-configured type with zero fields is a 400 at
publish time.

### Periods — `/api/v1/clients/{id}/periods/` and `/api/v1/periods/{id}/`

| Method | Path | Purpose |
|---|---|---|
| GET, POST | `clients/{id}/periods/` | list / open a month (pins current `ConfigVersion`) |
| GET, DELETE | `periods/{id}/` | detail with documents; soft delete |
| GET | `periods/{id}/documents/` | one per configured source |
| POST | `periods/{id}/documents/{id}/upload/` | upload, triggers the Celery chain |
| GET | `periods/{id}/documents/{id}/` | status, control totals, mismatch details |
| GET, POST | `periods/{id}/documents/{id}/transactions/` | transactional types |
| PATCH, DELETE | `periods/{id}/documents/{id}/transactions/{id}/` | edit a line |
| GET, PUT | `periods/{id}/documents/{id}/field-values/` | field-configured types |
| POST | `periods/{id}/documents/{id}/verify/` | mark verified |
| GET | `periods/{id}/journal-templates/{id}/` | resolved JE |
| POST | `periods/{id}/journal-templates/{id}/verify/` | verify + generate export |

### Review — `/api/v1/review/`

| Method | Path | Purpose |
|---|---|---|
| GET | `documents/` | reviewer queue (see the platform-scope caveat in `02-decisions.md`) |
| GET | `documents/{id}/` | document under review |
| GET, PATCH | `documents/{id}/transactions/` | correct extracted lines |
| POST | `documents/{id}/review/` | submit review notes, release |

### Dashboard — `/api/v1/dashboard/`

Read-only aggregates, scoped to the caller's firm. Rewritten as ORM aggregates —
the current raw SQL uses MySQL's `ELT()`, which does not exist in Postgres.

### Files

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/files/{token}/` | authenticated file access — streams (local) or 302s to a signed URL (GCS) |

## Document status lifecycle

```
pending → uploaded → extracting → extracted
                                    ├→ pending_review → in_review → reviewed ─┐
                                    └──────────────────────────────────────────┤
                                                                               ↓
                                                        classifying → classified → verified
```

`failed` is reachable from any processing state and carries an error message.
`pending_review` is entered automatically when control totals do not balance.

## Enumerations

| Enum | Values |
|---|---|
| `FirmMembership.role` | `owner`, `accountant`, `reviewer` |
| `DocumentSource.document_type` | `bank_statement`, `credit_card`, `check_register`, `payroll`, `sales`, `misc` |
| `ExtractionField.direction` | `debit`, `credit` |
| `JournalTemplate.frequency` | `monthly`, `quarterly`, `annual`, `adhoc` |
| `AccountingPeriod.status` | `initiated`, `in_progress`, `completed`, `failed` |
| `PeriodDocument.status` | see lifecycle above |
