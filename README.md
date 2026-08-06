# Autonomous Codebase Architect: Agentic Repo Analysis Powered by AMD ROCm

An autonomous codebase analysis agent powered by a LangGraph ReAct loop and Chroma RAG, running heavily optimized quantized LLM inference via vLLM on AMD Radeon GPUs.

---

## 🚀 Demo

### UI Dashboard

Streamlit interface streaming the ReAct planner's execution and dynamic architecture generation.


### Live Radeon Telemetry

Terminal view showing `rocm-smi` hardware monitoring during active inference.


---

## ✨ Features

- 🤖 **Agentic Orchestration**
  - LangGraph-powered ReAct loop (Reasoning & Acting)
  - Autonomous repository cloning
  - Intelligent tool selection
  - Multi-step reasoning

- 📚 **Deep Codebase Extraction**
  - Python AST parsing
  - Dependency graph generation
  - Chroma vector database for Retrieval-Augmented Generation (RAG)
  - Context-aware code retrieval

- ⚡ **AMD Hardware Acceleration**
  - ROCm backend support
  - Optimized inference on AMD Radeon GPUs
  - Production-ready vLLM serving

- 💾 **Extreme VRAM Efficiency**
  - AWQ 4-bit quantization
  - Reduced memory footprint
  - Increased memory bandwidth utilization

- 📈 **Live GPU Telemetry**
  - Real-time `rocm-smi` monitoring
  - GPU utilization
  - VRAM usage
  - Temperature tracking

---

## 🏗️ Project Architecture

```text
            [User Request]
                  │
                  ▼
       [Streamlit Interface]
                  │
                  ▼
      [LangGraph ReAct Loop]
           │            │
           │            ▼
           │    [AST Parser]
           │            │
           │            ▼
           │      [ChromaDB]
           │            ▲
           └────────────┘
                  │
                  ▼
   [vLLM OpenAI-Compatible API]
                  │
                  ▼
           [ROCm Backend]
                  │
                  ▼
      [AMD Radeon / Instinct GPU]
```

---

## 📁 Folder Structure

```text
.
├── .gitignore
├── README.md
├── requirements.txt
└── src/
    ├── agent.py
    ├── graph.py
    └── main.py
```

---

## ⚙️ Prerequisites

### Software

- Python 3.11 or 3.12
- ROCm 6.0+ (Recommended: ROCm 7.0)

### Hardware

- AMD Radeon RX 7000 Series
- AMD Radeon PRO GPUs
- AMD Instinct MI-Series GPUs

### Operating System

- Ubuntu 22.04+
- Fedora
- Radeon Cloud Platform

---

## 🛠️ Installation

### 1. Clone the repository


### 2. Create a virtual environment

```bash
python -m venv env

source env/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 🚀 Running the Project

Launch the Streamlit application:

```bash
streamlit run src/app.py
```

---

## 🔍 GPU Verification

Verify that inference is running on the AMD GPU.

Run the following command in another terminal:

```bash
watch -n 0.5 rocm-smi
```

### Expected Output During Inference

```text
GPU Utilization : 57%
VRAM Used       : 5.8 GB
Temperature     : 64°C
```

---

## 📊 Performance Benchmarks

| Metric | Value |
|---------|-------|
| Hardware | AMD Radeon PRO / Radeon Cloud |
| Model | Qwen 2.5 Coder 7B (AWQ) |
| Backend | vLLM (ROCm) |
| Quantization | 4-bit AWQ |
| Peak GPU Utilization | 89% |
| VRAM Footprint | ~5.8 GB |
| Average Tokens/sec | 65 t/s |

---

## 💡 Example Usage

### User Prompt

```text
Analyze this repository:

https://github.com/example/repo

Explain its authentication flow.
```

### Agent Execution

1. Clone repository
2. Build Abstract Syntax Tree (AST)
3. Index code into ChromaDB
4. Retrieve authentication-related code
5. Generate architecture summary

### Example Response

```text
Based on the retrieved context, the application uses a
JWT-based authentication flow located in src/auth.py.

When a user posts to /login, the verify_password()
function validates the password hash before generating
a signed JWT token returned to the client.
```

---

## 🔐 Configuration

Copy the environment template:

```bash
cp .env.example .env
```

Edit the `.env` file:

```env
RADEON_BASE_URL=https://radeon-global.anruicloud.com/spaces/<YOUR_ID>/8000/v1

RADEON_API_KEY=your_api_key_here
```

---

# ⚡ AMD Optimization (Hackathon Focus)

This project is designed specifically to showcase the AMD AI software ecosystem.

### 🚀 vLLM + ROCm

Instead of using traditional inference frameworks such as `llama.cpp`, this project connects to a dedicated **vLLM server compiled for ROCm**, closely matching enterprise deployment workflows.

### 💾 AWQ Quantization

The model is served using **4-bit AWQ quantization**, reducing VRAM usage from approximately **14 GB** to **5.8 GB**.

Because LLM inference is primarily memory-bandwidth bound, this reduction allows Radeon GPUs to move model weights significantly faster, improving throughput while maintaining high-quality responses.

### 🐳 Radeon Cloud Ready

The application runs directly on the **AMD Radeon Cloud One-Click Base Container**, providing:

- Zero dependency conflicts
- Native ROCm support
- Immediate GPU acceleration

---

## 🔧 Troubleshooting

### Issue

**404 Instance pod not found**

**Solution**

- Ensure the Radeon Cloud instance is running.
- Verify the deployment type is **vLLM Model API**.
- Wait until the instance is fully active.
- Confirm that `RADEON_BASE_URL` matches the current deployment.

---

### Issue

**High latency or model stalls during startup**

**Solution**

The server is likely downloading model weights from Hugging Face.

You can:

- Monitor progress from the Technical Details panel.
- SSH into the container to view download progress.
- Enable Persistent Volume (PVC) storage to cache model weights across restarts.

---

## 🔮 Future Work

- 🤖 Multi-agent architecture for specialized repository analysis
- 🚀 Multi-GPU tensor parallelism using vLLM
- 🧠 GraphRAG using Neo4j for structural code understanding
- 📈 Interactive architecture visualization
- 📝 Automatic documentation generation
- 🔍 Cross-repository semantic search

---

## 🙌 Acknowledgements

This project builds upon the following open-source technologies:

- AMD ROCm
- vLLM
- LangGraph
- LangChain
- ChromaDB
- Streamlit

---

## 📄 License

This project is licensed under the **MIT License**.

---

## ✍️ Author

**Siddhartha**

GitHub: **https://github.com/YourGitHubUsername**
