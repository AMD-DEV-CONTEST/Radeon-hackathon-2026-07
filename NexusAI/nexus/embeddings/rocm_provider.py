import numpy as np
from nexus.embeddings.base import EmbeddingBatch,EmbeddingProvider
from nexus.embeddings.device import detect_device
class ROCmEmbeddingProvider(EmbeddingProvider):
    def __init__(self,model_name="sentence-transformers/all-MiniLM-L6-v2",batch_size=64):
        self.model_name=model_name;self.batch_size=batch_size;self.device_info=detect_device();self._model=None
    def _load(self):
        if self._model:return self._model
        if self.device_info.backend!="rocm" or not self.device_info.accelerator_available:raise RuntimeError("AMD ROCm GPU is not available")
        from sentence_transformers import SentenceTransformer
        self._model=SentenceTransformer(self.model_name,device="cuda");return self._model
    def encode(self,texts):
        if not texts:return EmbeddingBatch(np.empty((0,384),dtype="float32"),"rocm",self.model_name,384)
        v=self._load().encode(texts,batch_size=self.batch_size,convert_to_numpy=True,normalize_embeddings=True,show_progress_bar=False).astype("float32")
        return EmbeddingBatch(v,"rocm",self.model_name,int(v.shape[1]))
    def health(self):
        d=self.device_info;return {"provider":"rocm","available":d.backend=="rocm" and d.accelerator_available,"device":d.device_name,"backend":d.backend,"torch_version":d.torch_version,"hip_version":d.hip_version,"model":self.model_name}
