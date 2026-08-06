import numpy as np
from dataclasses import dataclass
from nexus.embeddings import get_embedding_provider
@dataclass
class DenseSearchHit:index:int;score:float
class DenseSemanticRetriever:
    def __init__(self,provider=None):self.provider=provider or get_embedding_provider()
    def search(self,query,documents,top_k=5):
        if not query.strip() or not documents:return []
        v=self.provider.encode([query,*documents]).vectors;scores=v[1:]@v[0];ranked=np.argsort(scores)[::-1][:max(1,top_k)]
        return [DenseSearchHit(int(i),float(scores[i])) for i in ranked if scores[i]>0]
