# src/agent/config.py
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class AgentConfig:
    """Agent config"""
    agent_id: str = "default_agent"
    name: str = "Default Agent"
    description: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: float = 30.0
    # RAG-related config
    knowledge_base_path: Optional[str] = None
    embedding_model: str = "BAAI/bge-m3"
    vector_store_type: str = "faiss"
    chunk_size: int = 512
    chunk_overlap: int = 128
    # Other extension config
    extra: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.extra is None:
            self.extra = {}