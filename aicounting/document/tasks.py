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
from document.pipeline.processor.ai_process import DocumentProcessor
from document.pipeline.prompter import Configuration

from document.pipeline.classification import GLClassifier

@shared_task
def process_uploaded_document(file_path: str, doc_id: int):
    file = Path(file_path)
    if not file.exists():
        return

    try:
        doc = DimAICDocument.objects.get(doc_id=doc_id)

        config = Configuration(
            # TODO: make it come from confguration
            doc_type="bank_statement",
            extract_key_items=False,
            key_items=[],
            extract_line_items=True,
            line_items=[
                "date: The date of the transaction.", 
                "description: A description of the transaction.",
                "debit amount: The debit amount of the transaction.",
                "credit amount: The credit amount of the transaction.",
            ],
            excluded_fields=[]
        )
        processor = DocumentProcessor(config=config)
        mime_type = "application/pdf"
        with open(file, "rb") as f:
            pdf_bytes = f.read()

        result, control_totals = processor.process_document(pdf_bytes, mime_type)
        # TODO: save control totals in DB

        doc.control_item = control_totals
        # Save JSON output
        out_path = file.parent / "extracted_output.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        
        # Insert Key Items
        for idx, item in enumerate(result):
            page_key = f"page_{idx+1}"
            page_data = item.get(page_key, {})
            for key, val in page_data.get("key_items", {}):
                FactAICDocKeyItem.objects.create(
                    doc=doc,
                    key=key,
                    value=val,
                    page_number=idx
            )

            # Insert Line Items
            for line_idx, line_item in enumerate(page_data.get("line_items", [])):
                line_obj = FactAICDocLine.objects.create(
                    doc=doc,
                    line_number=line_idx,
                    page_number=idx
                )
                for k, v in line_item.items():
                    FactAICDocLineItem.objects.create(
                        line=line_obj,
                        key=k,
                        value=v
                    )

        # Update doc status
        doc.upload_stat = "processed"
        doc.save()

    except Exception as e:
        if doc:
            doc.upload_stat = f"failed"
            doc.save()
            print("Error: ",  {str(e)})
            import os, sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)
        raise



# @shared_task
def classify_document(doc_id: str):

    try:
        classifier_assistant = GLClassifier(
            api_key="sk-", 
            assistant_id="asst_9SbHYIoj1MnurVtE9UkoAWke",
            vector_store_ids=["vs_6862ae7e625c81918ece89a316d1861b"]
        )

        # document_id = "a2ac600b-5d1b-42cd-a34e-077a6b29a2d3"

        classifier_assistant.classify(doc_id)

    except Exception as e:
        print("Error: ",  {str(e)})
        import os, sys
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        print(exc_type, fname, exc_tb.tb_lineno)
