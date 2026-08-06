from nexus.embeddings.local_provider import LocalEmbeddingProvider
from nexus.retrieval.dense_service import DenseSemanticRetriever
def test_local_embedding_shape():
    b=LocalEmbeddingProvider(128).encode(["hello world","nexus ai"]);assert b.vectors.shape==(2,128)
def test_dense_retrieval_local():
    r=DenseSemanticRetriever(LocalEmbeddingProvider());h=r.search("NexusAI backend",["Aria lives in Kochi.","Noah maintains the NexusAI backend.","Lab in Bengaluru."],3);assert h and h[0].index==1
