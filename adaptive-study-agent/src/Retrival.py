from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# Project paths
project_root = Path(__file__).resolve().parent.parent
db_path = project_root / "chroma_db"

# Load embedding model
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# Load existing Chroma database
vectorstore = Chroma(
    persist_directory=str(db_path),
    embedding_function=embeddings
)

# Create retriever
retriever = vectorstore.as_retriever(search_kwargs={"k": 8})

question = input("Enter your question: ")

docs = retriever.invoke(question)

print(f"\nRetrieved {len(docs)} chunks\n")

for i, doc in enumerate(docs, start=1):
    print("=" * 60)
    print(f"Chunk {i}")
    print("=" * 60)
    print(doc.page_content[:500])   # print first 500 characters
    print()