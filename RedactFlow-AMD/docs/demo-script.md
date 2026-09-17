# 3–5 Minute Demo Script

## 0:00–0:25 — Problem

Show the source document. Explain that it mixes approved migration facts with an email address, phone number, internal IP address, and temporary API key. State that the source must not leave the machine.

## 0:25–0:55 — AMD local runtime

Show `rocm-smi` and the ROCm-enabled llama.cpp console. Explain that Qwen runs locally on a single AMD Radeon GPU and that no closed remote API is required.

## 0:55–1:30 — Local vault and task

Open RedactFlow. Add `sample_data/vendor-release-note.txt`. Read the release task and point out the local-only runtime status.

## 1:30–2:10 — Plan and evidence

Click **Build auditable plan**. Walk through retrieval, sensitive-data inspection, redaction, and audit memory. Open the Evidence tab and show the retrieved passage.

## 2:10–2:45 — Permission boundary

Execute without enabling permissions. Show that the agent pauses and produces no transformed file. Explain that reading does not imply authority to mutate or persist.

## 2:45–3:25 — Approved execution

Approve `redact_documents` and `write_audit_memory`, then execute. Show the release-safe copy, detected findings, and the local audit-memory entry. Download the redacted text file.

## 3:25–3:50 — Performance and close

Show `artifacts/rocm-benchmark.json`. Summarize the five Agentic AI capabilities and close with the intended extension: applying the same permission boundary to publishing, email, and ticketing tools.

