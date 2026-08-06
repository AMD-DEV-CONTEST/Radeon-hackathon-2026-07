import os
import requests
import time
from pathlib import Path

MODEL_ID = "unsloth/llama-3-8b-Instruct-bnb-4bit"
BASE_URL = f"https://huggingface.co/{MODEL_ID}/resolve/main"
LOCAL_DIR = Path(__file__).parent.parent / "local_model"

FILES = [
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json"
]

def download_file_with_retry(filename):
    url = f"{BASE_URL}/{filename}"
    file_path = LOCAL_DIR / filename
    
    while True:
        resume_byte_pos = file_path.stat().st_size if file_path.exists() else 0
        headers = {"Range": f"bytes={resume_byte_pos}-"} if resume_byte_pos > 0 else {}
        
        try:
            print(f"Connecting to {filename} (Resuming from {resume_byte_pos / (1024*1024):.2f} MB)...")
            # We use a 15 second timeout to quickly catch dropped connections
            response = requests.get(url, headers=headers, stream=True, timeout=15)
            
            if response.status_code == 416: # Range not satisfiable means the file is completely downloaded
                print(f"[*] {filename} is fully downloaded.")
                break
                
            if response.status_code not in (200, 206):
                print(f"Server returned status {response.status_code}. Retrying in 5 seconds...")
                time.sleep(5)
                continue
                
            mode = "ab" if response.status_code == 206 else "wb"
            with open(file_path, mode) as f:
                for chunk in response.iter_content(chunk_size=1024*1024): # Download in 1MB chunks
                    if chunk:
                        f.write(chunk)
            
            # If we exit the loop without an exception, it finished successfully
            print(f"[*] {filename} downloaded successfully.")
            break
            
        except Exception as e:
            print(f"Connection dropped ({e}). Reconnecting in 3 seconds to resume...")
            time.sleep(3)

if __name__ == "__main__":
    LOCAL_DIR.mkdir(exist_ok=True)
    print(f"Downloading model directly to {LOCAL_DIR}...")
    for f in FILES:
        download_file_with_retry(f)
    print("\n--- ALL FILES DOWNLOADED SUCCESSFULLY ---")
