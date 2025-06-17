import os
import json
from pathlib import Path
from celery import shared_task
from document.models.dim_aic_doc_model import (
    DimAICDocument,
    FactAICDocKeyItem,
    FactAICDocLine,
    FactAICDocLineItem
)
from pipeline.processor.ai_process import DocumentProcessor
from pipeline.prompter import Configuration

@shared_task
def process_uploaded_document(file_path: str, doc_id: int):
    file = Path(file_path)
    if not file.exists():
        return

    try:
        doc = DimAICDocument.objects.get(doc_id=doc_id)

        config = Configuration(
            doc_type=doc.doc_typ,
            extract_key_items=True,
            key_items=[],
            extract_line_items=True,
            line_items=[],
            excluded_fields=[]
        )
        processor = DocumentProcessor(config=config)
        mime_type = "application/pdf"
        with open(file, "rb") as f:
            pdf_bytes = f.read()

        result = processor.process_document(pdf_bytes, mime_type)

        # Save JSON output
        out_path = file.parent / "extracted_output.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        # Insert Key Items
        for item in result.get("key_items", []):
            FactAICDocKeyItem.objects.create(
                doc=doc,
                key=item["key"],
                value=item["value"],
                page_number=item.get("page", 1)
            )

        # Insert Line Items
        for line in result.get("line_items", []):
            line_obj = FactAICDocLine.objects.create(
                doc=doc,
                line_number=line.get("line_number", 0),
                page_number=line.get("page", 1)
            )
            for k, v in line["columns"].items():
                FactAICDocLineValue.objects.create(
                    line=line_obj,
                    key=k,
                    value=v
                )

        # Update doc status
        doc.upload_stat = "processed"
        doc.save()

    except Exception as e:
        if doc:
            doc.upload_stat = f"error: {str(e)}"
            doc.save()
        raise
