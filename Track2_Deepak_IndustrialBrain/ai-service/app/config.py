from dataclasses import dataclass
from pathlib import Path
import os


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "ai-service" / ".env")


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    local_llm_enabled: bool = os.getenv("LOCAL_LLM_ENABLED", "true").lower() == "true"
    local_llm_path: str = os.getenv("LOCAL_LLM_PATH", str(ROOT / "model-lora-output"))
    chroma_path: Path = Path(os.getenv("CHROMA_PATH", str(ROOT / "data" / "chroma"))).resolve()
    index_path: Path = Path(os.getenv("INDEX_PATH", str(ROOT / "data" / "index" / "index.json"))).resolve()
    tesseract_cmd: str = os.getenv("TESSERACT_CMD", "")
    allowed_origins: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:8080,http://localhost:8081,http://127.0.0.1:5173")


settings = Settings()

