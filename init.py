import os
import glob
from huggingface_hub import snapshot_download

MODEL_DIR = "./LLM/Models"
REPO_ID = "Qwen/Qwen2.5-32B-Instruct-GGUF"
FILE_PATTERN = "*q8_0*.gguf"

def ensure_model_downloaded():
    os.makedirs(MODEL_DIR, exist_ok=True)

    search_path = os.path.join(MODEL_DIR, FILE_PATTERN)
    
    existing_files = glob.glob(search_path)

    if existing_files:
        print(f"LLM Model found: {len(existing_files)}")
    else:
        print("LLM Model not found locally. Starting download from HuggingFace...")
        snapshot_download(
            repo_id=REPO_ID,
            local_dir=MODEL_DIR,
            allow_patterns=[FILE_PATTERN]
        )
        print("Download completed")

ensure_model_downloaded()