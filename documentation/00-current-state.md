# Current state — as of 2026-09-03

A factual record of what the system does today and where it is broken, taken
from the `development` branch at commit `003ff9a`. This is the baseline the v1
rebuild is measured against.

## What the product does

A CPA firm signs up, onboards its own clients, and for each client configures:

1. A **chart of accounts** (`dim_aic_gl_acct`), typically imported from a
   client-supplied COA document.
2. One or more **input files** (`dim_aic_input_files`) — a recurring source of
   documents, e.g. "Chase Operating ...1234" (bank statement) or "ADP Payroll".
3. For non-bank sources, a set of **attributes** (`dim_aic_input_file_attributes`)
   naming what to pull out of the document, each mapped to a GL account and an
   offset GL account.
4. **JE templates** (`dim_aic_je_template_header` + `_attribute`) describing the
   journal entry to produce.

Each month the firm opens a **monthly accounting session**
(`fact_aic_monthly_accounting`), uploads one document per configured input file,
and the system extracts, classifies and produces journal entries.

## Processing flow

```
POST upload → process_document_task (celery)
  → get_pipeline_class(doc_type)
      bank_statement, credit_card → Datalabs pipeline
      sales, payroll, misc        → LandingAI KV pipeline
  → pipeline.process_document(bytes)   [extract + persist]
  → validate_control_totals_task       [assigns reviewer on mismatch]
  → enqueue_classification_task        → ClassificationQueue
  → process_classification_queue_task  [celery beat, 60s, one per client]
      → GLClassificationService → OpenAI Responses API + per-client vector store
```

The Datalabs pipeline runs Marker parse + page segmentation in one call, then
three Gemini calls (transactions from HTML tables, control totals from text,
check-image OCR), merges, and saves via `BankStatementSaver`.

The KV pipeline builds a Pydantic model **dynamically from the configured
attributes** (`build_dynamic_extraction_model`), page by page, dropping fields
from the schema as they are found.

## Stack

| | |
|---|---|
| Django | 5.2.1 + DRF 3.16 |
| DB | MySQL via `mysqlclient`, credentials in `mysql.cnf` |
| Queue | Celery 5.5 + Redis |
| Storage | Azure Blob via `django-storages`, SAS URLs |
| Auth | Azure AD SSO via MSAL, JWT bearer tokens |
| LLM | Gemini (extraction), OpenAI (classification), Anthropic (unused paths), LandingAI ADE, Datalabs |

## Apps

`account` (accounting domain, 34 models/views files), `user` (firms, clients,
accountants, reviewers), `authentication` (Azure SSO), `dashboard` (raw-SQL
aggregates), `extractor` (not a Django app — a plain package).

## Problems

### Tenancy is convention, not structure

There is no tenant column and no central scoping helper. Every view re-derives
the tenant inline:

```python
if hasattr(user, 'customer_profile'):
    return Model.objects.filter(client__customer=user.customer_profile)
elif hasattr(user, 'accountant_profile'):
    return Model.objects.filter(client__customer=accountant.customer,
                                client__assigned_accountants=accountant)
return Model.objects.none()
```

**177 occurrences across 14 files.** Any view that forgets the branch leaks data
across firms, and nothing in the schema or the test suite would catch it.

Two constraints actively prevent multi-tenancy:

- `DimAicInputFiles.name` is `unique=True` **globally** — two firms cannot both
  have an input file called "Operating Account".
- `DimAICClient.client_id` is `unique=True` **globally** — two firms cannot both
  use the client code "ACME".

`DimAICReviewer` has no firm at all; `get_next_reviewer()` round-robins over
every verified reviewer on the platform, so a reviewer is handed documents from
any firm.

`DimAICGLAcct` carries **both** `customer` and `client_id` FKs. They are set
independently and can disagree.

### Snapshots duplicate everything, including file bytes

`FactAICMonthlyAccounting.create_monthly_accounting_with_snapshots` copies the
entire configuration into four parallel tables on every period open:

