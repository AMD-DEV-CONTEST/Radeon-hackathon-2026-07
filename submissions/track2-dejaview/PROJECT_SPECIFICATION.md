# DejaView project specification

**AMD AI DevMaster Hackathon, Track 2: Agentic AI**
**Release:** 2026-08-05
**Status:** single-user MVP; final hardware acceptance is still an operator step

## 1. What the project does

DejaView turns permitted screen activity into a searchable timeline. A user can ask what they were working on, open the supporting event or screenshot, and request a daily report. Honcho stores a small activity summary so the agent can answer questions about recurring work patterns.

The product is built around one rule: a frame must pass a device-local privacy decision before any downstream service can see it. A blocked frame creates audit metadata only. It does not become OCR, a screenshot, an embedding, a Honcho message, or a remote request.

The current release is intentionally narrow. It supports screen frames only. Audio and document ingestion return `501 unsupported_media`. The contest-verified capture client is macOS. A Windows capture backend is included, but its complete managed stack has not passed the final live acceptance gate.

## 2. Why this is an agentic application

DejaView is not a chat wrapper around a document index. The system has to decide whether an observation may enter memory, construct a time-aware event, retrieve evidence, and refuse an answer when the evidence is missing.

The main flow is:

```text
capture -> local Sentinel -> OCR -> novelty and merge -> visual understanding
        -> embedding -> timeline and screenshot -> Honcho outbox
        -> agent tools -> cited answer or daily report
```

`agentd` calls retrieval and profile tools before it writes an answer. Every event citation must be present in the tool results from the same request. If a Radeon request fails, the router may use the verified Local Metal path only for classified retryable failures. Authentication errors, bad caller requests, privacy rejection, and unknown errors do not trigger a fallback.

## 3. Deployment model

### Split deployment

The usual setup keeps the data on a Mac or Windows device. Postgres, Redis, screenshots, audit records, Honcho, `memoryd`, and `agentd` stay there. The AMD machine is a stateless inference host. Only frames that pass the local Sentinel can be sent through `GATEWAY_URL`.

### Single AMD host

For a judge without a Mac data plane, the same logical services can run on one AMD host. In this mode the data and compute planes share a machine, but the order of checks does not change: Sentinel first, then OCR and storage. Gateways remain loopback-bound.

