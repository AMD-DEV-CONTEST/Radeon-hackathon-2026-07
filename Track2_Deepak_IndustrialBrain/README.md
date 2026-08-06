# IndusMind AI - Final Project 

**Industrial Asset Intelligence & RCA Copilot**

IndusMind AI converts fragmented maintenance records, inspection reports, OEM guidance, safety procedures, and operating data into a searchable industrial knowledge layer. It answers natural-language questions with exact source citations, builds an Asset 360° history, and creates evidence-linked root-cause investigation briefs.

> **Team Presentation Ready**: This project is optimized for a 5-minute technical presentation. See `IndusMind_Final_Presentation.pptx` and `PRESENTATION_SCRIPT.md` for the slides and script.

##  Key Features

- **Fine-Tuned LLaMA-3 (LoRA)**: Completely offline, fast, and secure 4-bit local inference powered by our custom PyTorch LoRA adapter.
- **Evidence-First RAG**: Natural language answers backed by exact source document, page, and excerpt citations via a local ChromaDB vector database.
- **Asset 360° View**: Connects failures, measurements, maintenance actions, and dates.
- **RCA Intelligence**: Separates observations, probable contributors, and investigation steps.
- **Fully Local Architecture**: No cloud dependencies. All data and AI inference stay securely on your local network.

##  Technology Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 19, TypeScript, Vite, Tailwind-like custom CSS |
| **Backend API** | Java 21, Spring Boot 3.5, Spring Security, JWT, PostgreSQL/H2 |
| **AI Brain** | Python 3.12, FastAPI, PyTorch, HuggingFace transformers, peft, bitsandbytes |
| **AI Model** | LLaMA-3 8B (4-bit quantized) + Industrial LoRA Adapter |
| **Vector DB** | ChromaDB (Persistent Local Mode) |

##  How to Run the Demo

To run the project perfectly for the presentation tomorrow, we have configured a 1-click startup script that starts everything in optimized mode.

1. Open **PowerShell** in this repository's root folder.
2. Run the start script:
   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-all.ps1 -DemoMode
   ```
3. Open your browser to [http://localhost:5173](http://localhost:5173).

*(Note: The first time you ask a question, the local LLaMA-3 AI will take a few seconds to load into the GPU. Subsequent questions will be extremely fast!)*

### Demo Accounts
| Role | Username | Password |
|---|---|---|
| Engineer | `engineer` | `Engineer@123` |
| Admin | `admin` | `Admin@123` |

### Try asking the AI:
> "Why did Pump P-101 fail repeatedly?"
> "What safety steps apply before pump maintenance?"

##  Stopping the Services
When the presentation is over, cleanly shut down the AI, Backend, and Frontend by running:
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-all.ps1
```

##  Repository Structure
- `frontend/` - React application
- `backend/` - Spring Boot API and security
- `ai-service/` - FastAPI RAG, ChromaDB, and Local LLM inference code
- `model-lora-output/` - The fine-tuned LLaMA-3 LoRA adapter weights
- `sample-data/` - Synthetic industrial demonstration corpus
- `scripts/` - Automated setup and startup scripts
- `generate_ppt.py` - Script used to generate the PowerPoint presentation
