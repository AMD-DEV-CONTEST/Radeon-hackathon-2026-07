import os
import structlog
from typing import Dict, List, Any
import chromadb
from chromadb.config import Settings
from langchain_ollama import OllamaEmbeddings
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

class ChromaDBClient:
    """
    Singleton wrapper for ChromaDB using local Ollama embeddings.
    Manages multiple distinct collections for Long-Term Memory.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ChromaDBClient, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        # Initialize Local Ollama Embeddings (nomic-embed-text)
        try:
            self.embeddings = OllamaEmbeddings(
                model="nomic-embed-text",
                base_url=settings.ollama_base_url
            )
            logger.info("Initialized Ollama embeddings", model="nomic-embed-text")
        except Exception as e:
            logger.error("Failed to initialize Ollama embeddings", error=str(e))
            self.embeddings = None

        # Initialize Persistent ChromaDB Client
        persist_dir = os.path.join(os.getcwd(), "chroma_db")
        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Initialize 7 Distinct Collections
        collection_names = [
            "memory_pricing", 
            "memory_seo", 
            "memory_branding", 
            "memory_marketplace", 
            "memory_competitor", 
            "memory_seller", 
            "memory_marketing"
        ]
        
        self.collections = {}
        for name in collection_names:
            self.collections[name] = self.client.get_or_create_collection(
                name=name,
                metadata={"description": f"Long-term memory for {name.split('_')[1]}"}
            )
        logger.info("Initialized ChromaDB collections", collections=collection_names)

    def add_memory(self, collection_name: str, document: str, metadata: dict, doc_id: str):
        """Add a memory to a specific collection with rich metadata."""
        if collection_name not in self.collections:
            raise ValueError(f"Collection {collection_name} does not exist.")
            
        collection = self.collections[collection_name]
        
        # Use Langchain OllamaEmbeddings to generate vector
        embedding = None
        if self.embeddings:
            try:
                embedding = self.embeddings.embed_query(document)
            except Exception as e:
                logger.warning("Embedding generation failed, falling back to mock", error=str(e))
        
        if not embedding:
            # Mock embedding for hackathon demo fallback (768 dimensions for nomic)
            import random
            embedding = [random.uniform(-1, 1) for _ in range(768)]

        collection.add(
            documents=[document],
            embeddings=[embedding],
            metadatas=[metadata],
            ids=[doc_id]
        )
        logger.debug("Added memory to ChromaDB", collection=collection_name, doc_id=doc_id)

    def search_memory(self, collection_name: str, query: str, n_results: int = 5) -> Dict[str, Any]:
        """Perform a vector search in a specific collection."""
        if collection_name not in self.collections:
            raise ValueError(f"Collection {collection_name} does not exist.")
            
        collection = self.collections[collection_name]
        
        embedding = None
        if self.embeddings:
            try:
                embedding = self.embeddings.embed_query(query)
            except Exception as e:
                logger.warning("Embedding generation failed", error=str(e))
                
        if not embedding:
            import random
            embedding = [random.uniform(-1, 1) for _ in range(768)]
            
        results = collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            include=['documents', 'metadatas', 'distances']
        )
        return results

    def search_all(self, query: str, n_results_per_collection: int = 2) -> List[Dict[str, Any]]:
        """Search across all collections."""
        all_results = []
        for name in self.collections:
            try:
                res = self.search_memory(name, query, n_results_per_collection)
                # Parse ChromaDB output format
                if res and res.get('documents') and res['documents'][0]:
                    for i in range(len(res['documents'][0])):
                        all_results.append({
                            "collection": name,
                            "document": res['documents'][0][i],
                            "metadata": res['metadatas'][0][i],
                            "distance": res['distances'][0][i],
                            "id": res['ids'][0][i]
                        })
            except Exception as e:
                logger.warning("Search failed for collection", collection=name, error=str(e))
        return all_results

vector_store = ChromaDBClient()