The first-time connection procedure is in the [Radeon Cloud quick start](https://github.com/Aidenwu0209/localwork/blob/main/docs/Radeon-Cloud-QUICKSTART.md). The server-side model and VRAM procedure is in [deploy/server/DEPLOY.md](https://github.com/Aidenwu0209/localwork/blob/main/deploy/server/DEPLOY.md).

## 4. Model roles

The application uses logical role names. Physical model files are configured in `deploy/server/litellm.yaml`.

| Role | Responsibility | Physical model in the release |
|---|---|---|
| `brain` | Deep reasoning, planning, visual interpretation, and writing | ThinkingCap-Qwen3.6-27B GGUF |
| `perceive` | Screen understanding and Honcho derivation | Gemma 4 E4B GGUF with BF16 projector |
| `sentinel` | Fast visual privacy classification | MiniCPM-V 4.6 GGUF with projector |
| `fast` | Novelty, merge, and tag decisions | MiniCPM5-1B GGUF |
| `embed` | Event and query embeddings | Qwen3-Embedding-0.6B GGUF, 1024 dimensions |
| `ocrd` | Deterministic verbatim OCR; not an LLM role | PP-OCRv6 or RapidOCR |

The five LLM names are routing roles, not a promise that all weight sets are resident at the same time. The launch scripts check current VRAM before starting a role. In the split topology, `sentinel` stays on the data device and `brain` starts on demand.

## 5. AMD Radeon and ROCm implementation

The AMD inference host uses llama.cpp built with `GGML_HIP=ON` for `gfx1100`. The accepted P3.1 campaign ran on a Radeon PRO W7900D with 47.98 GiB VRAM and ROCm 7.2.1. The harness recorded the binary, model, prompt, image, ROCm, and output hashes.

The formal matrix contains:

- 18 `brain` cells: Q8_0, Q6_K, and Q4_K_M, with MTP off/on and client concurrency 1/4/8.
- 3 `perceive` cells: server slots and client concurrency at 1/1, 2/2, and 4/4.
- One excluded warm-up and three measured batches per cell.

Selected measurements include 23.9 tokens/s for brain Q6_K with MTP off at concurrency 1, 41.6 tokens/s with MTP on in the same cell, and 50.0 tokens/s aggregate for the tested perceive slots/c4 cell. The full data, VRAM samples, and hashes are in [docs/benchmarks.md](https://github.com/Aidenwu0209/localwork/blob/main/docs/benchmarks.md) and [the checksummed P3.1 evidence](https://github.com/Aidenwu0209/localwork/tree/main/docs/benchmark-evidence/p31/p31-w7900d-20260728T075653Z).

These are isolated benchmark cells. They do not establish full-pipeline latency, arbitrary-screen accuracy, energy efficiency, co-tenant speedups, or simultaneous residency for every role. Operators must use `rocm-smi` on the current instance before launching a model.

## 6. Privacy and data handling

The capture client keeps frame pixels in memory, sends them to the local Sentinel, and discards the buffer. If the Sentinel returns a sensitive, malformed, unknown, low-confidence, timed-out, or unavailable result, the pipeline closes the gate.

For an allowed frame, OCR and later stages can create a timeline event, an embedding, and a screenshot. For a blocked frame, the audit record contains the decision and reason, but no pixel data or screenshot path.

The Honcho outbox contains a strict, minimized projection: schema version, event ID, timestamp, app context, activity, topics, and event provenance. It excludes OCR text, URLs, window titles, screenshots, pixels, and blocked frames. Delivery is asynchronous, retryable, and idempotent; an Honcho outage does not roll back the local timeline event.

## 7. Reproduction

From a clean clone on an authorized machine:

```bash
git submodule update --init --recursive
make setup
cp .env.example .env
cp deploy/mac/honcho.env.example deploy/mac/honcho.env
set -a; source .env; set +a
make doctor
make test
```

For the local product path:

```bash
./deploy/mac/llama-launch/dev-stack.sh up sentinel
ssh radeon-cloud "cd /root/dejaview-launch && ./server-stack.sh up embed fast perceive"
ssh -f -N -L 14000:127.0.0.1:4000 radeon-cloud
make product-up
make product-status
make capture
```

The repository does not store model weights, temporary Radeon coordinates, SSH private keys, API keys, or real user data. Operators provide those values outside source control. Do not expose the inference gateway publicly.

## 8. Evidence and verification

The repository contains synthetic fixtures and an offline first-party test suite. The release checker validates the video manifest, caption timing and hashes, office documents, tracked paths, privacy-sensitive text, README links, and the human-only official PR boundary.

The 3:15.2 English submission video shows the product flow, a blocked sensitive frame, evidence-backed recall, Honcho output, Radeon inference, and a verified Radeon-link disconnect followed by the Local Metal report. The original 2:37 evidence cut remains in the repository unchanged. The editable captions and manifest are next to both videos.

The offline suite and the final hardware acceptance are separate checks. A passing offline suite cannot stand in for a live Radeon run. Before the final upload, the operator must run the acceptance checklist on the final instance and confirm the official repository fork, English PR, account eligibility, and upload fields.

## 9. Current limitations

- The product is single user. Accounts, billing, team administration, mobile clients, cross-device sync, and installers are out of scope.
- macOS is the contest-verified capture client. Windows capture code exists, but the full Windows managed stack remains a separate acceptance gate.
- Audio and document ingestion return `501 unsupported_media`.
- OCR quality depends on the screen, font, language mix, and compression. The synthetic corpus does not cover every application.
- The split topology sends allowed transient inference payloads to an authorized stateless AMD host. It does not claim that all inference runs on the data device.

## 10. Deliverables

- Source repository: [github.com/Aidenwu0209/localwork](https://github.com/Aidenwu0209/localwork)
- English README and reproduction instructions
- [Project specification in Markdown](PROJECT_SPECIFICATION.md), [PDF](DejaView-Project-Specification.pdf), and [editable DOCX](DejaView-Project-Specification.docx)
- [Editable Track 2 presentation](DejaView-Track2-Presentation.pptx)
- [English demo video](dejaview-demo-en.mp4), [SRT](dejaview-demo-en.srt), and [manifest](https://github.com/Aidenwu0209/localwork/blob/main/docs/assets/demo/p34-video-manifest.json)
- [ROCm benchmark report](https://github.com/Aidenwu0209/localwork/blob/main/docs/benchmarks.md) and [P3.1 evidence](https://github.com/Aidenwu0209/localwork/tree/main/docs/benchmark-evidence/p31/p31-w7900d-20260728T075653Z)

All project descriptions and PR text for the competition must be in English. The official submission is a human step: fork the competition repository and open a PR with the title `Track 2, DeepSleep, DejaView`.

## 11. License

Project code and documentation use Apache-2.0. See [LICENSE](https://github.com/Aidenwu0209/localwork/blob/main/LICENSE), [NOTICE](https://github.com/Aidenwu0209/localwork/blob/main/NOTICE), and [docs/licenses.md](https://github.com/Aidenwu0209/localwork/blob/main/docs/licenses.md) for project and third-party notices. Model weights retain their upstream licenses.
