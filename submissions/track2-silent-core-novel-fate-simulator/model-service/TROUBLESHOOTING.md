# Troubleshooting

> All issues encountered during deployment on AMD Radeon Cloud.
> Each entry includes the error message, root cause, and fix.

## Quick Reference

| # | Issue | Severity |
|---|-------|----------|
| 1 | git clone SSL certificate verification failed | Low |
| 2 | spaCy model: Invalid wheel filename | Low |
| 3 | Services exit immediately with `python xxx.py` | Medium |
| 4 | Gateway crash: KeyError env vars | High |
| 5 | Gateway: Model service unavailable (wrong ports) | **Critical** |
| 6 | Checking which services are running | Info |
| 7 | SSH connection refused / timed out | Medium |
| 8 | `--flash-attn` requires a value | Low |
| 9 | Image/TTS returns 70-byte JSON instead of real file | **Critical** |
| 10 | `llama-bench` fails: model not found | Medium |
| 11 | Disk space: No space left on device | High |
| 12 | Port already in use: Errno 98 | Medium |
| 13 | HF-MIRROR for users in China | Info |
| 14 | Restarting all services cleanly | Info |
| 15 | Image service: model not found (IMAGE_MODEL_PATH) | **Critical** |
| 16 | Complete environment variables reference | Info |
| 17 | Image API returns JSON (not raw PNG) | Medium |
| 18 | TTS service unreachable after restart | **Critical** |
| 19 | Downloading files from server to local Windows | Info |
| 20 | Complete startup script for fresh server | Info |

---

## 1. `git clone` SSL certificate verification failed

```
fatal: unable to access 'https://github.com/...': server certificate verification failed.
CAfile: none CRLfile: none
```

**Fix:** Disable SSL verification in the container:
```bash
git config --global http.sslVerify false
```

## 2. `pip install` spaCy model: Invalid wheel filename

```
ERROR: Invalid wheel filename (invalid version): 'en_core_web_sm-any-py3-none-any'
```

**Fix:** Use spacy's own download command instead of a direct pip URL:
```bash
python -m spacy download en_core_web_sm
```

## 3. Services exit immediately with `python xxx.py --port`

```
(venv) root@...:~/model-service# python image_service.py --port 8082
(venv) root@...:~/model-service#     # prompt returns immediately, no server started
```

**Cause:** The three service scripts lack `if __name__ == "__main__"` entry
blocks, so `python xxx.py` runs the module top-to-bottom and exits without
calling `uvicorn.run()`.

**Fix:** Use `uvicorn` directly:
```bash
uvicorn image_service:app --host 0.0.0.0 --port 8082
uvicorn tts_service:app --host 0.0.0.0 --port 8083
uvicorn gateway:app --host 0.0.0.0 --port 8000
```

## 4. Gateway crash: `KeyError: 'SILENT_CORE_INTERNAL_API_KEY'`

```
KeyError: 'SILENT_CORE_INTERNAL_API_KEY'
```

**Cause:** `gateway.py` reads two environment variables at import time. Both
must be set **before** launching uvicorn.

**Fix:**
```bash
export SILENT_CORE_API_KEY="test-key"
export SILENT_CORE_INTERNAL_API_KEY="test-key"
uvicorn gateway:app --host 0.0.0.0 --port 8000
```

## 5. Gateway returns `Model service unavailable`

```json
{"detail": "Model service unavailable: All connection attempts failed"}
```

**Cause:** Gateway cannot reach one or more backend services. The gateway
code reads three URL environment variables with **wrong default ports**:

```python
LLM_URL = os.getenv("LLM_URL", "http://127.0.0.1:8001")    # default 8001, should be 8081
IMAGE_URL = os.getenv("IMAGE_URL", "http://127.0.0.1:8002") # default 8002, should be 8082
TTS_URL = os.getenv("TTS_URL", "http://127.0.0.1:8003")    # default 8003, should be 8083
```

If any URL is not set, the gateway connects to the wrong port and silently
fails. The error response is a 70-byte JSON file, NOT the actual image/audio.

**Fix:** Set ALL three URL variables before starting gateway:
```bash
export LLM_URL="http://127.0.0.1:8081"
export IMAGE_URL="http://127.0.0.1:8082"
export TTS_URL="http://127.0.0.1:8083"
```

