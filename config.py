"""
Configuration constants for the Research Assistant.
"""
import os

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")

# Collection name for ChromaDB
COLLECTION_NAME = "research_papers"

# Embedding model
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Ollama configuration
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"

# Chunking parameters
CHUNK_SIZE = 800          # ~200 tokens (4 chars per token approx)
CHUNK_OVERLAP = 120       # ~30 tokens overlap

# Retrieval parameters
TOP_K = 3  # Number of chunks to retrieve per query

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CHROMA_DIR, exist_ok=True)