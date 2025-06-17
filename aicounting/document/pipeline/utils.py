
import io
from pypdf import (
    PdfReader,
    PdfWriter
)

def split_pdf_to_pages(pdf_bytes: bytes):
    """Splits a PDF file into individual pages and returns a list of bytes for each page."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    num_pages = len(reader.pages)
    page_bytes = []

    for page_num in range(num_pages):
        writer = PdfWriter()
        writer.add_page(reader.pages[page_num])
        
        with io.BytesIO() as output_stream:
            writer.write(output_stream)
            page_bytes.append(output_stream.getvalue())
    
    return page_bytes