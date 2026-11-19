from pypdf import PdfWriter, PdfReader
import fitz

def merge_pdfs(paths, output_path):
    writer = PdfWriter()
    for path in paths:
        reader = PdfReader(path)
        for page in reader.pages:
            writer.add_page(page)
    with open(output_path, "wb") as output:
        writer.write(output)

def compress_pdf(input_path, output_path):
    doc = fitz.open(input_path)
    doc.save(output_path, garbage=4, deflate=True, clean=True)
    doc.close()
