from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Get project root (adaptive-study-agent)
project_root = Path(__file__).resolve().parent.parent

pdf_path = project_root / "data" / "Module_1_full_merged.pdf"

print("PDF Path:", pdf_path)
print("Exists:", pdf_path.exists())

loader = PyPDFLoader(str(pdf_path))
documents = loader.load()

print(f"Loaded {len(documents)} pages")

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=150
)

chunks = text_splitter.split_documents(documents)

print(f"Created {len(chunks)} chunks")
print("\nFirst chunk:\n")
print(chunks[0].page_content)