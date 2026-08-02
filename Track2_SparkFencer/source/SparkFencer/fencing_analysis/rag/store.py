"""Local RAG over the fencing knowledge base (knowledge/*.md).

Fully on-device: embeddings come from a local ollama model (bge-m3) and the
index is a plain .npz + .json pair — no external vector-DB dependency, which
keeps the aarch64 deployment surface minimal. Swap-in of Chroma/LlamaIndex is
trivial if the corpus ever outgrows brute-force cosine search (thousands of
chunks are fine).
"""

import json
import os
import re

import numpy as np
import requests

DEFAULT_EMBED_MODEL = "bge-m3"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_PROVIDER = "ollama"


def _embed(texts, model=DEFAULT_EMBED_MODEL, base_url=None, provider=DEFAULT_PROVIDER, timeout=180):
    """Embed *texts* via a local embedding service.

    Two provider API shapes are supported, independent of whichever provider
    the VLM/chat agent is configured with:
      - "ollama": native /api/embed (bge-m3 etc. served by `ollama serve`).
      - anything else (e.g. "llama.cpp"): OpenAI-compatible /v1/embeddings,
        served by a `llama-server --embedding` instance or vLLM.
    """
    base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    if provider == "ollama":
        response = requests.post(f"{base_url}/api/embed",
                                 json={"model": model, "input": texts}, timeout=timeout)
        response.raise_for_status()
        return np.array(response.json()["embeddings"], dtype=np.float32)

    response = requests.post(f"{base_url}/v1/embeddings",
                             json={"model": model, "input": texts}, timeout=timeout)
    response.raise_for_status()
    data = sorted(response.json()["data"], key=lambda d: d.get("index", 0))
    return np.array([d["embedding"] for d in data], dtype=np.float32)


def chunk_markdown(path):
    """Split one markdown doc into section chunks with title context."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    doc_title = os.path.basename(path).removesuffix(".md")
    match = re.match(r"\s*#\s+(.+)", text)
    if match:
        doc_title = match.group(1).strip()

    chunks = []
    sections = re.split(r"\n(?=##\s)", text)
    for section in sections:
        section = section.strip()
        if not section:
            continue
        heading = ""
        m = re.match(r"##\s+(.+)", section)
        if m:
            heading = m.group(1).strip()
        body = re.sub(r"^#{1,2}\s+.+\n?", "", section).strip()
        if len(body) < 30:
            continue
        source = f"{doc_title}" + (f" § {heading}" if heading else "")
        chunks.append({"source": source, "text": f"{source}\n{body}"})
    return chunks


def build_index(knowledge_dir="knowledge", index_dir="knowledge/.index",
                embed_model=DEFAULT_EMBED_MODEL, base_url=None, provider=DEFAULT_PROVIDER):
    chunks = []
    for name in sorted(os.listdir(knowledge_dir)):
        if name.endswith(".md"):
            chunks.extend(chunk_markdown(os.path.join(knowledge_dir, name)))
    if not chunks:
        raise RuntimeError(f"No markdown docs found under {knowledge_dir}")

    print(f"Embedding {len(chunks)} chunks with {embed_model} ({provider})...")
    vectors = _embed([c["text"] for c in chunks], model=embed_model, base_url=base_url, provider=provider)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9

    os.makedirs(index_dir, exist_ok=True)
    np.save(os.path.join(index_dir, "vectors.npy"), vectors)
    with open(os.path.join(index_dir, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump({"embed_model": embed_model, "provider": provider, "chunks": chunks}, f, ensure_ascii=False)
    print(f"Index built: {len(chunks)} chunks -> {index_dir}")
    return index_dir


class KnowledgeStore:
    def __init__(self, index_dir="knowledge/.index", base_url=None, provider=None):
        self.vectors = np.load(os.path.join(index_dir, "vectors.npy"))
        with open(os.path.join(index_dir, "chunks.json"), encoding="utf-8") as f:
            payload = json.load(f)
        self.chunks = payload["chunks"]
        self.embed_model = payload.get("embed_model", DEFAULT_EMBED_MODEL)
        # Fall back to whatever the index was built with, so a stale index
        # from before per-provider support keeps behaving as it did (ollama).
        self.provider = provider or payload.get("provider", DEFAULT_PROVIDER)
        self.base_url = base_url

    def search(self, query, k=4, min_score=0.35):
        q = _embed([query], model=self.embed_model, base_url=self.base_url, provider=self.provider)[0]
        q /= np.linalg.norm(q) + 1e-9
        scores = self.vectors @ q
        order = np.argsort(-scores)[:k]
        results = []
        for i in order:
            if scores[i] < min_score:
                continue
            results.append({
                "source": self.chunks[i]["source"],
                "text": self.chunks[i]["text"],
                "score": round(float(scores[i]), 3),
            })
        return results
