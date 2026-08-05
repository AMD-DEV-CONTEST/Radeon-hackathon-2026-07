from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(slots=True)
class AppConfig:
    project_name: str = "AgentFlow AI"
    api_prefix: str = "/api"
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    preferred_models: tuple[str, ...] = (
    "qwen2.5:3b",
    "qwen2.5:7b",
    "llama3.2:3b",
    "mistral:7b",
)
    base_dir: Path = Path(__file__).resolve().parent.parent
    data_dir: Path = base_dir / "runtime_data"
    uploads_dir: Path = data_dir / "uploads"
    chroma_dir: Path = data_dir / "chroma"
    db_path: Path = data_dir / "agentflow.db"
    sample_data_dir: Path = base_dir / "sample_data"
    max_upload_size_mb: int = 25
    rag_chunk_size: int = 900
    rag_chunk_overlap: int = 150
    rag_top_k: int = 5
    embedding_dimensions: int = 256

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.sample_data_dir.mkdir(parents=True, exist_ok=True)


config = AppConfig()
