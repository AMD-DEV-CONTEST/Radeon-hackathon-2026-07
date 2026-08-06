from abc import ABC,abstractmethod
from dataclasses import dataclass
import numpy as np
@dataclass
class EmbeddingBatch:
    vectors:np.ndarray;device:str;model_name:str;dimension:int
class EmbeddingProvider(ABC):
    @abstractmethod
    def encode(self,texts:list[str])->EmbeddingBatch:...
    @abstractmethod
    def health(self)->dict:...
