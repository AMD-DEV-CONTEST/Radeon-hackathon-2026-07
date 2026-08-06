# Qwen3.6-35B-A3B Q4_K_M Installation Guide on AMD W7900

This document records the actual download, installation, startup, and verification process of `Qwen3.6-35B-A3B-Q4_K_M.gguf` on an AMD Radeon PRO W7900 48GB host, and provides reusable deployment commands.

## 1. Final Deployment Results

| Item | Value |
|---|---|
| Model | Qwen3.6-35B-A3B |
| Quantization Format | GGUF Q4_K_M |
| Model Repository | `ggml-org/Qwen3.6-35B-A3B-GGUF` |
| Model File | `Qwen3.6-35B-A3B-Q4_K_M.gguf` |
| File Size | `20,419,565,568` bytes |
| GPU | AMD Radeon PRO W7900 48GB, `gfx1100` |
| ROCm | 7.2.1 |
| Inference Backend | llama.cpp ROCm build |
| llama.cpp Version | `b10217-ddd4ec142` |
| Native Context | `262144` tokens |
| API | OpenAI-compatible Chat Completions API |
| Local Listen Address | `http://127.0.0.1:8000` |
| Model VRAM Usage | ~26GB (Native 256K context, single slot) |
| Short Text Generation Speed | ~88–92 tokens/s |
| 40K-token Prompt Processing Speed | ~1,605 tokens/s |

Final model file location:
```text
/root/models/qwen3.6-35b-a3b-q4_k_m/Qwen3.6-35B-A3B-Q4_K_M.gguf
```

## 2. Why FP8 Was Not Used

Before this deployment, we downloaded and attempted to use the official FP8 model:
```text
Qwen/Qwen3.6-35B-A3B-FP8
```

The FP8 weights are approximately 35GB, which can fit into the 48GB VRAM. However, the current GPU architecture is `gfx1100`, and the ROCm version of vLLM has no available backend when loading the FP8 MoE, causing the startup to fail with:
```text
NotImplementedError: No FP8 MoE backend supports the deployment configuration.
```

Therefore, we chose the GGUF Q4_K_M version supported by llama.cpp. This version is approximately 20.4GB, fits completely into a single W7900, and has good inference speeds on this machine.

## 3. Install Hugging Face CLI

To avoid polluting the system Python, use an independent virtual environment:
```bash
python3 -m venv /root/.venvs/hf
/root/.venvs/hf/bin/pip install --upgrade pip huggingface_hub
```

Verify the client:
```bash
/root/.venvs/hf/bin/hf --version
```

If the host cannot stably connect to `huggingface.co` directly, use a Hugging Face mirror and disable the Xet client:
```bash
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DISABLE_XET=1
```

## 4. Download the Model

### 4.1 Create Model Directory
```bash
mkdir -p /root/models/qwen3.6-35b-a3b-q4_k_m
```

### 4.2 Use aria2 for Resumable Download
Install the downloader:
```bash
apt-get update
apt-get install -y aria2
```

Navigate to the model directory:
```bash
cd /root/models/qwen3.6-35b-a3b-q4_k_m
```

Download using the mirror address (using an auto-reconnect loop to handle CDN drops):
```bash
while true; do
  timeout 35 aria2c \
    -c -x 4 -s 4 -k 4M \
    --max-tries=0 \
    --retry-wait=3 \
    --file-allocation=none \
    -o Qwen3.6-35B-A3B-Q4_K_M.gguf \
    'https://hf-mirror.com/ggml-org/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-Q4_K_M.gguf?download=true'

  test ! -e Qwen3.6-35B-A3B-Q4_K_M.gguf.aria2 && break
  sleep 2
done
```

### 4.3 Verify the File
Check the file size:
```bash
stat -c '%n %s bytes' /root/models/qwen3.6-35b-a3b-q4_k_m/Qwen3.6-35B-A3B-Q4_K_M.gguf
```
Expected result:
```text
20419565568 bytes
```

## 5. Install ROCm Version of llama.cpp

Use the official llama.cpp installation script. Since the official binary download URL also depends on Hugging Face, replace `huggingface.co` with `hf-mirror.com` in the script.

```bash
curl -fsSL https://llama.app/install.sh -o /tmp/llama-install.sh
sed -i 's/huggingface\.co/hf-mirror.com/g' /tmp/llama-install.sh
LLAMA_VERSION=b10217 bash /tmp/llama-install.sh
```

The installer correctly identifies ROCm 7.2.1 and `gfx1100`, downloading the matching ROCm build without requiring local compilation from source.

## 6. Start the Model Service

### 6.1 Native 256K Context Startup Command
```bash
cd /root/models/qwen3.6-35b-a3b-q4_k_m
: > server.log

setsid /root/.local/bin/llama serve \
  -m /root/models/qwen3.6-35b-a3b-q4_k_m/Qwen3.6-35B-A3B-Q4_K_M.gguf \
  -ngl 99 \
  -c 262144 \
  -np 1 \
  --host 127.0.0.1 \
  --port 8000 \
  >> server.log 2>&1 < /dev/null &

echo $!
```

**Parameters Explained:**
- `-m`: GGUF model path
- `-ngl 99`: Offload all possible model layers to the GPU
- `-c 262144`: Use the model's native 256K context from training
- `-np 1`: Set a single inference slot
- `--host 127.0.0.1`: Bind to localhost to avoid unauthorized public exposure
- `--port 8000`: OpenAI-compatible API port

### 6.2 View Startup Logs
```bash
tail -f /root/models/qwen3.6-35b-a3b-q4_k_m/server.log
```
Expected output upon success:
```text
n_ctx_slot = 262144
model loaded
listening on http://127.0.0.1:8000
```

## 7. API Verification

### 7.1 Health Check
```bash
curl http://127.0.0.1:8000/health
```
Expected result: `{"status":"ok"}`

### 7.2 Chinese Chat Test
```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.6-35b-a3b-q4_k_m",
    "messages": [
      {
        "role": "user",
        "content": "你好，请只回复：模型测试成功"
      }
    ],
    "max_tokens": 64,
    "temperature": 0,
    "chat_template_kwargs": {
      "enable_thinking": false
    }
  }'
```

`Qwen3.6-35B-A3B` defaults to reasoning. If you only need a direct answer, you must set `"enable_thinking": false`.

## 8. SSH Tunnel Access

The service only listens on `127.0.0.1:8000` of the remote host. You can establish an SSH tunnel from your local machine:
```bash
ssh -L 8000:127.0.0.1:8000 root@<YOUR_REMOTE_IP> -p <YOUR_SSH_PORT>
```

## 9. Benchmark Results

| Test | Result |
|---|---:|
| General Generation | ~88–92 tokens/s |
| Short Prompt Processing | ~85–480 tokens/s |
| 40,021-token Prompt | ~1,605 tokens/s |
| 40K-token Total Request Time | ~25 seconds |
| GPU Stress Test Peak Power | ~193W |

## 10. Conclusion

In an AMD Radeon PRO W7900 48GB, ROCm 7.2.1, `gfx1100` environment:
- The official FP8 MoE weights fit in VRAM, but the current vLLM/ROCm backend does not support this combination.
- GGUF Q4_K_M can be fully loaded onto a single GPU using the ROCm version of llama.cpp.
- The model successfully uses a native 262,144-token context window.
- Single-request generation speed reaches approximately 88–92 tokens/s.
