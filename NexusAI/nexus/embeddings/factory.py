import os
from nexus.embeddings.local_provider import LocalEmbeddingProvider
from nexus.embeddings.rocm_provider import ROCmEmbeddingProvider
def get_embedding_provider():
    requested=os.getenv("NEXUS_EMBEDDING_PROVIDER","auto").lower()
    if requested=="local":return LocalEmbeddingProvider()
    if requested=="rocm":return ROCmEmbeddingProvider()
    r=ROCmEmbeddingProvider()
    return r if r.health()["available"] else LocalEmbeddingProvider()
