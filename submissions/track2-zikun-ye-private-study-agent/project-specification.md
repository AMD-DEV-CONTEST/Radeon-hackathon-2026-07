# Private Study Agent — Project Specification

## 1. Project Overview

Private Study Agent is a beginner-friendly AI study assistant for PDF learning materials. It provides a simple Streamlit interface through which users can upload a PDF, ask questions grounded in its content, generate a structured summary, and create a three-day study plan.

The application uses PyMuPDF to extract text from uploaded documents. It then sends a task-specific instruction, the user’s question when applicable, and the extracted document context to an OpenAI-compatible shared model API provided through AMD Radeon Cloud.

The current project represents a focused minimum viable product for an AMD Hackathon Track 2 submission: Development & Local Deployment of Private AI Agents. The application workflow has been deployed and tested in an AMD Radeon Cloud environment. However, the current version does not claim that complete large language model inference is running locally on a Radeon GPU.

## 2. Problem Statement

Students often work with long learning materials that are difficult to review efficiently. Locating relevant information, identifying key ideas, and turning course content into a practical study schedule can require significant manual effort.

General-purpose chatbots may also answer from general model knowledge instead of the uploaded document. This creates a risk of responses that are not supported by the learning material.

Private Study Agent addresses this problem by extracting content from a user-provided PDF and placing that content directly into a task-specific model request. The model is instructed to base its output on the supplied document and to state clearly when the document does not contain enough information.

## 3. Target Users

The primary target users are:

- Students reviewing lecture slides, course notes, and other PDF learning materials
- Learners who need quick summaries of educational documents
- Users who want a short, document-based study schedule
- Beginners who need a simple interface without complex knowledge-base configuration

The current MVP is designed for one uploaded, text-based PDF at a time.

## 4. Core Features

### 4.1 Grounded Question Answering

Users can enter a question about the uploaded PDF. The application sends the question together with the extracted document text and an instruction requiring the answer to be based on the PDF.

If the document does not provide sufficient information, the model is instructed to communicate that limitation clearly rather than invent an unsupported answer.

### 4.2 PDF Summary Generation

The application can generate a structured summary containing:

- A short overview
- Key ideas
- Important takeaways

The summary is generated from the extracted PDF content.

### 4.3 3-Day Study Plan Generation

The application can create a practical three-day study plan based on the uploaded material. Each day includes:

- Topics to study
- Suggested learning activities
- A clear learning goal

### 4.4 PDF Processing Pipeline

PDF processing is performed with PyMuPDF. The uploaded PDF is read in memory, text is extracted page by page, and the extracted pages are combined into a single document context.

The application validates that usable text has been extracted before enabling the model-assisted workflow. If no selectable text is found, the interface explains that the current MVP does not provide OCR for scanned PDFs.

For large documents, the application limits the model context to the first 60,000 extracted characters.

## 5. Agent Workflow

Private Study Agent uses a compact, task-oriented workflow rather than a multi-agent architecture.

The workflow is:

1. The user uploads one PDF through the Streamlit interface.
2. PyMuPDF extracts selectable text from each page.
3. The application verifies that usable document text was found.
4. The user selects one of three tasks:
   - Ask a question
   - Summarize the PDF
   - Generate a 3-day study plan
5. The application selects the corresponding task instruction.
6. The task instruction, optional user question, and PDF context are assembled into a model request.
7. The request is sent to the AMD Radeon Cloud OpenAI-compatible API.
8. The generated result is displayed in the Streamlit interface.
9. API, network, timeout, document, and response-format errors are presented as readable interface messages.

For large documents, the current implementation sends only the first 60,000 extracted characters to limit context usage.

## 6. System Architecture

```text
User Input
    ↓
Streamlit UI
    ↓
PDF Processing
(PyMuPDF text extraction)
    ↓
Agent Workflow
(task selection, instruction construction, context packaging)
    ↓
OpenAI-Compatible Model API
    ↓
Generated Result
    ↓
Streamlit UI
```

### Main Components

- **Streamlit UI:** Handles PDF upload, task selection, question input, progress indicators, results, and user-facing errors.
- **PDF Processing:** Uses PyMuPDF to extract text from the uploaded document in memory.
- **Agent Workflow:** Selects a task-specific instruction and combines it with the available document context.
- **API Client:** Uses Requests to call the AMD Radeon Cloud OpenAI-compatible chat completions endpoint.
- **Configuration:** Uses python-dotenv and the `AMD_API_KEY` environment variable for local configuration.

### Current API Configuration

