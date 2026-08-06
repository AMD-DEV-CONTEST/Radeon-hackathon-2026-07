# 1. llama-server (PrismML fork)
Download the pre-built binaries of PrismML fork of llama.cpp
```bash
curl -L -o /workspace/llama-rocm.tar.gz   "https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b9570-0ad1dab/llama-prism-b9570-0ad1dab-bin-ubuntu-rocm-7.2-x64.tar.gz"
cd /workspace
tar xzf llama-rocm.tar.gz
```

Download the models:
```bash
curl -L -C -  "https://hf-mirror.com/prism-ml/Ternary-Bonsai-27B-gguf/resolve/main/Ternary-Bonsai-27B-Q2_0.gguf" -o /workspace/end2end_xray/backend/models/chat/Ternary-Bonsai-27B-Q2_0.gguf
```
and
```bash
curl -L -C -  "https://hf-mirror.com/prism-ml/Ternary-Bonsai-27B-gguf/resolve/main/Ternary-Bonsai-27B-mmproj-Q8_0.gguf" -o /workspace/end2end_xray/backend/models/chat/Ternary-Bonsai-27B-mmproj-Q8_0.gguf
```

Start the AMD-optimized llama backend:
```bash
/workspace/llama-prism-b9570-0ad1dab/llama-server -m /workspace/end2end_xray/backend/models/chat/Ternary-Bonsai-27B-Q2_0.gguf --mmproj /workspace/end2end_xray/backend/models/chat/Ternary-Bonsai-27B-mmproj-Q8_0.gguf --host 127.0.0.1 --port 8082 -ngl 999 -c 8192 --jinja --chat-template-kwargs '{"enable_thinking":false}' --reasoning-format none
```

# 2. FastAPI backend (in another terminal)
On first installation: Create a conda environment and install dependencies
```bash
conda create -n e2e python=3.11.15 anaconda
pip install -r ./backend/requirements.txt
```
Start the backend:
```bash
cd /workspace/end2end_xray/backend
export CHAT_OPENAI_BASE_URL=http://127.0.0.1:8082/v1
export CHAT_OPENAI_MODEL=Ternary-Bonsai-27B-Q2_0.gguf
conda activate e2e
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```


#  3. Frontend (new terminal)
```bash
cd frontend
npm install
npm start
```
