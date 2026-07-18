import logging
import os
from typing import Optional
from huggingface_hub import snapshot_download, hf_hub_download

logger = logging.getLogger(__name__)

MODEL_REPOS = {
    "qwen2.5-7b": "bartowski/Qwen2.5-7B-Instruct-GGUF",
    "qwen2.5-14b": "bartowski/Qwen2.5-14B-Instruct-GGUF",
}

MODEL_PATTERNS = {
    "qwen2.5-7b": {
        "Q4_K_M": "*Q4_K_M.gguf",
        "Q5_K_M": "*Q5_K_M.gguf",
    },
    "qwen2.5-14b": {
        "Q4_K_M": "*Q4_K_M.gguf",
        "Q5_K_M": "*Q5_K_M.gguf",
    },
}

MODEL_FILENAMES = {
    "qwen2.5-7b": {
        "Q4_K_M": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "Q5_K_M": "Qwen2.5-7B-Instruct-Q5_K_M.gguf",
    },
    "qwen2.5-14b": {
        "Q4_K_M": "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        "Q5_K_M": "Qwen2.5-14B-Instruct-Q5_K_M.gguf",
    },
}


class ModelLoader:
    def __init__(self, models_dir: str = "./models"):
        self.models_dir = models_dir
        os.makedirs(models_dir, exist_ok=True)

    def download_model(self, model_name: str, quant: str = "Q4_K_M") -> str:
        if model_name not in MODEL_REPOS:
            raise ValueError(f"Unsupported model: {model_name}. Supported: {list(MODEL_REPOS.keys())}")
        
        if quant not in MODEL_PATTERNS[model_name]:
            raise ValueError(f"Unsupported quantization: {quant}. Supported: {list(MODEL_PATTERNS[model_name].keys())}")

        repo_id = MODEL_REPOS[model_name]
        pattern = MODEL_PATTERNS[model_name][quant]
        expected_filename = MODEL_FILENAMES[model_name][quant]
        save_path = os.path.join(self.models_dir, expected_filename)

        if os.path.exists(save_path):
            logger.info(f"Model already exists: {save_path}")
            return save_path

        logger.info(f"Downloading model from Hugging Face: {repo_id}")
        logger.info(f"Pattern: {pattern}")
        logger.info(f"Saving to: {save_path}")

        try:
            downloaded_files = snapshot_download(
                repo_id=repo_id,
                allow_patterns=pattern,
                local_dir=self.models_dir,
                resume_download=True,
            )

            if os.path.exists(save_path):
                logger.info(f"Model downloaded successfully: {save_path}")
                return save_path

            for root, dirs, files in os.walk(self.models_dir):
                for f in files:
                    if f.endswith(".gguf") and quant in f:
                        found_path = os.path.join(root, f)
                        if found_path != save_path:
                            os.rename(found_path, save_path)
                        logger.info(f"Model downloaded successfully: {save_path}")
                        return save_path

            raise FileNotFoundError(f"Model file not found after download. Check: {downloaded_files}")

        except Exception as e:
            logger.error(f"Failed to download model: {str(e)}")
            if os.path.exists(save_path):
                os.remove(save_path)
            raise

    def list_models(self) -> list:
        models = []
        for f in os.listdir(self.models_dir):
            if f.endswith(".gguf"):
                models.append(f)
        return models

    def get_model_path(self, model_name: str, quant: str = "Q4_K_M") -> Optional[str]:
        if model_name not in MODEL_FILENAMES:
            return None

        if quant not in MODEL_FILENAMES[model_name]:
            return None

        filename = MODEL_FILENAMES[model_name][quant]
        save_path = os.path.join(self.models_dir, filename)

        if os.path.exists(save_path):
            return save_path
        return None
