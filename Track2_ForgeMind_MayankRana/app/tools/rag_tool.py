"""
ForgeMind RAG Tool - Local codebase indexing with ChromaDB + BGE embeddings
Runs 100% on Radeon GPU via ROCm PyTorch
"""
import os
import pathlib
from typing import List, Dict
from app.models.embeddings import LocalEmbeddings

class CodebaseRAG:
    def __init__(self, workspace: str, persist_dir: str = ".forgemind_chroma"):
        self.workspace = pathlib.Path(workspace).resolve()
        self.persist_dir = self.workspace / persist_dir
        self.embedder = LocalEmbeddings()
        self.collection = None
        self._init_db()

    def _init_db(self):
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(self.persist_dir))
            self.collection = client.get_or_create_collection("codebase", metadata={"hnsw:space": "cosine"})
            print(f"[RAG] ChromaDB ready at {self.persist_dir}")
        except Exception as e:
            print(f"[RAG] ChromaDB init failed, using in-memory: {e}")
            self.collection = None
            self._memory_store = []  # fallback list of dicts

    def _chunk_file(self, file_path: pathlib.Path) -> List[Dict]:
        try:
            text = file_path.read_text(encoding='utf-8', errors='ignore')
            # Simple chunking by 500 chars with overlap - could use tree-sitter for AST
            chunks = []
            for i in range(0, len(text), 400):
                chunk = text[i:i+600]
                if len(chunk.strip()) > 50:
                    chunks.append({
                        "text": chunk,
                        "file": str(file_path.relative_to(self.workspace)),
                        "start": i
                    })
            return chunks[:20]  # limit per file
        except:
            return []

    def ingest(self) -> str:
        """Ingest entire codebase"""
        exts = {'.py', '.js', '.ts', '.java', '.md', '.json', '.yaml', '.toml'}
        all_chunks = []
        for p in self.workspace.rglob("*"):
            if p.is_file() and p.suffix in exts and "venv" not in str(p) and ".git" not in str(p) and ".forgemind" not in str(p):
                all_chunks.extend(self._chunk_file(p))
                if len(all_chunks) > 500:  # limit total
                    break

        if not all_chunks:
            return "No code files found to ingest"

        texts = [c["text"] for c in all_chunks]
        embeddings = self.embedder.embed(texts)

        if self.collection:
            ids = [f"chunk_{i}" for i in range(len(all_chunks))]
            metadatas = [{"file": c["file"], "start": c["start"]} for c in all_chunks]
            self.collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
        else:
            self._memory_store = [{"text": t, "embedding": e, "file": c["file"]} for t, e, c in zip(texts, embeddings, all_chunks)]

        return f"Ingested {len(all_chunks)} chunks from codebase into local vector DB (Radeon accelerated)"

    def query(self, question: str, k: int = 5) -> str:
        """Query codebase"""
        if not question:
            return "Empty query"

        q_emb = self.embedder.embed([question])[0]

        if self.collection and self.collection.count() > 0:
            results = self.collection.query(query_embeddings=[q_emb], n_results=k)
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            out = []
            for doc, meta in zip(docs, metas):
                out.append(f"--- File: {meta.get('file')} ---\n{doc[:800]}")
            return "\n\n".join(out)
        else:
            # Memory fallback - simple cosine similarity
            if not hasattr(self, '_memory_store') or not self._memory_store:
                return "Vector DB empty, run ingest first"
            import math
            def cosine(a,b):
                dot = sum(x*y for x,y in zip(a,b))
                na = math.sqrt(sum(x*x for x in a))
                nb = math.sqrt(sum(y*y for y in b))
                return dot/(na*nb+1e-9)
            scored = sorted(self._memory_store, key=lambda x: cosine(x["embedding"], q_emb), reverse=True)[:k]
            return "\n\n".join([f"--- File: {s['file']} ---\n{s['text'][:800]}" for s in scored])

# Global
_rag_instance = None
def get_rag(workspace: str):
    global _rag_instance
    if _rag_instance is None or str(_rag_instance.workspace) != str(pathlib.Path(workspace).resolve()):
        _rag_instance = CodebaseRAG(workspace)
    return _rag_instance
