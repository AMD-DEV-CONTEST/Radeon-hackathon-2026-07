# Rocm Reproduce Steps


## 1. Install llama.cpp
Choose image: amd-oneclick-base:git-proxy-test-20260528-1125
```
apt update
apt install -y git cmake build-essential
cd /workspace
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
HIPCXX="$(hipconfig -l)/clang" HIP_PATH="$(hipconfig -R)" cmake -S . -B build  -DGGML_HIP=ON  -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j"$(nproc)"

# Confirm that the HIP version has been compiled
./build/bin/llama-cli --list-devices

# Download vision model
./build/bin/llama cli -hf mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K

# Exit and start LLM service
/exit
./build/bin/llama serve \
  -hf mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K \
  --mmproj-url "https://hf-mirror.com/mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-GGUF/resolve/main/Qwen3.6-35B-A3B-Fable-5-Distill.mmproj-f16.gguf" \
  -ngl 999 \
  -c 32768 \
  --flash-attn on \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --host 0.0.0.0 \
  --port 8000
```


## 2.Pull the code
```
git clone --branch submission/track2-dale --single-branch https://github.com/ld0574/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07

uv sync --frozen --extra semantic --extra dev

uv sync --frozen --extra semantic
```

## 3. Configure Production Secrets

```
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

Paste the generated 64-character value into `XIANG_APP_API_KEY`. A production `.env` should contain
these values:

```
# Application
XIANG_APP_ENV=production
XIANG_DEPLOYMENT_MODE=submission-local
XIANG_HOST=127.0.0.1
XIANG_PORT=8080
XIANG_LOG_LEVEL=INFO

# Browser authentication. The permanent key never leaves this machine.
XIANG_AUTH_ENABLED=true
XIANG_APP_API_KEY=PASTE_64_RANDOM_HEX_CHARACTERS_HERE
XIANG_PUBLIC_SESSIONS_ENABLED=true
XIANG_ACCESS_TOKEN_TTL_MINUTES=20
XIANG_SESSION_ISSUE_LIMIT_PER_MINUTE=10

# Private llama.cpp connection on the same Radeon host.
XIANG_LLM_BASE_URL=http://127.0.0.1:8000/v1
XIANG_LLM_API_KEY=
XIANG_LLM_MODEL=mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K
XIANG_LLM_TIMEOUT_SECONDS=300
XIANG_LLM_PROBE_ON_START=false
XIANG_LLM_ENABLE_THINKING=true
XIANG_LLM_REASONING_BUDGET=4096

# Local state
XIANG_SQLITE_PATH=./runtime/xianglens.sqlite3
XIANG_MILVUS_URI=./runtime/xianglens_milvus.db
XIANG_UPLOAD_DIR=./runtime/uploads
XIANG_EXPORT_DIR=./runtime/exports
XIANG_IMAGE_RETENTION=session
XIANG_SESSION_TTL_MINUTES=60

# Semantic retrieval
XIANG_EMBEDDING_PROVIDER=fastembed
XIANG_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
XIANG_EMBEDDING_DIMENSION=384
XIANG_RAG_TOP_K=4

# The origin has no repository path component.
XIANG_ALLOWED_ORIGINS=https://ld0574.github.io
```

## 4. Build the Production Knowledge Database

FastEmbed downloads its model on the first build:

```bash
XIANG_EMBEDDING_PROVIDER=fastembed \
  uv run python scripts/build_knowledge_db.py --provider fastembed
```

Run the retrieval smoke suite using the same production configuration:

```bash
uv run python scripts/run_rag_smoke.py
```
Will show: All 8 RAG smoke queries passed.

## 5. Start XiangLens FastAPI
```
mkdir -p /workspace/xianglens-logs

nohup ./scripts/start_api.sh \
  > /workspace/xianglens-logs/xianglens-api.log 2>&1 &

echo $! > /workspace/xianglens-logs/xianglens-api.pid

# Test FastAPI health
curl --fail http://127.0.0.1:8080/health

#
```

## 6. Install frp 
Open a new terminal.
```
/var/run/secrets/frp-self-service/install
# Open a new terminal
export PATH="$HOME/.local/bin:$PATH"
# Expose 8080 port
"$HOME/.local/bin/rc-tunnel" expose --port 8080
# Will display url like xxxxxx.radeon.firstdg.ai
```

## 7. Frontend 
Open <https://ld0574.github.io/Radeon-hackathon-2026-07/> and paste the API server into the override api base url input.

You can test this agent. 
Example images in `data/case` folder.
Enjoy~ 