# 📚 Local Research Assistant

A fully local Retrieval-Augmented Generation (RAG) system for chatting with PDF research papers. Runs entirely on your machine with AMD GPU acceleration via ROCm.

## Features

- ✅ **100% Local** - No cloud APIs, all data stays private
- ✅ **AMD ROCm Support** - GPU-accelerated embeddings
- ✅ **PDF Processing** - Extract text from research papers
- ✅ **RAG Pipeline** - Retrieve + Generate with citations
- ✅ **Chat Interface** - Gradio UI with streaming responses
- ✅ **Source Transparency** - See which chunks were retrieved

## Quick Start

### 1. Install ROCm (AMD GPU)

```bash
# Ubuntu 22.04/24.04
wget https://repo.radeon.com/amdgpu-install/6.2/ubuntu/jammy/amdgpu-install_6.2.60200-1_all.deb
sudo apt install ./amdgpu-install_6.2.60200-1_all.deb
sudo amdgpu-install -y --usecase=rocm
sudo usermod -aG render,video $LOGNAME
sudo reboot
```

### 2. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
```

### 3. Install Python Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Run the App

```bash
python main.py
```

Open `http://localhost:7860` in your browser.

## Project Structure

```
research-assistant/
├── main.py
├── config.py # Configuration
├── app/
│ ├── embeddings.py # Embedding model (ROCm-aware)
│ ├── vectorstore.py # ChromaDB setup
│ ├── ingestion.py # PDF → chunks → embeddings
│ ├── retrieval.py # Query → relevant chunks
│ ├── generation.py # Ollama API + RAG prompt
│ └── ui.py # Gradio interface
├── uploads/ # Uploaded PDFs
├── chroma_db/ # Vector database
└── requirements.txt
```

## How It Works

1. **Upload PDFs** → Text extracted with PyPDF2
2. **Chunking** → Split into 800-char chunks (200 tokens)
3. **Embeddings** → `all-MiniLM-L6-v2` on AMD GPU
4. **Vector Store** → ChromaDB persists to disk
5. **Query** → Retrieve top-3 relevant chunks
6. **RAG Prompt** → Combine context + history + question
7. **Generation** → Stream response from Ollama (Llama 3.2)

## Troubleshooting

### No GPU detected

```bash
# Check ROCm
rocminfo
rocm-smi

# Verify PyTorch sees GPU
python -c "import torch; print(torch.cuda.is_available())"
```

### Ollama connection error

```bash
ollama serve
ollama pull llama3.2
```

## License

MIT - Built for hackathons and learning.
