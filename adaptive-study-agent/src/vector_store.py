from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

# Project root
project_root = Path(__file__).resolve().parent.parent

pdf_path = project_root / "data" / "Module_1_full_merged.pdf"
db_path = project_root / "chroma_db"

# Load PDF
loader = PyPDFLoader(str(pdf_path))
documents = loader.load()

print(f"Loaded {len(documents)} pages")

# Split
splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=150
)

chunks = splitter.split_documents(documents)

print(f"Created {len(chunks)} chunks")

# Embedding model
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# Create Chroma database
vectorstore = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory=str(db_path)
)

print("✅ Chroma database created successfully!")
print(f"Stored {len(chunks)} chunks.")