- Base URL: `https://developer.amd.com.cn/radeon/api/v1`
- Endpoint: `/chat/completions`
- Configured model: `DeepSeek-V4-Flash`

The model name above reflects the fixed `MODEL_NAME` configuration currently present in `app.py`. The architecture diagram uses the generic component name “OpenAI-Compatible Model API” to describe the integration boundary.

## 7. AMD Radeon Cloud Integration

The project was deployed and tested on an AMD Radeon Cloud instance.

Deployment verification included:

- Creating an active Radeon Cloud instance with one GPU
- Deploying the project files into the instance environment
- Creating and activating a Python virtual environment
- Installing the dependencies from `requirements.txt`
- Starting the Streamlit service on port 8501
- Verifying the backend health endpoint successfully
- Opening the Streamlit interface through an SSH tunnel
- Testing PDF upload, grounded question answering, summary generation, and three-day study plan generation in the cloud-hosted application

Deployment evidence is available in the repository:

- `assets/radeon-instance.png`
- `assets/radeon-streamlit-start.png`
- `assets/radeon-health-check.png`
- `assets/radeon-websocket-limit.png`

The Streamlit service started successfully, and the internal backend health endpoint returned `ok`. The direct Radeon Cloud public route was affected by reverse proxy WebSocket handling, so a verified SSH tunnel was used to forward the cloud service to a local browser. Through this tunnel, the Streamlit interface opened successfully and the three model-assisted study functions were tested successfully.

The reverse proxy issue affects the direct public access path and does not indicate an error in the application’s core implementation. The SSH tunnel is a private access method for the computer holding the matching SSH key; it is not a public application URL.

The current model generation flow uses an OpenAI-compatible shared model API. The project does not claim that the complete DeepSeek-V4-Flash inference workload is served locally from the tested Radeon GPU instance, and no completed ROCm local inference implementation is claimed.

## 8. Privacy and Security

PDF text extraction is performed inside the running application environment using PyMuPDF. The uploaded file is read in memory and is not intentionally written to a project database or permanent application storage by the current implementation.

For model-assisted features, extracted PDF text is included in the request sent to the AMD Radeon Cloud OpenAI-compatible shared model API. Therefore, the current MVP should not be described as a fully offline or fully local inference system.

Security measures in the current repository include:

- The API key is read only from the `AMD_API_KEY` environment variable.
- The API key is not hard-coded in `app.py`.
- Local credentials are stored in `.env`.
- `.env` and `.venv/` are excluded through `.gitignore`.
- The application does not display the API key.
- No API keys or passwords are included in the repository.
- API and network failures are converted into user-facing error messages.
- The SSH private key remains on the user's local computer and is not stored in the repository or Radeon Cloud Profile.
- Only the corresponding SSH public key is saved in the Radeon Cloud Profile.

Users should avoid uploading highly sensitive documents unless the shared API’s data-handling terms are appropriate for their use case.

## 9. Limitations

The current MVP has the following limitations:

- It supports one PDF at a time.
- It supports text-based PDFs but does not include OCR for scanned documents.
- Only the first 60,000 extracted characters are sent for large PDFs.
- The current MVP uses direct document context processing: extracted PDF text is placed directly into the model request instead of being indexed and retrieved through a vector-based retrieval pipeline.
- It does not provide document citations or page-level source references.
- It does not include user accounts, persistent memory, or multi-agent collaboration.
- Model generation depends on a remote OpenAI-compatible shared API.
- Complete local Radeon GPU inference has not been implemented.
- The direct Radeon Cloud public route was limited by reverse proxy WebSocket handling. Interactive use was successfully verified through a private SSH tunnel, which requires the matching local SSH key and is not a public deployment URL.

These limitations reflect the intentionally small scope of the hackathon MVP.

## 10. Future Work

Planned future work includes:

- Exploring ROCm-compatible local model serving on AMD Radeon GPU infrastructure
- Measuring and optimizing model latency, memory usage, and throughput on AMD hardware
- Replacing or supplementing the shared API with controlled local inference
- Extending direct document context processing with retrieval for larger documents and more relevant context selection
- Adding page-level citations and source references
- Supporting OCR for scanned PDFs
- Expanding task planning and tool use beyond the current fixed workflow
- Adding optional user-controlled memory and study-progress tracking
- Improving cloud deployment so external browser access does not require an SSH tunnel
- Evaluating stronger privacy controls for sensitive educational documents

The next major technical milestone is to deploy a compatible model-serving stack in an AMD ROCm environment and connect the existing agent workflow to that local endpoint.
