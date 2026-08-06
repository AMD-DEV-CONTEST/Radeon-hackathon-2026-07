# Private Study Agent

**Track:** Track 2 - Development & Local Deployment of Private AI Agents  
**Participant:** Zikun Ye (individual participant)  
**Project:** Private Study Agent  
**Source repository:** https://github.com/xmolly929/private-study-agent-amd

## Project Overview

Private Study Agent is a beginner-friendly AI study assistant for PDF learning
materials. It extracts text from an uploaded PDF, builds a task-specific request,
and provides study support grounded in the supplied document.

## Core Capabilities

- Grounded question answering based on uploaded PDF content
- PDF summary generation
- Three-day study plan generation
- Clear handling when the document does not contain enough information

## Agent Workflow

```text
User uploads PDF
        |
        v
Streamlit user interface
        |
        v
PyMuPDF text extraction
        |
        v
Task-specific agent workflow
        |
        v
AMD Radeon Cloud OpenAI-compatible shared model API
        |
        v
Grounded study-support output
```

## AMD Radeon Cloud Deployment

The application was deployed and tested on an AMD Radeon Cloud instance. The
verified deployment included environment setup, dependency installation,
Streamlit startup, backend health verification, and interactive use through an
SSH tunnel.

The PDF processing and Streamlit application run in the Radeon Cloud instance.
Model generation currently uses the AMD Radeon Cloud OpenAI-compatible shared
model API. This submission does not claim that complete large language model
inference is served locally from the tested Radeon GPU instance.

## Submission Materials

- [Project specification](project-specification.md)
- [Supplementary presentation](Private-Study-Agent-Hackathon-Presentation.pptx)
- [Demo video information](demo-video.md)
- [Complete project README](PROJECT_README.md)
- [Complete source code](https://github.com/xmolly929/private-study-agent-amd)
- [Full project README and reproduction guide](https://github.com/xmolly929/private-study-agent-amd/blob/main/README.md)

## Reproduction

The complete verified local and AMD Radeon Cloud deployment instructions are in
the project repository README:

https://github.com/xmolly929/private-study-agent-amd#amd-radeon-cloud-deployment

The minimal local development flow is:

```powershell
git clone https://github.com/xmolly929/private-study-agent-amd.git
cd private-study-agent-amd
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Set `AMD_API_KEY` in `.env` before launching the application. The real key is
not included in either repository.

## Privacy and Security

- Uploaded PDFs are parsed with PyMuPDF in the application environment.
- Extracted document context is sent to the configured shared model API for the
  requested model-assisted operation.
- API credentials are loaded from `AMD_API_KEY` and are never hard-coded.
- `.env`, virtual environments, caches, and private source documents are
  excluded from the public repository.

## Current Limitations

- The MVP supports text-based PDFs and does not include OCR for scanned pages.
- Direct document context processing is used instead of a vector retrieval
  pipeline.
- Long PDF input is limited to the first 60,000 extracted characters.
- Model generation requires access to the shared OpenAI-compatible API.
- Complete local Radeon GPU model inference and measured GPU inference
  optimization are future work, not claims of the current submission.
- The direct Radeon Cloud public route was affected by reverse proxy WebSocket
  handling; interactive use was successfully verified through an SSH tunnel.