## 6. Checking which services are running

`ss` and `netstat` may not be installed in the container. Use curl instead:
```bash
for port in 8081 8082 8083 8000; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$port/ 2>/dev/null)
  echo "Port $port: $code"
done
```

Expected results when all services are up:
- `8081`: 415 (llama.cpp rejects GET, but server is alive)
- `8082`: 404 (FastAPI, no root route — check `/docs` for 200)
- `8083`: 404 (same as above)
- `8000`: 404 (same as above)

## 7. SSH connection refused / timed out

**Connection timed out:** The instance IP or port has changed after restart.
Check the AMD Radeon Cloud dashboard for updated SSH connection info.

**Connection refused:** The host is reachable but SSH service is not running
on the specified port. Verify the port number in the dashboard.

**Identity file not accessible:** Use absolute path on Windows:
```cmd
ssh -i C:\Users\<username>\.ssh\id_ed25519 root@<IP> -p <PORT>
```

## 8. `--flash-attn` requires a value

```
error: argument --flash-attn: expected one argument
```

**Fix:** Use `--flash-attn on` (not just `--flash-attn`).

## 9. Image/TTS returns 70-byte JSON instead of real file

```
-rw-r--r-- 1 root root 70 Aug 16 13:34 /tmp/test_image.png
/tmp/test_image.png: JSON text data
```

**Cause:** The gateway's default port mapping (8002/8003) doesn't match the
actual service ports (8082/8083). The gateway returns an error JSON but the
curl command saves it as `.png` or `.wav`.

**Diagnosis:**
```bash
cat /tmp/test_image.png
# If it shows: {"detail":"Model service unavailable: All connection attempts failed"}
# Then IMAGE_URL or TTS_URL is not set correctly.
```

