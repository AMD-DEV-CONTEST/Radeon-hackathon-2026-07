"""
Local Embeddings - BGE-M3 or all-MiniLM running on ROCm PyTorch
100% offline
"""
from typing import List
import os

class LocalEmbeddings:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self.model = None
        self._load()

    def _load(self):
        try:
            from sentence_transformers import SentenceTransformer
            # Will use ROCm if torch+rocm is installed
            device = "cuda"  # ROCm uses cuda alias in PyTorch
            try:
                import torch
                if not torch.cuda.is_available():
                    device = "cpu"
            except:
                device = "cpu"
            print(f"[Embeddings] Loading {self.model_name} on {device}")
            self.model = SentenceTransformer(self.model_name, device=device)
        except Exception as e:
            print(f"[Embeddings] Failed to load, using mock: {e}")
            self.model = None

    def embed(self, texts: List[str]) -> List[List[float]]:
        if self.model:
            return self.model.encode(texts, show_progress_bar=False).tolist()
        else:
            # Mock 384-dim embeddings for demo
            import hashlib, random
            embeddings = []
            for t in texts:
                random.seed(int(hashlib.md5(t.encode()).hexdigest()[:8], 16))
                embeddings.append([random.random() for _ in range(384)])
            return embeddings
