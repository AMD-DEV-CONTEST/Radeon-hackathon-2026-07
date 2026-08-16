# Silent Core Model Service

The three AI models behind Novel Fate Simulator, served through one
OpenAI-compatible API gateway. Clients use stable model IDs:
`silent-core/llm`, `silent-core/image`, `silent-core/tts`.

## Models

| Model | Implementation | Compute | Role |
|---|---|---|---|
| `silent-core/llm` | Qwen3-8B Q4_K_M, llama.cpp HIP | AMD Radeon GPU | Narrative generation, agent reasoning |
| `silent-core/image` | Z-Image-Turbo, Diffusers CPU offload | AMD Radeon GPU | Scene illustration |
| `silent-core/tts` | Kokoro-82M, PyTorch | 16 CPU threads | English voice narration |

TTS runs on CPU so it does not contend with LLM and image workloads on the GPU.
The quantized LLM uses ~1/3 of the BF16 memory and reaches ~91.6 tok/s.

## API

```
POST /v1/chat/completions    # LLM text generation
POST /v1/responses            # LLM with structured output
POST /v1/images/generations   # Scene illustration
POST /v1/audio/speech         # Voice narration
GET  /v1/models               # List available models
GET  /health                  # Health check
```

All `/v1/*` requests require `Authorization: Bearer $API_KEY`.

See `examples/python_client.py` for chat, image, and speech client code.

## Deployment

### Hardware

- AMD Radeon GPU with ROCm (tested: gfx1100, 48 GB VRAM)
- Ubuntu 22.04, ROCm 7.2+
- ~30 GB storage for models + tools

### Instance setup (AMD Radeon Cloud)

1. **Image**: Select `AMD OneClick Base` (`amd-oneclick-base:rocm7.2.1-py3.12-v20260416`)
2. **SSH Key**: Paste your `~/.ssh/id_ed25519.pub` content into the SSH Public Key field **before** creating the instance
3. **Model API Key**: Not required — this project runs its own models, not AMD-hosted APIs

### 0. Prerequisites

ROCm must be installed and working:
```bash
rocm-smi                    # Should show your GPU
rocminfo | grep "Name:"     # Should list gfx1100 (or your GPU target)
```