| Snapshot table | Mirrors |
|---|---|
| `fact_aic_input_file_snapshot` | `dim_aic_input_files` |
| `fact_aic_input_file_attribute_snapshot` | `dim_aic_input_file_attributes` |
| `fact_aic_je_template_header_snapshot` | `dim_aic_je_template_header` |
| `fact_aic_je_template_attribute_snapshot` | `dim_aic_je_template_attribute` |

Worse, `_create_input_file_snapshot` reads each source file out of blob storage
and writes a **byte-for-byte copy** back under a new key. Row count and blob
storage both grow linearly with months × clients × configured sources, for data
that never changes after it is written.

Extracted rows then point at snapshot rows
(`MonthlyDocumentAttributeItem.attribute → FactAICInputFileAttributeSnapshot`),
so the snapshots can never be pruned.

### Half the extractor is unreachable

`extractor/pipeline_registry.py` wires only two routes. Unreferenced from any
live path:

| Dead | Lines |
|---|---|
| `extractor/rectifier/` (rectify.py + utils.py) | 2,212 |
| `extractor/pipelines/gemini/` | 1,095 |
| `extractor/pipelines/claude/` | 356 |
| `extractor/pipelines/landing_ai/` | 319 |
| `extractor/pipelines/kv/gemini_pipeline.py` | 132 |
| `extractor/prompter.py`, `extractor/statement_models.py` | 382 |
| `user/manual_tool.py` | 337 |

`extractor/rectifier/rectify.py` is the **only** consumer of Google Document AI.

### Naming

The `Dim*`/`Fact*` prefixes imply a star schema that does not exist — these are
plain OLTP tables. The names actively mislead: `DimAICCustomer` is a CPA firm,
`DimAicInputFiles` is a configured document source (not a file), and
`FactAICMonthlyAccounting` is an accounting period. Table names (`customer`,
`client`, `accountant`, `assistant`, `contact`) are generic enough to collide
with anything.

### Live bugs

- **Migration `0030_remove_zombie_models`** issues `DeleteModel` for
  `ClassificationQueue` and `MonthlyDocumentBankKeyItem`, both still imported and
  used by `account/tasks.py`, plus three models still defined and registered in
  `account/admin.py`. Applying it breaks the classification queue; leaving it
  unapplied leaves `makemigrations` permanently dirty.
- **`anthropic` is missing from `requirements.txt`** but imported at module scope
  by `extractor/pipelines/datalabs/backends.py`, which is the only wired
  bank-statement pipeline. A clean install cannot import it.
- **`CORS_ALLOW_ALL_ORIGINS = True` with `CORS_ALLOW_CREDENTIALS = True`** —
  browsers reject that combination, and it is wide open regardless.
- **`requirements.txt` is UTF-16 encoded**, so git treats it as a binary blob and
  diffs are unreadable.
- `FactAICMonthlyAccounting.clean()` enforces one period per client/month/year,
  but DRF never calls `clean()`, so there is no actual constraint.
- 178 bare `except Exception` blocks convert real errors into 500s with a
  stringified traceback in the log.

### Secrets in the working tree

Four untracked files carried credentials: a live GCP service-account private key
(`aicounting-2025v1-*.json`), and the MySQL production password in plaintext in
both `mysql.cnf.prod` and `.prod.dep.md`. All four are now gitignored; the
password dies with the MySQL migration, and the GCP key should be rotated.

## Dead columns left behind by Phase 1

Deleting the rectifier orphaned five columns on `monthly_document_line_item`:
`is_rectified`, `was_missing`, `was_compared`, `rectified_confidence`,
`rectification_reasoning`. The Datalabs pipeline never emits them, so
`BankStatementSaver` writes the defaults on every row and the serializers return
`False`/`None` unconditionally. They are dropped with the rest of the schema in
Phase 3 rather than in a separate migration against a database that is about to
be discarded.

The same applies to the `05_document_ai` and `06_rectification` artifact stages
in `aicounting/azure_storage_paths.py` and the `save_rectified_data` /
`save_rectifier_items` helpers in `aicounting/file_upload_helper.py` — both
modules are rewritten wholesale in Phase 2.
