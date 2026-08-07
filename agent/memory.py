import os
import chromadb
import uuid

class AgentMemory:
    def __init__(self, collection_name: str = "sentinel_memory", persist_directory: str = "./agent_db"):
        print(f"Initializing Memory Database at {persist_directory}...")
        
        # Initialize ChromaDB client with persistent storage
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"} # Default similarity metric
        )

    def add_interaction(self, user_input: str, agent_response: str, metadata: dict = None):
        """Saves a conversation turn into the vector DB."""
        if metadata is None:
            metadata = {"type": "conversation"}
            
        doc_id = str(uuid.uuid4())
        document = f"User: {user_input}\nAgent: {agent_response}"
        
        self.collection.add(
            documents=[document],
            metadatas=[metadata],
            ids=[doc_id]
        )

    def get_relevant_context(self, query: str, n_results: int = 3) -> list:
        """Retrieves relevant past interactions based on the user query."""
        if self.collection.count() == 0:
            return []
            
        # Ensure we don't request more results than documents exist
        fetch_count = min(n_results, self.collection.count())
        
        results = self.collection.query(
            query_texts=[query],
            n_results=fetch_count
        )
        
        # Return the retrieved documents
        if results and results['documents']:
            return results['documents'][0]
        return []
