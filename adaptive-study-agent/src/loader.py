from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader

# Get the project root directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Construct the PDF path
pdf_path = BASE_DIR / "data" / "Module_1_full_merged.pdf"

print("PDF path:", pdf_path)
print("Exists:", pdf_path.exists())

loader = PyPDFLoader(str(pdf_path))
docs = loader.load()

print(f"Loaded {len(docs)} pages.")