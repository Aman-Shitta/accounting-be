from django.conf import settings
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

    doc = None
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
        
        breakpoint()
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

                # create empty key for gl ref
                FactAICDocLineItem.objects.create(
                    line=line_obj,
                    key="gl_account",
                    value="N/A"
                )

                FactAICDocLineItem.objects.create(
                    line=line_obj,
                    key="gl_account_desc",
                    value="N/A"
                )

        # Update doc status
        doc.upload_stat = "extracted"
        doc.save()

        classified_pages_data = classify_document(doc_id)


        for page_num, classified_data in classified_pages_data.items():
            for line_item in classified_data:
                line_num = line_item.get("id")
                gl_account = line_item.get("gl_account")
                gl_account_desc = line_item.get("gl_account_desc")

                line_obj = FactAICDocLine.objects.filter(
                    doc=doc,
                    line_number=int(line_num),
                    page_number=int(page_num)
                ).first()

                FactAICDocLineItem.objects.update_or_create(
                    line=line_obj,
                    key="gl_account",
                    defaults={"value": gl_account}
                )

                FactAICDocLineItem.objects.update_or_create(
                    line=line_obj,
                    key="gl_account_desc",
                    defaults={"value": gl_account_desc}
                )

        # Update doc status
        doc.upload_stat = "classified"
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
            api_key=settings.OPENAI_API_KEY, 
            assistant_id="asst_kU6Jl2GsjwGUu3Qof5IkxnIh",
            vector_store_ids=["vs_6862ae7e625c81918ece89a316d1861b"]
        )
        classified_data = classifier_assistant.classify(doc_id)
        return classified_data

    except Exception as e:
        print("Error: ",  {str(e)})
        import os, sys
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        print(exc_type, fname, exc_tb.tb_lineno)
