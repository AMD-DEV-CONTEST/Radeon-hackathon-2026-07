# 🚀 AgentFlow AI

> **Offline Multi-Agent AI Assistant for Private Document Intelligence**

<p align="center">
  <strong>AMD AI DevMaster Hackathon 2026</strong><br>
  Track 2 – Development & Local Deployment of Private AI Agents
</p>

---

## 📖 Overview

AgentFlow AI is an **offline, privacy-first multi-agent AI assistant** designed to provide intelligent document understanding without relying on cloud services.

The application enables users to upload PDF documents, build a local knowledge base, ask questions, generate summaries, and maintain conversation memory—all while keeping data on the local machine.

The system uses a collaborative multi-agent architecture powered by **Ollama**, **FastAPI**, **React**, and **Retrieval-Augmented Generation (RAG)**.

---

# ✨ Key Features

- 🤖 Multi-Agent AI Architecture
- 📄 PDF Upload & Processing
- 🔍 Retrieval-Augmented Generation (RAG)
- 🧠 Conversation Memory
- 📚 Local Knowledge Base using ChromaDB
- 💬 Intelligent Question Answering
- 📝 Automatic Document Summarization
- 🔒 100% Offline Processing
- ⚡ Local LLM using Ollama
- 🎨 Modern React Dashboard

---

# 🏗️ System Architecture

```text
                User

                  │

                  ▼

          React Frontend

                  │

                  ▼

          FastAPI Backend

                  │

                  ▼

           Planner Agent

                  │

      ┌──────────┼──────────┐

      ▼          ▼          ▼

 Research     Memory      Tool

   Agent       Agent      Agent

      └──────────┼──────────┘

                  ▼

          Reviewer Agent

                  │

                  ▼

      Ollama (Qwen2.5:3B)

                  │

                  ▼

          Final AI Response
```

---

# 🔄 Workflow

1. Upload a PDF document.
2. Extract and process document text.
3. Generate embeddings.
4. Store vectors in ChromaDB.
5. User submits a query.
6. Planner Agent creates an execution plan.
7. Research Agent retrieves relevant context.
8. Memory Agent recalls previous conversations.
9. Tool Agent performs supporting operations.
10. Reviewer Agent validates the response.
11. Final answer is displayed.

---

# 💻 Technology Stack

## Frontend

- React
- Vite
- Tailwind CSS

## Backend

- FastAPI
- Python

## AI Stack

- Ollama
- Qwen2.5:3B

## Vector Database

- ChromaDB

## Database

- SQLite

---

# 📂 Project Structure

```text
agentflow-ai/
│
├── app/
├── docs/
├── runtime_data/
├── sample_data/
├── src/
├── tests/
├── AgentFlow AI.pdf
├── AgentFlow AI.pptx
├── amd hackathon.mp4
├── README.md
├── package.json
└── requirements.txt
```

---

# ⚙️ Installation

### Clone Repository

```bash
git clone https://github.com/ARYARAJINIKANTH/Radeon-hackathon-2026-07.git
```

---

### Backend

```bash
cd agentflow-ai
pip install -r requirements.txt
```

---

### Start Ollama

```bash
ollama serve
```

---

### Pull Model

```bash
ollama pull qwen2.5:3b
```

---

### Run Backend

```bash
py -m uvicorn app.main:app --reload
```

---

### Run Frontend

```bash
npm install
npm run dev
```

---

# 🚀 Demo

### Application Features

- Upload PDF Documents
- Intelligent Question Answering
- AI Document Summarization
- Multi-Agent Collaboration
- Local Knowledge Retrieval
- Offline AI Inference

---

# 🎥 Demo Video

📹 Demo video is included in this repository:

**amd hackathon.mp4**

---

# 📄 Project Documentation

- 📘 Project Specification → **AgentFlow AI.pdf**
- 📊 Presentation → **AgentFlow AI.pptx**

---

# 🔐 Privacy

AgentFlow AI performs all inference locally using Ollama.

No document data is sent to cloud AI services.

This makes the application suitable for:

- Enterprise
- Government
- Healthcare
- Education
- Legal Organizations

---

# ⚡ AMD Optimization

The application is designed for local deployment and can be executed on compatible AMD Radeon GPUs using ROCm to accelerate local inference.

The demonstration included in this repository was developed and tested on the available local development hardware while maintaining the same architecture for future AMD GPU deployment.

---

# 🎯 Future Improvements

- 🎙 Voice Assistant
- 🖼 Multi-modal AI
- 📚 Multi-document Reasoning
- 🧠 Better Agent Collaboration
- ⚡ Enhanced GPU Optimization
- 🏢 Enterprise Deployment

---

# 👨‍💻 Developer

**Arya R**

BE Computer Science & Engineering (AI & ML)

VSB Engineering College

AMD AI DevMaster Hackathon 2026

Track 2 – Development & Local Deployment of Private AI Agents

---

# ⭐ Thank You

Thank you to **AMD AI DevMaster Hackathon 2026** for providing the opportunity to build and showcase **AgentFlow AI**.
