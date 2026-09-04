"""
Pipeline routing: resolves a pipeline class for a document's extraction mode.

Routing is keyed by *mode* — ``"transactional"`` or ``"fields"`` — not by
document category. Categories are configuration (see
``v1.configuration.models.DocumentCategory``); a firm can add "1099-NEC" or
"rent roll" without a deploy, but there are still only two things a pipeline
can produce, and that's what decides which one runs.

To route one specific category through a different provider (a client whose
statements one backend handles badly, say), that's a per-category provider
override — a real feature, not yet built. Today the choice is fleet-wide per
mode, which is what this map expresses.
"""

import importlib


class UnsupportedDocTypeError(Exception):
    """Raised when no pipeline is mapped for an extraction mode."""
    pass


PIPELINE_MAP: dict[str, str] = {
    # Emits line items.
    "transactional": "extractor.pipelines.datalabs.pipeline.ExtractorPipeline",
    # Emits values for configured fields.
    "fields": "extractor.pipelines.kv.landing_pipeline.DocumentProcessor",
}


def get_pipeline_class(extraction_mode: str) -> type:
    """
    Resolve the pipeline class for an extraction mode.

    Imports lazily via dotted path to avoid circular imports between
    pipelines and shared base classes.
    """
    dotted_path = PIPELINE_MAP.get(extraction_mode)

    if not dotted_path:
        raise UnsupportedDocTypeError(
            f"No pipeline registered for extraction mode '{extraction_mode}'. "
            f"Available: {list(PIPELINE_MAP.keys())}"
        )
    module_path, _, class_name = dotted_path.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)
