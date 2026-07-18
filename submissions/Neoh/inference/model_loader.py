import logging
import os
import requests
from typing import Optional
from tqdm import tqdm

logger = logging.getLogger(__name__)

MODEL_DOWNLOAD_URLS = {
    "qwen2.5-7b": {
        "Q4_K_M": "https://hf-mirror.com/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "Q5_K_M": "https://hf-mirror.com/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q5_K_M.gguf",
    },
    "qwen2.5-14b": {
        "Q4_K_M": "https://hf-mirror.com/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        "Q5_K_M": "https://hf-mirror.com/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q5_K_M.gguf",
    },
}


class ModelLoader:
    def __init__(self, models_dir: str = "./models"):
        self.models_dir = models_dir
        os.makedirs(models_dir, exist_ok=True)

    def download_model(self, model_name: str, quant: str = "Q4_K_M") -> str:
        if model_name not in MODEL_DOWNLOAD_URLS:
            raise ValueError(f"Unsupported model: {model_name}. Supported: {list(MODEL_DOWNLOAD_URLS.keys())}")
        
        if quant not in MODEL_DOWNLOAD_URLS[model_name]:
            raise ValueError(f"Unsupported quantization: {quant}. Supported: {list(MODEL_DOWNLOAD_URLS[model_name].keys())}")

        url = MODEL_DOWNLOAD_URLS[model_name][quant]
        filename = os.path.basename(url)
        save_path = os.path.join(self.models_dir, filename)

        if os.path.exists(save_path):
            logger.info(f"Model already exists: {save_path}")
            return save_path

        logger.info(f"Downloading model: {url}")
        logger.info(f"Saving to: {save_path}")

        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            chunk_size = 8192

            with open(save_path, "wb") as f, tqdm(
                desc=filename,
                total=total_size,
                unit="iB",
                unit_scale=True,
                unit_divisor=1024,
            ) as bar:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    size = f.write(chunk)
                    bar.update(size)

            logger.info(f"Model downloaded successfully: {save_path}")
            return save_path

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
        if model_name not in MODEL_DOWNLOAD_URLS:
            return None

        filename = f"{model_name.replace('-', '')}-Instruct-{quant}.gguf"
        save_path = os.path.join(self.models_dir, filename)

        if os.path.exists(save_path):
            return save_path
        return None