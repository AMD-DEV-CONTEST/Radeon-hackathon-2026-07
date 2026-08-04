"""CLI wrapper to build the RAG index. Run once before first agent run."""
from src.rag.ingest import build_index

if __name__ == "__main__":
    build_index()
    print("RAG index built.")
