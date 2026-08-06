import os
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Settings:
    SECRET_KEY: str = os.environ.get('SECRET_KEY', 'indusmind-dev-secret-change-in-production')
    DATABASE_URL: str = os.environ.get('DATABASE_URL', 'sqlite:///../data/indusmind.db')
    UPLOAD_DIR: str = os.environ.get('UPLOAD_DIR', '../data/uploads')
    CHROMA_PATH: str = os.environ.get('CHROMA_PATH', '../data/chroma')
    LOCAL_LLM_ENABLED: bool = os.environ.get('LOCAL_LLM_ENABLED', 'false').lower() in ('true', '1', 't')
    LOCAL_LLM_PATH: str = os.environ.get('LOCAL_LLM_PATH', '../ai-service/local_model')
    LORA_PATH: str = os.environ.get('LORA_PATH', '../model-lora-output')
    TESSERACT_CMD: str = os.environ.get('TESSERACT_CMD', '')
    ALLOWED_ORIGINS: str = os.environ.get('ALLOWED_ORIGINS', 'http://localhost:5173,http://localhost:8000')
    GEMINI_API_KEY: str = os.environ.get('GEMINI_API_KEY', '')
    GEMINI_MODEL: str = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')

    def __post_init__(self):
        base_dir = Path(__file__).resolve().parent
        self.UPLOAD_DIR = str((base_dir / self.UPLOAD_DIR).resolve())
        self.CHROMA_PATH = str((base_dir / self.CHROMA_PATH).resolve())
        self.LOCAL_LLM_PATH = str((base_dir / self.LOCAL_LLM_PATH).resolve())
        self.LORA_PATH = str((base_dir / self.LORA_PATH).resolve())
        
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
        os.makedirs(self.CHROMA_PATH, exist_ok=True)
        
        if self.DATABASE_URL.startswith("sqlite:///"):
            db_path = self.DATABASE_URL.replace("sqlite:///", "")
            full_db_path = (base_dir / db_path).resolve()
            os.makedirs(full_db_path.parent, exist_ok=True)
            self.DATABASE_URL = f"sqlite:///{full_db_path}"

settings = Settings()
