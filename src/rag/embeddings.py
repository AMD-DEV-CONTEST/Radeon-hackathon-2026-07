import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ROCEmbeddings:
    """GPU-accelerated embeddings using sentence-transformers on ROCm."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-large-en-v1.5",
        query_instruction: Optional[str] = "Represent this sentence for searching relevant passages: ",
    ):
        """Initializes the ROCEmbeddings model.

        Args:
            model_name (str): Sentence-transformers model path or name.
            query_instruction (str): Prefix instruction for query embeddings (used by BGE models).
        """
        self.model_name = model_name
        self.query_instruction = query_instruction
        self.device = "cpu"
        self.rocm_available = False
        self.hip_version = None
        self.is_bge = "bge" in model_name.lower()

        try:
            import torch
            from sentence_transformers import SentenceTransformer

            # Check for ROCm/HIP support
            if hasattr(torch.version, "hip") and torch.version.hip is not None:
                self.rocm_available = True
                self.hip_version = torch.version.hip
                if torch.cuda.is_available():
                    self.device = "cuda"  # PyTorch maps 'cuda' to HIP internally
                    logger.info(f"ROCm detected (HIP {self.hip_version}). Using GPU acceleration.")
                else:
                    logger.warning("ROCm detected but CUDA/HIP is not available. Falling back to CPU.")
            elif torch.cuda.is_available():
                self.device = "cuda"
                logger.info("CUDA detected. Using GPU acceleration.")
            else:
                logger.info("No GPU detected. Falling back to CPU.")

            self.model = SentenceTransformer(self.model_name, device=self.device)
            logger.info(f"Loaded embedding model {self.model_name} on {self.device}")

        except ImportError as e:
            logger.error(f"Failed to import required libraries: {e}")
            raise
        except Exception as e:
            logger.error(f"Error loading embedding model: {e}")
            raise

    def embed_query(self, text: str) -> List[float]:
        """Embeds a single query string.

        Prepend query_instruction if model is a BGE model.

        Args:
            text (str): The query text.

        Returns:
            List[float]: The embedding vector.
        """
        try:
            query_text = text
            if self.is_bge and self.query_instruction and not query_text.startswith(self.query_instruction):
                query_text = f"{self.query_instruction}{text}"

            embedding = self.model.encode(query_text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Error embedding query: {e}")
            return []

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embeds a batch of documents without instruction prefix.

        Args:
            texts (List[str]): The document texts.

        Returns:
            List[List[float]]: List of embedding vectors.
        """
        try:
            embeddings = self.model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Error embedding documents: {e}")
            return [[] for _ in texts]

    def get_device_info(self) -> Dict[str, Any]:
        """Returns information about the underlying compute device.

        Returns:
            Dict[str, Any]: Device information.
        """
        return {
            "device": self.device,
            "rocm_available": self.rocm_available,
            "hip_version": self.hip_version,
            "model_name": self.model_name,
        }
