"""Build the vector index from MITRE ATT&CK + CVE data in data/knowledge_base/.

Run once via: python scripts/build_rag_index.py
"""
import os


def build_index(kb_dir: str = None, vector_db_path: str = None):
    kb_dir = kb_dir or os.getenv("KNOWLEDGE_BASE_DIR", "./data/knowledge_base")
    vector_db_path = vector_db_path or os.getenv("VECTOR_DB_PATH", "./data/vector_store")
    # TODO:
    # 1. load MITRE ATT&CK STIX bundle + CVE snippets from kb_dir
    # 2. chunk documents
    # 3. embed with sentence-transformers
    # 4. write to chromadb at vector_db_path
    raise NotImplementedError
