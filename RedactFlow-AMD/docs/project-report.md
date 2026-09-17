# RedactFlow AMD — Project Report

## Project background

Public communications are often assembled from private operational documents. These sources can contain personal contact details, internal network addresses, API keys, identity numbers, and unapproved statements. Copying them into a remote general-purpose assistant creates both privacy risk and a weak audit trail.

RedactFlow AMD is a local release-review agent that converts this task into a visible, permissioned workflow. It retrieves relevant passages from an on-device vault, scans for sensitive values, pauses before any transformation, generates release-safe copies, and records a minimal audit memory.

## Target users and scenarios

- Security and incident-response teams preparing public incident updates.
- Operations teams releasing vendor or migration notices.
- Researchers preparing shareable summaries from private notes.
- Small organizations that need local AI assistance without uploading source documents.

## System architecture

The FastAPI service exposes document, planning, execution, and audit-memory endpoints. A local lexical retriever grounds each task in stored evidence. Deterministic privacy tools detect and redact common sensitive patterns. A local Qwen instruction model, served by ROCm-enabled llama.cpp, can summarize grounded results. SQLite stores document content and non-secret execution memories.

The browser UI renders the plan before execution and treats tools as capabilities with `read`, `transform`, or `write` permissions. Transform and write actions require explicit approval.

## Agent capabilities

### Local RAG

Documents are normalized, overlapped into bounded chunks, tokenized, and scored against the task using cosine similarity over term counts. Retrieved passages are shown alongside the result so reviewers can trace claims to source text.

### Tool calling

The agent invokes four explicit tools: `local_rag_search`, `sensitive_data_scan`, `redact_documents`, and `write_audit_memory`. Tools have narrow inputs and clearly labeled effects.

### Multi-step planning

Each user task becomes a persistent plan with ordered steps, descriptions, permission classes, and approval requirements. The plan is inspectable before execution.

### Memory

SQLite records plan creation, document addition, and completed release-review metadata. Raw detected secrets are excluded from audit-memory payloads.

### Permission control

Read-only inspection can run immediately. Redaction and persistence remain blocked until separately approved. Original documents are never overwritten.

## AMD Radeon GPU and ROCm adaptation

The optional local model layer connects to an OpenAI-compatible llama.cpp server bound to loopback. The supplied `run_rocm_llama.sh` launches a HIP-enabled server with all model layers offloaded to a Radeon GPU. The project includes an environment probe and repeatable latency benchmark for submission evidence.

Recommended competition environment:

- AMD Radeon GPU supplied through the hackathon program.
- ROCm release supported by the allocated image.
- llama.cpp built with `GGML_HIP=ON` and the assigned GPU target.
- Qwen2.5-7B-Instruct GGUF at an appropriate quantization for available VRAM.

## Innovation and practical value

RedactFlow focuses on the moment where local AI systems become operationally dangerous: moving from reading to taking action. Instead of hiding agent behavior behind a chat response, it surfaces a concise execution plan, classifies tools by effect, and lets the user approve capabilities individually. The same mechanism can later guard email sending, file publishing, ticket creation, or database updates.

## Reproducibility

The complete source, dependency pins, sample data, deterministic demo mode, tests, ROCm launch script, environment probe, and benchmark script are included. A reviewer can reproduce the core workflow without a model, then enable local inference on an AMD Radeon machine using documented environment variables.

