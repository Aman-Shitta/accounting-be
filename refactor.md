# Simplify Document Processing Flow

## Problem

The current flow between API upload and pipeline execution has **too many intermediary layers**:

```
API View → DocumentProcessingService → Celery task (process_uploaded_document)
  → DocumentConfig.from_dict() → DocumentConfig.to_configuration() → Configuration
    → MonthlyAccountingDocumentProcessor(doc, config) 
      → processor.set_doc_processor(doc_type)  
        → _register_default_processors() → ProcessorRegistry.get(doc_type)
          → ProcessorClass(config, doc)  [BaseDocumentProcessor.__init__]
            → GeminiMixin.init_gemini()  ← unnecessary for Claude/LandingAI
      → processor.start_process(file_bytes)
        → doc_processor.process_document(file_bytes)  ← ACTUAL WORK
```

**7 layers** between the API call and the actual pipeline running. The intermediary classes exist mainly to:
- Build a `Configuration` object (only used by Gemini pipelines for prompt-building)
- Wrap the pipeline in a `MonthlyAccountingDocumentProcessor` that just calls `.process_document()`
- Route to a pipeline via `ProcessorRegistry` (which is just a dict lookup)

## Goal: Simple 4-Step Flow

```
1. API gets file upload
2. Start Celery task with (doc_id) only
3. Pipeline runs (selected by doc_type mapping) — handles extraction + saving
4. Classification task runs
```

## Proposed Architecture

### New Flow

```
API View → Celery task (process_document_task)
  → resolve_pipeline(doc) → PipelineClass(doc)  
    → pipeline.process_document(file_bytes)  ← ACTUAL WORK
      → validation_task → classification_task
```

**3 layers** total. The Celery task itself handles:
- Fetching the document and file bytes from storage
- Resolving which pipeline to use
- Setting up debug storage
- Clearing old data
- Calling the pipeline
- Updating document status

---

## User Review Required

