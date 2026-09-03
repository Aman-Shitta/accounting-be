# API v1 contract

The `/api/v1/` surface as built. This is the handoff to the React /
React Native client — it should be the only thing that client needs.

All responses are JSON. Everything except `auth/login`, `auth/refresh`,
`auth/set-password` and `auth/forgot-password` requires
`Authorization: Bearer <access token>`.

## Conventions

**Envelope.** Every response has the same shape:

```json
{ "status": "success", "status_code": 200, "message": "OK.", "data": { } }
```

```json
{ "status": "error", "status_code": 400, "message": "Validation failed.",
  "errors": { "external_ref": ["Your firm already has a client with the reference 'REF1'."] } }
```

**Errors.** One handler covers the whole API. Validation → 400 with `errors`
populated. Missing permission → 403. A row that does not exist, *or belongs to
another firm* → 404: existence never leaks across tenants. A server fault → 500
with a generic message; the traceback goes to the log, never to the client.

**Pagination.** Limit/offset on every list, default page size 50:
`?limit=&offset=`. Lists return `{"count", "next", "previous", "results"}`
inside `data`.

**Search and ordering.** `?search=` and `?ordering=` where a view declares
`search_fields` — clients (name, reference), ledger accounts (number, name),
document sources (name).

**Throttling.** 60/min authenticated, 30/min anonymous. `auth/login` is
10/min and `auth/set-password` / `auth/forgot-password` 5/min.

**IDs.** Integer primary keys. `client.external_ref` is the firm's own code and
is unique *per firm*, never globally.

---

## Auth — `/api/v1/auth/`

There is no self-service signup. A firm owner invites by email; the invitee
receives a link and chooses a password.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `login/` | `{email, password}` | `{access, refresh}` |
| POST | `refresh/` | `{refresh}` | `{access}` |
| POST | `set-password/` | `{token, password}` | `{access, refresh}` |
| POST | `forgot-password/` | `{email}` | — |
| GET | `me/` | | identity, roles, reachable client count |
| POST | `invite/` | `{email, role, first_name?, last_name?}` | the new membership |

`role` is `owner`, `accountant` or `reviewer`.

**Invite flow.** `POST auth/invite/` → the invitee gets an email containing
`{APP_BASE_URL}/set-password?token=…` → the client reads `token` off the query
string and posts it with a chosen password → the response carries a token pair,
so the user lands signed in. Invite links last 48 hours, reset links 1 hour, and
both are single-use.

**Login and forgot-password answer identically whether or not the account
exists.** Do not build UI that infers otherwise.

---

## Firm — `/api/v1/firm/`

| Method | Path | Notes |
|---|---|---|
| GET | `` | the caller's firm, with `client_count` |
| PATCH | `` | owners only |
| GET | `members/` | the roster |
| GET | `members/{id}/` | |
| DELETE | `members/{id}/` | deactivates; owners only, and not yourself |

---

## Clients — `/api/v1/clients/`

| Method | Path | Notes |
|---|---|---|
| GET, POST | `` | list / onboard |
| GET, PATCH, DELETE | `{id}/` | DELETE is a soft delete |

`external_ref` must be unique within the firm. Two different firms may both use
`ACME`.

### Under a client — `/api/v1/clients/{client_id}/`

| Path | Methods | Notes |
|---|---|---|
| `contacts/` | list, create, detail, update, delete | |
| `reference-documents/` | list, create, detail, delete | multipart; `kind` is `chart_of_accounts`, `vendor_list` or `gl_history` |
| `assignments/` | list, create, delete | which members may work on this client; owners only to create |
| `ledger-accounts/` | list, create, detail, update, delete | chart of accounts |
| `document-sources/` | list, create, detail, update, delete | |
| `document-sources/{id}/fields/` | GET, PUT | extraction fields |
| `journal-templates/` | list, create, detail, update, delete | |
| `journal-templates/{id}/lines/` | GET, PUT | |
| `config/` | GET | version history, without payloads |
| `config/{id}/` | GET | one version, with payload |
| `config/publish/` | POST | freeze current config as a new version |
| `config/current/` | GET | the latest version |
| `config/check/` | GET | `{publishable, problems[]}` |
| `periods/` | GET, POST | list / open a month |
| `periods/{id}/` | GET, DELETE | DELETE is a soft delete, freeing the month |
| `periods/years/` | GET | years with periods, for a picker |

---

## Document types

The split the UI has to respect. `document_source.is_transactional` is returned
on every source so the client does not have to hardcode the list.

### Transactional — `bank_statement`, `credit_card`, `check_register`

The document *is* a list of transactions; there is nothing to name in advance.