If ROCm is not installed, follow the [AMD ROCm installation guide](https://rocm.docs.amd.com/en/latest/deploy/linux/install.html).

### 1. System dependencies

```bash
sudo apt-get update && sudo apt-get install -y espeak-ng libsndfile1 ffmpeg cmake git curl
```

### 2. Python environment

```bash
python3 -m venv /opt/venv && source /opt/venv/bin/activate
pip install diffusers accelerate kokoro spacy soundfile httpx huggingface_hub uvicorn
python -m spacy download en_core_web_sm
```

### 3. Build llama.cpp with HIP

```bash
git config --global http.sslVerify false
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100 -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 8 --target llama-server llama-bench
```

Replace `gfx1100` with your GPU target (`rocm_agent_enumerator` to find it).

### 4. Download models

```bash
huggingface-cli download Qwen/Qwen3-8B-GGUF Qwen3-8B-Q4_K_M.gguf \
  --local-dir ./models/Qwen3-8B-GGUF
# Image (Z-Image-Turbo) and TTS (Kokoro-82M) auto-download on first request
```

> **For users in China:** HuggingFace downloads can be very slow. Use the
> `hf-mirror.com` mirror by setting the `HF_ENDPOINT` environment variable
> **before** running `huggingface-cli`:
> ```bash
> export HF_ENDPOINT=https://hf-mirror.com
> huggingface-cli download Qwen/Qwen3-8B-GGUF Qwen3-8B-Q4_K_M.gguf \
>   --local-dir ./models/Qwen3-8B-GGUF
> ```
> Global users can use the default HuggingFace endpoint without any changes.

### 5. Start all services

> **Important:** `image_service.py`, `tts_service.py`, and `gateway.py` do not
> contain `if __name__ == "__main__"` entry blocks. You **must** use `uvicorn`
> to launch the FastAPI applications. Running `python xxx.py --port` will exit
> immediately without starting the server.

Start services **in order** — each backend must be running before the gateway starts:

```bash
# Terminal 1: LLM
./llama.cpp/build/bin/llama-server \
  --model ./models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8081 \
  --n-gpu-layers 99 \
  --ctx-size 8192 \
  --threads 16 \
  --batch-size 512 \
  --flash-attn on

# Terminal 2: Image
uvicorn image_service:app --host 0.0.0.0 --port 8082

# Terminal 3: TTS
uvicorn tts_service:app --host 0.0.0.0 --port 8083

# Terminal 4: Gateway (clients only need this port)
export SILENT_CORE_API_KEY="test-key"
export SILENT_CORE_INTERNAL_API_KEY="test-key"
export LLM_URL="http://127.0.0.1:8081"
export IMAGE_URL="http://127.0.0.1:8082"
export TTS_URL="http://127.0.0.1:8083"
uvicorn gateway:app --host 0.0.0.0 --port 8000
```

> **Critical: Set ALL three URL environment variables.** The gateway code
> defaults to ports 8001/8002/8003, but services run on 8081/8082/8083.
> If you only set `LLM_URL` and forget `IMAGE_URL` / `TTS_URL`, image and
> TTS requests will silently return a 70-byte JSON error file instead of
> the actual image/audio output. See Troubleshooting #9.

#### Run all services in background (one-time setup script)

```bash
cd /workspace/Radeon-hackathon-2026-07/submissions/track2-silent-core-novel-fate-simulator/model-service
source /opt/venv/bin/activate

# Kill any old processes first
pkill -f "llama-server" 2>/dev/null
pkill -f "uvicorn image_service" 2>/dev/null
pkill -f "uvicorn tts_service" 2>/dev/null
pkill -f "uvicorn gateway" 2>/dev/null
sleep 2

# LLM
nohup /workspace/llama.cpp/build/bin/llama-server \
  --model /workspace/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8081 \
  --n-gpu-layers 99 --ctx-size 8192 --threads 16 \
  --batch-size 512 --flash-attn on \
  > /tmp/llm.log 2>&1 &

sleep 10  # Wait for model loading

# Image
nohup uvicorn image_service:app --host 0.0.0.0 --port 8082 > /tmp/image.log 2>&1 &
sleep 5

# TTS
nohup uvicorn tts_service:app --host 0.0.0.0 --port 8083 > /tmp/tts.log 2>&1 &
sleep 3

# Gateway
export SILENT_CORE_API_KEY="test-key"
export SILENT_CORE_INTERNAL_API_KEY="test-key"
export LLM_URL="http://127.0.0.1:8081"
export IMAGE_URL="http://127.0.0.1:8082"
export TTS_URL="http://127.0.0.1:8083"
nohup uvicorn gateway:app --host 0.0.0.0 --port 8000 > /tmp/gateway.log 2>&1 &
sleep 3

# Verify all services
for port in 8081 8082 8083 8000; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$port/docs 2>/dev/null)
  echo "Port $port: $code"
done
```

### Smoke test

```bash
# Health
curl http://127.0.0.1:8000/health

# LLM
curl -H "Authorization: Bearer test-key" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/v1/chat/completions \
  -d '{"model":"silent-core/llm","messages":[{"role":"user","content":"Say hello."}],"max_tokens":16}'

# Image (10-30s on first call)
curl -H "Authorization: Bearer test-key" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/v1/images/generations \
  -d '{"model":"silent-core/image","prompt":"A silver compass on an ancient map","size":"512x512"}'

# TTS
curl -H "Authorization: Bearer test-key" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/v1/audio/speech \
  -d '{"model":"silent-core/tts","voice":"heart","input":"Silent Core is ready."}' --output test.wav
```

## Performance

| Workload | Metric | Value |
|---|---|---|
| LLM decode | tokens/s | ~93.3 |
| LLM prompt processing | tokens/s | ~2989 |
| LLM TTFT | ms | ~42 |
| Image (warm) | seconds | ~10.8 |
| TTS | real-time factor | ~0.51 |

Detailed methodology in `PERFORMANCE_RESULTS.md` and
`RADEON_INFERENCE_OPTIMIZATION_REPORT.md`.

## Model Tuning Guide

See **[TUNING_GUIDE.md](TUNING_GUIDE.md)** for the complete tuning guide,
including:
- GPU monitoring with `rocm-smi`
- Baseline benchmark with `llama-bench`
- Parameter comparison table (Flash Attn, threads, GPU layers)
- API-level temperature tuning
- Production configuration

**Key result:** Q4_K_M + Flash Attention + 99 GPU layers = **93.32 tok/s**
generation speed on gfx1100 (48 GB VRAM).

## Client setup

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://PUBLIC_HOST/v1",
    api_key="sc_...",
    timeout=600,
)
```

Image generation is serialized on the single GPU; use a timeout of at
least 300 seconds.

The current `trycloudflare.com` URL is a temporary demo tunnel. Replace
with a named tunnel or direct HTTPS for production.

## Troubleshooting

See **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** for the complete list of 16
issues encountered during deployment, including:

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