**Fix:** Set `IMAGE_URL` and `TTS_URL`, then restart gateway (see #5).

## 10. `llama-bench` fails: `failed to load model`

```
llama_bench: error: failed to load model './models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf'
```

**Cause:** Using a relative path (`./models/...`) from the `model-service`
directory. The model files are at `/workspace/models/` (or a symlink to
`/data/models/`), not inside `model-service/models/`.

**Fix:** Use absolute path:
```bash
/workspace/llama.cpp/build/bin/llama-bench \
  -m /workspace/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  -ngl 99 -t 16 -fa 1 -p 512 -n 128
```

Or create a symlink in the model-service directory:
```bash
ln -sf /workspace/models ./models
```

## 11. Disk space: `No space left on device`

```
OSError: [Errno 28] No space left on device
```

**Cause:** The `/workspace` partition has only ~20 GB. Model files (4-5 GB
each) fill it up quickly.

**Fix:** Store models in `/data/models/` (root partition, ~700 GB available)
and create a symlink:
```bash
mkdir -p /data/models
mv /workspace/models/* /data/models/
rm -rf /workspace/models
ln -s /data/models /workspace/models
```

## 12. Port already in use: `Errno 98`

```
ERROR: [Errno 98] error while attempting to bind on address ('0.0.0.0', 8082): address already in use
```

**Cause:** An old process is still holding the port. `lsof` may not be
installed in the container.

**Fix:** Use `pkill` (not `lsof`) to kill old processes:
```bash
pkill -f "uvicorn image_service" 2>/dev/null
pkill -f "uvicorn tts_service" 2>/dev/null
pkill -f "uvicorn gateway" 2>/dev/null
pkill -f "llama-server" 2>/dev/null
sleep 2

# Verify ports are free
ss -tlnp | grep -E '8081|8082|8083|8000'
```

## 13. HF-MIRROR for users in China

HuggingFace downloads from the default endpoint are extremely slow in China.
Set `HF_ENDPOINT` **before** running `huggingface-cli`:
```bash
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download Qwen/Qwen3-8B-GGUF Qwen3-8B-Q4_K_M.gguf \
  --local-dir ./models/Qwen3-8B-GGUF
```

## 14. Restarting all services cleanly

When in doubt, kill everything and restart from scratch:
```bash
# Kill all
pkill -f "llama-server" 2>/dev/null
pkill -f "uvicorn" 2>/dev/null
sleep 2

# Restart in order (see README "Run all services in background")
```

## 15. Image service: model not found `/persistent/silent-core/models/Z-Image-Turbo`

```
ValueError: The provided pretrained_model_name_or_path "/persistent/silent-core/models/Z-Image-Turbo" is neither a valid local path nor a valid repo id.
```

**Cause:** `image_service.py` defaults to `/persistent/silent-core/models/Z-Image-Turbo`
via `IMAGE_MODEL_PATH` env var. This path doesn't exist on fresh AMD Cloud instances.
The code also uses `local_files_only=True`, so it will NOT auto-download.

**Fix:** Download the model manually and set `IMAGE_MODEL_PATH`:
```bash
# Download from correct HuggingFace repo (Tongyi-MAI, NOT ZhipuAI)
export HF_ENDPOINT=https://hf-mirror.com  # For China users
huggingface-cli download Tongyi-MAI/Z-Image-Turbo \
  --local-dir /data/models/Z-Image-Turbo

# Set env vars before starting Image service
export IMAGE_MODEL_PATH="/data/models/Z-Image-Turbo"
export GENERATED_IMAGE_DIR="/data/generated/images"
mkdir -p /data/generated/images
```

> **Important:** The correct HuggingFace repo is `Tongyi-MAI/Z-Image-Turbo`
> (Apache 2.0 license). The repo `ZhipuAI/Z-Image-Turbo` does NOT exist
> and returns 401 Unauthorized.

## 16. Complete environment variables reference

The Image and TTS services read several environment variables that must be
set **before** starting uvicorn:

| Service | Env Var | Default | Purpose |
|---------|---------|---------|---------|
| Image | `IMAGE_MODEL_PATH` | `/persistent/silent-core/models/Z-Image-Turbo` | Model location |
| Image | `GENERATED_IMAGE_DIR` | `/persistent/silent-core/generated/images` | Output directory |
| Image | `IMAGE_CPU_OFFLOAD` | `true` | CPU offload to save VRAM |
| Image | `IMAGE_UNLOAD_AFTER_REQUEST` | `false` | Unload model after each request |
| Image | `IMAGE_COMPILE_TRANSFORMER` | `false` | torch.compile optimization |
| Gateway | `LLM_URL` | `http://127.0.0.1:8001` | LLM backend URL |
| Gateway | `IMAGE_URL` | `http://127.0.0.1:8002` | Image backend URL |
| Gateway | `TTS_URL` | `http://127.0.0.1:8003` | TTS backend URL |
| Gateway | `SILENT_CORE_API_KEY` | (none, required) | Client API key |
| Gateway | `SILENT_CORE_INTERNAL_API_KEY` | (none, required) | Internal auth key |

**All URL defaults use wrong ports (8001/8002/8003).** Always override with
8081/8082/8083 when starting on AMD Cloud.

## 17. Image API returns JSON (not raw PNG)

```bash
$ ls -la /workspace/test_image.png
-rw-r--r-- 1 root root 141 Aug 16 14:04 /workspace/test_image.png
$ file /workspace/test_image.png
/workspace/test_image.png: JSON text data
```

**Cause:** The Image API returns a JSON response with a URL to the generated
image (OpenAI-compatible format), not the raw image binary:

```json
{"created":1786889047,"data":[{"url":"http://127.0.0.1:8000/files/images/7080790539dc419d89f01702362f2e17.png","generation_size":"512x512"}]}
```

**Fix:** Parse the JSON to get the URL, then download the actual image:
```bash
# Method 1: Direct file from generated directory
ls -la /data/generated/images/
file /data/generated/images/*.png

# Method 2: Download via URL from the JSON response
url=$(cat /workspace/test_image.png | python3 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['url'])")
curl -s -o /workspace/real_image.png "$url"
```

## 18. TTS service unreachable after restart

```
{"detail":"model service unavailable: All connection attempts failed"}
```

**Cause:** When restarting Gateway with `pkill -f "uvicorn"`, ALL uvicorn
processes are killed — including TTS. If TTS is not restarted, or if
`TTS_URL` env var is not set when Gateway restarts, the same "All connection
attempts failed" error occurs.

**Fix:** Always restart services in order and set ALL env vars:
```bash
# 1. Restart TTS first
pkill -f "uvicorn tts_service" 2>/dev/null
sleep 2
cd /workspace/Radeon-hackathon-2026-07/submissions/track2-silent-core-novel-fate-simulator/model-service
source /opt/venv/bin/activate
nohup uvicorn tts_service:app --host 0.0.0.0 --port 8083 > /tmp/tts.log 2>&1 &
sleep 5

# 2. Restart Gateway with ALL env vars
pkill -f "uvicorn gateway" 2>/dev/null
sleep 2
export SILENT_CORE_API_KEY="test-key"
export SILENT_CORE_INTERNAL_API_KEY="test-key"
export LLM_URL="http://127.0.0.1:8081"
export IMAGE_URL="http://127.0.0.1:8082"
export TTS_URL="http://127.0.0.1:8083"
nohup uvicorn gateway:app --host 0.0.0.0 --port 8000 > /tmp/gateway.log 2>&1 &
sleep 3

# 3. Test TTS
curl -s -H "Authorization: Bearer test-key" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/v1/audio/speech \
  -d '{"model":"silent-core/tts","input":"Hello world"}' \
  -o /workspace/test_tts.wav
file /workspace/test_tts.wav  # Should show "WAVE audio" or "data"
```

## 19. Downloading files from server to local Windows

Use `scp` from Windows CMD (not PowerShell):
```cmd
scp -i C:\Users\<username>\.ssh\id_ed25519 -P <PORT> root@<IP>:/data/generated/images/<filename>.png D:\projects\test_image.png
```

Or copy to `/workspace/` and download via JupyterLab file browser:
```bash
cp /data/generated/images/*.png /workspace/
```
Then right-click the file in JupyterLab and select "Download".

## 20. Complete startup script for fresh server

Run this script after cloning the repo on a new AMD Cloud instance:

```bash
#!/bin/bash
set -e

# === 0. Clone repo ===
git config --global http.sslVerify false
git clone https://github.com/west-liu/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/submissions/track2-silent-core-novel-fate-simulator/model-service

# === 1. Install dependencies ===
python3 -m venv /opt/venv && source /opt/venv/bin/activate
pip install diffusers accelerate kokoro spacy soundfile httpx huggingface_hub uvicorn
python -m spacy download en_core_web_sm

# === 2. Build llama.cpp ===
cd /workspace
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100 -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 8 --target llama-server llama-bench
cd -

# === 3. Download models ===
export HF_ENDPOINT=https://hf-mirror.com  # China users

# LLM model
huggingface-cli download Qwen/Qwen3-8B-GGUF Qwen3-8B-Q4_K_M.gguf \
  --local-dir /data/models/Qwen3-8B-GGUF

# Image model (Tongyi-MAI, NOT ZhipuAI)
huggingface-cli download Tongyi-MAI/Z-Image-Turbo \
  --local-dir /data/models/Z-Image-Turbo

# Create symlink for LLM
ln -sf /data/models /workspace/models

# Create image output directory
mkdir -p /data/generated/images

# === 4. Start all services ===
source /opt/venv/bin/activate

# LLM
nohup /workspace/llama.cpp/build/bin/llama-server \
  --model /data/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8081 \
  --n-gpu-layers 99 --ctx-size 8192 --threads 16 \
  --batch-size 512 --flash-attn on \
  > /tmp/llm.log 2>&1 &
sleep 10

# Image
export IMAGE_MODEL_PATH="/data/models/Z-Image-Turbo"
export GENERATED_IMAGE_DIR="/data/generated/images"
nohup uvicorn image_service:app --host 0.0.0.0 --port 8082 > /tmp/image.log 2>&1 &
sleep 10

# TTS
nohup uvicorn tts_service:app --host 0.0.0.0 --port 8083 > /tmp/tts.log 2>&1 &
sleep 5

# Gateway
export SILENT_CORE_API_KEY="test-key"
export SILENT_CORE_INTERNAL_API_KEY="test-key"
export LLM_URL="http://127.0.0.1:8081"
export IMAGE_URL="http://127.0.0.1:8082"
export TTS_URL="http://127.0.0.1:8083"
nohup uvicorn gateway:app --host 0.0.0.0 --port 8000 > /tmp/gateway.log 2>&1 &
sleep 3

# === 5. Verify all services ===
echo "LLM: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8081/health)"
echo "Image: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8082/docs)"
echo "TTS: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8083/docs)"
echo "Gateway: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs)"
```

Save as `setup.sh` and run with `bash setup.sh` on a fresh instance.
