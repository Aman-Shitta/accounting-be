import os
import json
import traceback
from pathlib import Path
from ai_process_new import DocumentProcessor
from utils import prepare_prompt

MIME_TYPES = {
    "PDF": "application/pdf",
}

def read_pdf_bytes(file_path: Path) -> bytes:
    with open(file_path, "rb") as f:
        return f.read()


def save_output(output_data, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file_json = out_dir / "out_3_no_error.json"
    out_file_txt = out_dir / "out_3_no_error.txt"

    try:
        with open(out_file_json, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)
        print(f"Saved JSON result to: {out_file_json}")
    except Exception  as e:
        # Fallback: Save as plain text
        with open(out_file_txt, "w", encoding="utf-8") as f:
            f.write(str(output_data))
        print(f"Could not save as JSON, saved as text: {out_file_txt}")
        print(f"JSON Error: {e}")


def process_single_file(file_path: Path, processor: DocumentProcessor):
    print(f"\nProcessing file: {file_path}")
    try:
        if file_path.suffix.lower() == ".pdf":
            mime_type = MIME_TYPES.get("PDF")
            pdf_bytes = read_pdf_bytes(file_path)
        # elif file_path.suffix.lower() in ["jpg", "jpeg", "png"]: 
        #     pdf_bytes = convert_image_to_pdf(file_path)
        else:
            mime_type
            raise ValueError(f"Document type {file_path.suffix} not supported")

        result = processor.process_document(pdf_bytes, mime_type)

        output_folder = file_path.stem  # name without extension
        output_path = file_path.parent / output_folder
        save_output(result, output_path)

    except Exception as e:
        print(f"Error processing {file_path.name}: {e}")
        traceback.print_exc()


def process_all_pdfs_in_folder(folder_path: Path, processor: DocumentProcessor):
    for file in folder_path.iterdir():
        if file.is_file() and file.suffix.lower() in [".pdf"]:
            process_single_file(file, processor)


if __name__ == "__main__":
    folder_path = Path(r"C:\Users\Aman\Zygoon\AICounting - Test Files\Bank Statements")

    prompt = prepare_prompt()
    processor = DocumentProcessor(
        key="",
        prompt=prompt
    )

    process_all_pdfs_in_folder(folder_path, processor)