> [!IMPORTANT]
> **Breaking Changes**: The following files/classes will be deprecated and eventually removed:
> - `extractor/services.py` → `DocumentProcessingService` (replaced by direct Celery dispatch from view)
> - `extractor/processor.py` → `MonthlyAccountingDocumentProcessor` and `ProcessorRegistry` (logic moves into Celery task)
> - `extractor/config_factory.py` → `DocumentConfig`, `DocumentConfigFactory` (no longer needed — pipelines don't need this config object)
> - `extractor/protocol.py` → `ExtractionPipeline` protocol (pipelines just implement `process_document`)
> - `extractor/base.py` → `BaseDocumentProcessor` with GeminiMixin (will be cleaned up)
> - `extractor/prompter.py` → `Configuration` class (only Gemini pipelines use prompts — they can build them internally)

> [!WARNING]
> **Pipeline `__init__` signature change**: Currently pipelines take `(config, doc)`. New signature will be just `(doc)`. Gemini pipelines that need prompts will build `Configuration` internally from `doc.doc_type`.

> [!IMPORTANT]
> **Config serialization removed**: Currently `DocumentConfig` is serialized to dict and passed through Celery. In the new flow, only `doc_id` is passed to Celery (the task fetches everything it needs from the DB).

---

## Proposed Changes

### Component: Pipeline Base Classes

#### [MODIFY] [base.py](file:///Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/extractor/base.py)

**Remove GeminiMixin** from `BaseDocumentProcessor`. The class becomes a simple ABC with shared utilities:

```python
class BaseDocumentProcessor(AbstractDocumentProcessor):
    """Base processor with shared utilities. No AI provider coupling."""
    
    def __init__(self, doc: MonthlyAccountingDocument):
        self.document = doc
        self.debug_storage = None
    
    # Keep: parse_amount(), format_date(), truncate_decimal_to_2_places()
    # Keep: set_debug_storage()
    # Remove: init_gemini(), ai_client, _generate_content_stream()
    # Remove: class-level api_key, model
```

Add a `GeminiDocumentProcessor` subclass for Gemini-based pipelines:

```python
class GeminiDocumentProcessor(GeminiMixin, BaseDocumentProcessor):
    """Base for pipelines that need Gemini AI."""
    
    def __init__(self, doc):
        super().__init__(doc)
        self.init_gemini()
        self.ai_client = self.gemini_client
    
    # Keep: _generate_content_stream()
```

---

### Component: Pipeline Registry (New — simple mapping)

#### [NEW] [extractor/pipeline_registry.py](file:///Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/extractor/pipeline_registry.py)

A simple, flat mapping function replacing `ProcessorRegistry`, `DocumentConfigFactory`, and `_register_default_processors`:

```python
def get_pipeline_class(doc_type: str) -> Type[BaseDocumentProcessor]:
    """
    Resolve the pipeline class for a document type.
    Single source of truth for pipeline routing.
    """
    PIPELINE_MAP = {
        "bank_statement": "extractor.pipelines.landing_ai.pipeline.ExtractorPipeline",
        "credit_card": "extractor.pipelines.landing_ai.pipeline.ExtractorPipeline",
        "sales": "extractor.pipelines.kv.landing_pipeline.DocumentProcessor",
        "payroll": "extractor.pipelines.kv.landing_pipeline.DocumentProcessor",
        "misc": "extractor.pipelines.kv.landing_pipeline.DocumentProcessor",
    }
    ...
```

To switch providers (e.g., use Claude instead of Landing AI for bank statements), you just change one line in this mapping. No more commenting/uncommenting imports in `processor.py`.

---

### Component: Celery Task (Simplified)

#### [MODIFY] [account/tasks.py](file:///Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/account/tasks.py)

Replace `process_uploaded_document` task. The new task takes only `doc_id`:

```python
@shared_task
def process_document_task(doc_id: str):
    """
    Process a document. This is the single Celery entry point.
    
    1. Fetch doc + file from storage
    2. Resolve pipeline by doc_type
    3. Run pipeline (extraction + saving)
    4. Update status
    """
    doc = MonthlyAccountingDocument.objects.get(id=doc_id)
    file_bytes = read_file_from_storage(doc)
    
    # Clear existing data
    clear_existing_data(doc)
    
    # Resolve and instantiate pipeline
    PipelineClass = get_pipeline_class(doc.doc_type)
    pipeline = PipelineClass(doc)
    
    # Setup debug storage
    debug_storage = DocumentDebugStorage(doc)
    pipeline.set_debug_storage(debug_storage)
    
    # Run extraction
    result = pipeline.process_document(file_bytes)
    
    doc.status = "extracted"
    doc.save()
    
    return result
```

The `validate_control_totals_task` and `enqueue_classification_task` stay as-is — they're already clean.

---

### Component: API View

#### [MODIFY] [monthly_accounting_views.py](file:///Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/account/accounting/monthly_accounting_views.py)

Replace `DocumentProcessingService` with direct Celery dispatch:

```python
# Before (lines 653-655):
service = DocumentProcessingService(document)
task_id = service.process_document()

# After:
from account.tasks import process_document_task, validate_control_totals_task
task_chain = chain(
    process_document_task.s(str(document.id)),
    validate_control_totals_task.s(document_id=str(document.id))
)
result = task_chain.apply_async()
task_id = result.id
```

---

### Component: Pipeline `__init__` Cleanup

#### [MODIFY] [claude/pipeline.py](file:///Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/extractor/pipelines/claude/pipeline.py)

```python
# Before:
def __init__(self, config: Configuration, doc: MonthlyAccountingDocument):
    super().__init__(config, doc)

# After:
def __init__(self, doc: MonthlyAccountingDocument):
    super().__init__(doc)
```

No more `config` parameter — Claude pipeline never used `Configuration` for anything meaningful (it has its own prompts hardcoded).

#### [MODIFY] [landing_ai/pipeline.py](file:///Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/extractor/pipelines/landing_ai/pipeline.py)

Same change — Landing AI pipeline never uses `Configuration` either.

#### [MODIFY] [kv/landing_pipeline.py](file:///Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/extractor/pipelines/kv/landing_pipeline.py)

Same change.

#### [MODIFY] [gemini/pipeline.py](file:///Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/extractor/pipelines/gemini/pipeline.py)

Change base class to `GeminiDocumentProcessor` and build `Configuration` internally:

```python
class DocumentProcessor(GeminiDocumentProcessor):
    def __init__(self, doc: MonthlyAccountingDocument):
        super().__init__(doc)
        # Build prompt internally — this is the ONLY pipeline that needs it
        from extractor.prompter import Configuration, prepare_prompt
        config = Configuration(doc_type=doc.doc_type, extract_line_items=True, ...)
        self.prompt = prepare_prompt(config)
```

#### [MODIFY] [kv/gemini_pipeline.py](file:///Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/extractor/pipelines/kv/gemini_pipeline.py)

Same pattern — change base to `GeminiDocumentProcessor`, build prompt internally.

---

### Component: Deprecate Intermediary Files

#### [DELETE] `extractor/services.py` → `DocumentProcessingService`
- Keep `GLClassificationService` — move it to its own file or into `extractor/classification/`

#### [DELETE] `extractor/processor.py` → `MonthlyAccountingDocumentProcessor`, `ProcessorRegistry`
- All logic moves to `process_document_task` in `account/tasks.py`

#### [DELETE] `extractor/config_factory.py` → `DocumentConfig`, `DocumentConfigFactory`
- `DocumentType` enum is still useful — move it to `extractor/constants.py` or keep inline

#### [DELETE] `extractor/protocol.py` → `ExtractionPipeline` protocol
- Unnecessary — `BaseDocumentProcessor` already defines the interface

---

### Component: Exports

#### [MODIFY] [extractor/__init__.py](file:///Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/extractor/__init__.py)

Clean up exports to reflect the simplified structure.

---

## Summary: Before vs After

| Concern | Before | After |
|---------|--------|-------|
| API → Celery | `DocumentProcessingService.process_document()` | Direct `chain(process_document_task.s(), ...)` |
| Config serialization | `DocumentConfig → dict → Celery → DocumentConfig → Configuration` | `doc_id → Celery → fetch doc from DB` |
| Pipeline routing | `ProcessorRegistry + _register_default_processors()` | `get_pipeline_class(doc_type)` — simple dict |
| Pipeline wrapper | `MonthlyAccountingDocumentProcessor.start_process()` | Gone — task calls `pipeline.process_document()` directly |
| Pipeline init | `PipelineClass(config, doc)` | `PipelineClass(doc)` |
| Gemini coupling | All pipelines inherit GeminiMixin | Only Gemini pipelines inherit `GeminiDocumentProcessor` |
| Files involved | `services.py`, `processor.py`, `config_factory.py`, `protocol.py`, `base.py`, `prompter.py` | `pipeline_registry.py`, `base.py`, `tasks.py` |

---

## Open Questions

> [!IMPORTANT]
> 1. **`GLClassificationService`** currently lives in `services.py`. Should I move it to `extractor/classification/service.py` or keep it in `services.py` (just remove `DocumentProcessingService` from that file)? yes

> [!IMPORTANT]
> 2. **`DocumentType` enum** — currently in `config_factory.py`. It's used by `tasks.py` to determine if a doc is "transactional" vs "attribute" (to decide if control-total validation runs). Should I move it to a standalone `extractor/constants.py`? okay

> [!IMPORTANT]
> 3. **Gemini pipeline**: The old `DocumentProcessor` in `gemini/pipeline.py` has its own save-to-DB logic (not using `BankStatementSaver`). Should I also update it to use `BankStatementSaver` during this refactor, or leave that for a separate task? Yes

---

## Verification Plan

### Automated Tests
- `python manage.py check` — verify no import errors
- Grep for all deleted class references to ensure no dangling imports
- Trace the full flow from API → Celery → Pipeline for each doc type

### Manual Verification
- Upload a bank statement → verify Landing AI pipeline runs
- Upload a sales doc → verify KV Landing pipeline runs
- Confirm classification still chains correctly after extraction
