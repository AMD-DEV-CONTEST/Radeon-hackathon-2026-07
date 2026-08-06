# Experience Asset - Four-Minute Demo Recording Runbook

**Status:** content and evidence are ready; real screen recording, English
narration/subtitles, upload and final URL require a human recording session.

Use the accepted public synthetic journey from `web/e2e/m4.spec.ts`. Record the
real application with local Qwen3.5-9B on the W7900. Do not substitute Mock
output or join unrelated runs as if they were one successful journey.

## One-sentence story

> Experience Asset turns a fragmented personal experience into a correctable,
> evidence-bound asset; LangGraph coordinates the steps, while deterministic
> Runtime policy controls retrieval, tools, privacy, approval and delivery on a
> local Radeon stack.

## Required identity card before recording

Capture a readable terminal or evidence screen containing:

```text
Application implementation: c9ec07489d17a2abb74bac66a23ade2c775c1b06
Model: Qwen/Qwen3.5-9B
Model revision: 460979c3d11864dd16408d860ac930a360a2fac2
Precision: BF16; quantization: none
vLLM: 0.26.0
ROCm/HIP: 7.2
GPU: Radeon PRO W7900, gfx1100, 96 CUs, 48 GiB
Profile: P1-prefix-cache; S0 rollback
Service: localhost only
```

Do not reveal the pod hostname, IP address, credentials, signed URLs, private
prompts, raw logs or local database contents.

## Recommended four-minute cut

| Time | Screen | Narration job | Evidence proved |
|---|---|---|---|
| 0:00-0:18 | Final HTML/Markdown/JSON result, then slide 1 | State the user problem and product promise | The result is a reusable asset, not one-shot prose |
| 0:18-0:35 | Identity card / `amd-smi` plus application commit | Name W7900, ROCm, vLLM and Qwen3.5-9B | Core inference is local on the declared stack |
| 0:35-1:20 | Real UI: source input, M1, M2 and one correction | Explain typed evidence and correction | Visible state, source boundary and version continuity |
| 1:20-2:12 | Real UI: M3, M4 readiness, candidate summary, relation confirmation | Explain the retrieval gate | History is unavailable until readiness and explicit confirmation |
| 2:12-3:03 | Real UI: M5 route, privacy decision, exact approval, preview/export | Explain Runtime authority | Eligibility, privacy and approval precede delivery |
| 3:03-3:35 | Slide 6 plus real evidence path | State the bounded optimization result | Service evidence and integrated evidence remain separate |
| 3:35-4:00 | Final output and slide 7 | Close on value and limitation | Finished result, privacy boundary and honest claim scope |

Honest cuts may remove model waiting time. Keep enough before/after state to
show that each cut continues the same asset/version chain.

## Suggested narration

### 0:00-0:35 - Problem and local identity

> Personal experience is rich, but ordinary notes and AI summaries flatten
> facts, judgments and uncertainty into one paragraph. Experience Asset builds
> a versioned knowledge asset instead. This run uses local Qwen3.5-9B through
> vLLM and ROCm on a Radeon PRO W7900; the model service and application remain
> bound to localhost.

### 0:35-1:20 - M1 and M2

> The Agent first establishes the source boundary and the user's goal. It then
> maps critical moments using only supplied statement identities. I can correct
> an upstream fact without silently rewriting the rest of the asset.

### 1:20-2:12 - M3, M4 and phase-gated retrieval

> Decisions and evidence become inspectable in M3. M4 extracts lessons and
> limits, but cross-asset history remains locked until the Knowledge Card is
> ready. Candidate discovery exposes summaries only. Detailed retrieval begins
> only after I confirm one relation.

### 2:12-3:03 - M5 and delivery

> M5 evaluates routes, privacy and permission. The model can propose an action,
> but deterministic Runtime policy decides whether it may execute. Approval is
> bound to the exact version, route, language and evidence. The accepted private
> route produces HTML, Markdown and JSON from the same canonical asset.

### 3:03-4:00 - Radeon evidence and close

> In the frozen W7900 service benchmark, the selected P1 Profile reduced p95
> time to first token by 83.89 percent versus S0, reduced median end-to-end
> service latency by 4.33 percent and retained 85 percent warm-up reliability. The same complete Agent
> case passed on S0 and P1; P1 took 109.21 seconds in that one observation, but
> no cache hit was recorded, so we do not generalize or attribute the timing
> difference to caching. Experience Asset keeps the model useful without giving
> it authority over facts, privacy or disclosure.

## Recording checklist

- [ ] final submission repository commit recorded separately from tested
      application implementation `c9ec074`;
- [ ] P1 service healthy on `127.0.0.1` and S0 rollback command retained;
- [ ] FastAPI and React UI healthy through local/SSH forwarding only;
- [ ] the accepted public synthetic scenario is reset to a clean state;
- [ ] screen resolution and browser zoom keep labels readable;
- [ ] notifications, credentials, host/IP details and private tabs are hidden;
- [ ] one rehearsal reaches private HTML/Markdown/JSON delivery;
- [ ] recording uses English narration or complete English subtitles;
- [ ] final video is 3-5 minutes and shows real operation, not slides only;
- [ ] uploaded video plays from its intended reviewer-facing link;
- [ ] final URL and optional timestamps are copied into `OFFICIAL_PR_DRAFT.md`.

## Evidence-safe claims for the recording

- Complete local Agent on W7900: `PASS` at `c9ec074`.
- Stage 1 P1 vs S0: p95 TTFT -83.89%, median E2EL -4.33%, output TPS
  +0.47%, P1 reliability 85%.
- Minimal Stage 2: both S0/P1 journeys passed; P1 109.21 seconds vs S0 about
  2.0 minutes in one observation.
- Do not attribute the Stage 2 observation to prefix caching; observed hit rate
  was 0.0%.
- Do not claim Stage 2 peak VRAM; it was not measured.
- Do not claim hallucination or privacy risk is eliminated.
