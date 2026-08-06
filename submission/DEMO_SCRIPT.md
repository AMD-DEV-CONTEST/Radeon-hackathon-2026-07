# ClaimCourt Demo Script

**Target length:** 4 minutes 20 seconds
**Language:** English
**Demo workspace:** synthetic championship corpus only

## Before Recording

- Start Qwen3-14B, the ClaimCourt LoRA, BGE embedding, reranker, API, and frontend.
- Warm the judge with one short JSON request.
- Reset the UI to the English Case Desk.
- Close terminals containing tokens, private paths, SSH keys, or unrelated history.
- Keep `rocm-smi`, `/v1/models`, and the live evidence JSON commands ready in separate terminals.

## Timeline

### 0:00-0:20 - The dispute

**Screen:** ClaimCourt title and the synthetic Vendor SLA case.

**Narration:**

"Sales said enterprise-grade reliability. Engineering discussed a 99.9% target. The contract manager says no 99.9% SLA was ever signed. ClaimCourt turns this private document dispute into an auditable local verdict."

### 0:20-0:45 - Local AMD proof

**Screen:** Terminal showing `rocminfo`, `rocm-smi`, and both local vLLM model endpoints.

**Narration:**

"The complete inference path runs locally on an AMD Radeon PRO W7900-class GPU with ROCm. Qwen3-14B BF16 serves the controlled agent roles and the ClaimCourt intent LoRA. BGE embeddings run through a second local vLLM pooling endpoint. No closed remote model API is used."

### 0:45-1:10 - Private workspace and fuzzy intent

**Screen:** Load the championship corpus, enter the SLA question, open Intent.

**Narration:**

"ClaimCourt first compiles the human request into a structured intent: claim type, concepts, artifact constraints, search scope, and clarification requirements. This prevents vague language from being sent directly to a vector store."

### 1:10-1:45 - Evidence retrieval

**Screen:** Evidence view with agreement, email, meeting notes, signed addendum, draft, and citations.

**Narration:**

"Retrieval combines BM25, SQLite FTS5, character and word indexes, local BGE embeddings, metadata, file-family authority rules, and a local cross-encoder. Every result retains its page or slide locator and SHA-256 evidence identity."

### 1:45-2:30 - Controlled evidence court

**Screen:** Prosecutor and defense panels, then the judge verdict.

**Narration:**

"The prosecutor presents the strongest support. The defense finds exceptions, unsigned language, and contradictions. The judge can cite only evidence IDs from this packet. Unknown citations are rejected. The result is insufficient evidence of a contractual 99.9% commitment."

### 2:30-3:05 - Timeline and next action

**Screen:** Contradiction timeline and missing-evidence panel.

**Narration:**

"The timeline separates a future engineering target from the signed 99.5% addendum and the agreement's no-SLA clause. ClaimCourt identifies the missing record and recommends requesting a signed 99.9% SLA addendum."

### 3:05-3:30 - Permission and privacy

**Screen:** Export modal. Show that the file is not written until approval.

**Narration:**

"The report stays local and is not written until the user approves. Sensitive-record scans return only a location, category, fingerprint, and redacted preview. Raw credentials never enter the model or exported report."

### 3:30-4:05 - Measured Radeon evidence

**Screen:** Runtime drawer and live JSON receipt.

**Narration:**

"This live run reports a 0.27-second first token, 14.3 output tokens per second, and a complete three-role latency of 126.44 seconds. The frozen 320-query live holdout passed every case with the Router, BGE embedding, and reranker active, and zero unsafe wrong auto-selections."

### 4:05-4:20 - Closing

**Screen:** Verdict and ClaimCourt title.

**Narration:**

"ClaimCourt is not another document chatbot. It is a private local evidence agent that understands fuzzy human memory, shows its sources, exposes contradictions, and asks permission before it acts."

## Recording Commands

```bash
rocminfo | head -n 25
rocm-smi --showproductname --showuse --showmemuse
curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:8001/v1/models
curl http://127.0.0.1:8503/api/health
```

Never show an SSH private key, access token, real private document, shell history containing credentials, or a public endpoint exposing a real workspace.
