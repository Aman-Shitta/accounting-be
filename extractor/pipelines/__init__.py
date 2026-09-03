"""
Extraction Pipelines

Provider-based pipeline implementations. Each subfolder represents a
different extraction backend (LandingAI, Gemini, Claude, etc.).

To add a new extraction provider:
    1. Create ``extractor/pipelines/your_provider/``
    2. Add ``pipeline.py`` implementing ``BaseDocumentProcessor.process_document()``
    3. Map your doc_type(s) to the new class in ``extractor.pipeline_registry.PIPELINE_MAP``
"""
