from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

# Locate the project root
project_root = Path(__file__).resolve().parent.parent
pdf_path = project_root / "data" / "Module_1_full_merged.pdf"

# Load PDF
loader = PyPDFLoader(str(pdf_path))
documents = loader.load()

# Split into chunks
splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=150
)

chunks = splitter.split_documents(documents)

print(f"Created {len(chunks)} chunks")

# Load embedding model
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# Generate embedding for the first chunk
vector = embeddings.embed_query(chunks[0].page_content)

print("Embedding length:", len(vector))
print("First 10 values:", vector[:10])