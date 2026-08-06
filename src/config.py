from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel

class InferenceConfig(BaseModel):
    """Configuration for inference backends (vLLM, Ollama, and Radeon API)."""
    backend: str = "vllm"  # "vllm" | "ollama" | "radeon_api"
    primary_model: str = "Qwen/Qwen3-30B-A3B"
    secondary_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    quantization: str = "gptq"  # gptq, awq, or none
    dtype: str = "float16"
    max_model_len: int = 32768
    tensor_parallel_size: int = 1
    gpu_memory_utilization: float = 0.85
    vllm_host: str = "localhost"
    vllm_port: int = 8000
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:0.6b"
    enable_prefix_caching: bool = True
    enable_chunked_prefill: bool = True
    radeon_api_url: str = "https://developer.amd.com.cn/radeon/api/v1"
    radeon_api_key: str = ""
    radeon_model: str = "Qwen3-30B-A3B"

class RAGConfig(BaseModel):
    """Configuration for Retrieval-Augmented Generation."""
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k: int = 5
    num_hops: int = 3
    num_docs: int = 5
    max_backtracks: int = 2
    vector_db_path: str = "./data/vector_db"
    documents_path: str = "./data/documents"

class PrivacyConfig(BaseModel):
    """Configuration for privacy controls and auditing."""
    audit_log_path: str = "./data/audit/audit.jsonl"
    enable_encryption: bool = False
    encryption_key_path: str = "./data/memory/encryption.key"
    auto_approve_file_read: bool = True
    auto_approve_file_search: bool = True
    auto_approve_file_list: bool = True
    require_approval_file_write: bool = True
    require_approval_email: bool = True
    require_approval_calendar_write: bool = True
    require_approval_web_search: bool = True

class MemoryConfig(BaseModel):
    """Configuration for session memory and database."""
    db_path: str = "./data/memory/sessions.db"
    max_context_tokens: int = 4096
    chars_per_token: float = 4.0  # approximate

class AgentConfig(BaseModel):
    """Configuration for the ReAct agent loop and token budgeting."""
    max_iterations: int = 10
    max_tokens_per_turn: int = 4096
    max_total_tokens: int = 12000

class ServerConfig(BaseModel):
    """Configuration for the FastAPI/Gradio server."""
    host: str = "0.0.0.0"
    port: int = 7860
    debug: bool = False
    gradio_share: bool = False

class BunkerConfig(BaseSettings):
    """Root configuration object for the Bunker agent."""
    inference: InferenceConfig = InferenceConfig()
    rag: RAGConfig = RAGConfig()
    privacy: PrivacyConfig = PrivacyConfig()
    memory: MemoryConfig = MemoryConfig()
    agent: AgentConfig = AgentConfig()
    server: ServerConfig = ServerConfig()

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_prefix="BUNKER_", 
        env_nested_delimiter="__",
        extra="ignore"
    )

@lru_cache()
def get_config() -> BunkerConfig:
    """Returns a cached singleton BunkerConfig instance."""
    return BunkerConfig()