- **No extraction fields.** `PUT .../fields/` returns 400.
- Configure `ledger_account` (the account the statement represents) and
  `default_offset_account`.
- Extraction produces **transactions**, and the classifier assigns a ledger
  account per transaction.

### Field-configured — `payroll`, `sales`, `misc`

- **At least one extraction field is required**, or publishing is refused.
- Each field: `key` (slug, used in the extraction schema), `label`,
  `prompt_hint` (what to tell the extractor to look for), `direction`
  (`debit`/`credit`), `ledger_account`, `offset_ledger_account`, `position`.
- Extraction produces **field values** — one per configured field, including
  the ones it could not find, so the UI can show the gap.

`PUT .../fields/` replaces the whole set; the extraction schema is built from
all of them at once, so partial edits do not make sense.

---

## Configuration versioning

`POST config/publish/` freezes the client's sources, fields, templates and
lines into an immutable version. **Opening a period pins the version current at
that moment**, so editing configuration afterwards does not change a month
already in progress.

Publishing is refused, with reasons in `errors.configuration`, when:

- no document sources are configured
- a field-configured source has no fields
- a transactional source has fields, or no ledger account

`GET config/check/` returns the same list without attempting a publish — use it
to disable the publish button and show what is missing.

Opening a period with no published version publishes one automatically, so
onboarding is a single action.

---

## Periods — `/api/v1/periods/{period_id}/`

| Path | Methods | Notes |
|---|---|---|
| `documents/` | GET | one slot per configured source |
| `documents/{id}/` | GET, PATCH | |
| `documents/{id}/upload/` | POST | multipart `file`; 202 with `task_id` |
| `documents/{id}/config/` | GET | the **frozen** config for this document's source |
| `documents/{id}/verify/` | POST | mark verified |

`documents/{id}/config/` is what a UI should render the extraction form from —
not the client's live configuration, which may have moved on.

Uploading replaces any previous extraction for that document rather than adding
to it.

### Extracted rows — `/api/v1/documents/{document_id}/`

| Path | Methods | Notes |
|---|---|---|
| `transactions/` | list, create, detail, update, delete | transactional documents |
| `check-details/` | list, create, detail, update, delete | payee/memo from check images |
| `field-values/` | GET, PATCH | field-configured documents; rows are created by the pipeline |

Setting `ledger_account` on a transaction marks it `is_manually_classified`, so
a later classification pass leaves it alone.

---

## Review — `/api/v1/review/`

Reviewers only. A document arrives here when its control totals do not balance
and the client has `allow_review` set.

| Method | Path | Notes |
|---|---|---|
| GET | `documents/` | the caller's queue |
| GET | `documents/{id}/` | |
| POST | `documents/{id}/claim/` | → `in_review` |
| POST | `documents/{id}/submit/` | `{notes, approved}`; approving sends it to classification |

> Reviewers are platform-level today and see documents across every firm. See
> `02-decisions.md` — this needs a product decision.

---

## Dashboard — `/api/v1/dashboard/`

Counts and recent activity scoped to what the caller can reach:
`totals`, `periods_by_status`, `documents_by_status`, `needs_attention`
(pending upload, failed, awaiting review) and `recent_periods`.

---

## Document status lifecycle

```
pending → uploaded → extracting → extracted
                                    ├→ pending_review → in_review → reviewed ─┐
                                    └──────────────────────────────────────────┤
                                                                               ↓
                                                        classifying → classified → verified
```

`failed` is reachable from any processing state and carries `failure_reason`.
`pending_review` is entered automatically when control totals do not balance.

## Enumerations

| Enum | Values |
|---|---|
| `membership.role` | `owner`, `accountant`, `reviewer` |
| `document_source.document_type` | `bank_statement`, `credit_card`, `check_register`, `payroll`, `sales`, `misc` |
| `extraction_field.direction` | `debit`, `credit` |
| `journal_template.frequency` | `monthly`, `quarterly`, `annual`, `adhoc` |
| `journal_template_line.side` | `debit`, `credit` |
| `journal_template_line.amount_source` | `extracted_field`, `fixed`, `manual` |
| `accounting_period.status` | `initiated`, `in_progress`, `completed`, `failed` |
| `ledger_account.account_class` | `asset`, `liability`, `equity`, `revenue`, `expense` |
| `period_document.status` | see lifecycle above |

## Getting a working environment

```sh
docker compose up -d
cp .env.example .env
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo      # a firm, a client, config, one period
.venv/bin/python manage.py runserver
```

`seed_demo` prints the credentials it creates. Email is written to the console
in development, so invite and reset links appear in the `runserver` output.
