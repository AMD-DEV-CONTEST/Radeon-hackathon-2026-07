import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.preprocessing import normalize
from nexus.embeddings.base import EmbeddingBatch,EmbeddingProvider
class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self,dimension=768):
        self.dimension=dimension;self.vectorizer=HashingVectorizer(n_features=dimension,alternate_sign=False,norm=None,lowercase=True,ngram_range=(1,2))
    def encode(self,texts):
        if not texts:v=np.empty((0,self.dimension),dtype="float32")
        else:v=normalize(self.vectorizer.transform(texts),norm="l2",axis=1).toarray().astype("float32")
        return EmbeddingBatch(v,"cpu","hashing-vectorizer",self.dimension)
    def health(self):return {"provider":"local","available":True,"device":"cpu","model":"hashing-vectorizer","dimension":self.dimension}
