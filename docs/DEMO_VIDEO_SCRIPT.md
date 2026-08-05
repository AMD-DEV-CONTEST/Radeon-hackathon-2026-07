# XiangLens 4:30 Demonstration Video Script

## Recording Goal

Prove, in one continuous story, that XiangLens is a complete private Agent whose core multimodal
inference runs on AMD Radeon/ROCm. The video must show command-line evidence, the real GUI, the
bounded workflow, tool use, RAG, memory consent, privacy controls, and measured performance.
The distinguishing reveal is an opt-in private 108-technique Lens Tool whose proprietary source
never enters Git or the browser.

Target duration: **4 minutes 30 seconds**. Keep the final export between 3 and 5 minutes.

## Demo Assets

Use repository fixtures rather than personal photographs:

```text
data/fixtures/images/portrait_01__clean.jpg
data/fixtures/images/portrait_01__qr_code.jpg
```

Primary request:

```text
Compare these profile images for a GitHub account used with international open-source
collaborators. I want to appear credible and approachable. Explain visible privacy risks,
cite your context, apply the private symbolic Lens only as a non-factual course framework,
and do not infer personality or identity.
```

Memory statement for the second turn:

```text
Remember that red is an intentional part of my brand identity. Do not treat it as a negative
signal in future reviews.
```

## Timeline and Narration

### 0:00–0:20 — Hook and positioning

**Screen**

- Open on the two candidate images beside the XiangLens title.
- Cut to the running application for no more than two seconds.

**Narration**

> A profile image follows us across every commit, community message, and professional
> introduction—but small crops, hidden metadata, and cultural ambiguity are easy to miss.
> XiangLens is a private, evidence-backed profile-image Agent running on AMD Radeon and ROCm.

**On-screen caption**

```text
XiangLens · AMD AI DevMaster 2026 · Track 2
Private · Goal-relative · Source-backed
```

### 0:20–0:50 — Prove the local Radeon boundary

**Screen**

Show one terminal with large readable text. Run or display already-prepared output for:

```bash
rocm-smi --showproductname --showuse --showmemuse
git -C /workspace/llama.cpp rev-parse --short HEAD
curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:8080/health
```

Then show the authenticated XiangLens system-status JSON with:

```text
deployment_mode: submission-local
model_endpoint: http://127.0.0.1:8000/v1
submission_topology_compliant: true
milvus_ready: true
private_lens_available: true
```

**Narration**

> The Qwen3.6 35B-class multimodal model is served by llama.cpp on a Radeon PRO W7900. FastAPI,
> LangGraph, Milvus Lite, SQLite, the private Lens source, and the model share the same
> user-controlled environment. Only the application API is exposed; core inference and
> proprietary knowledge stay local.

### 0:50–1:15 — Explain the Agent in one diagram

**Screen**

Show the architecture slide. Highlight the workflow from left to right:

```text
Policy -> Memory recall -> Local tools -> Vision -> Private Lens -> RAG -> Compare -> Consent -> Report
```

**Narration**

> This is not a one-shot prompt. A bounded LangGraph state machine applies a policy gate, recalls
> only approved memory, runs deterministic privacy tools, calls the local vision model, optionally
> invokes a runtime-mounted private Lens, retrieves four source-backed cards, compares candidates,
> requests consent, and renders citations in code.

### 1:15–1:45 — Set the goal and upload candidates

**Screen**

- Switch to the XiangLens GUI.
- Show target context `GitHub` and audience `International open-source collaborators`.
- Show all four Lens Packs enabled.
- Show **Private 108-Technique Lens** separately, unchecked at first, then enable it.
- Upload the clean and QR fixtures.
- Paste the primary request.

**Narration**

> I define the platform, audience, and intended signals instead of asking the model to judge a
> person. These two open-license fixtures differ by one visible privacy risk. XiangLens will compare
> them against the same transparent rubric. The separate private control mounts a 24-lesson,
> 108-technique course distillation on the server for this run only; its source never enters the
> page or the public repository.

### 1:45–2:30 — Run the real bounded workflow

**Screen**

- Click **Compare candidates**.
- Keep the Workflow panel visible while the background run is active; then show the complete node
  trace when the durable result arrives.
- Briefly show Radeon utilization moving in a small terminal crop or split view.
- Do not speed up the portion that proves real execution; trim only idle waiting.

**Narration**

> The public tunnel uses a short background-run request and polls durable state, avoiding its HTTP/2
> streaming limit. The completed result still exposes every public tool name, duration, and summary.
> Objective checks run before the model. The VLM describes visible facts without identity or
> personality inference. Top-K retrieval keeps the public prompt focused, and the opt-in private node
> emits only a filtered symbolic reading and technique identifier.

**On-screen callouts**

```text
Local image tools
Self-hosted VLM
Runtime-only Private Lens Tool
Milvus Lite Top-K RAG
Typed output validation
```

### 2:30–3:05 — Show the final decision and evidence

**Screen**

- Show the recommended image and comparison scores.
- Show the QR privacy finding.
- Show the completed `run private lens` trace node.
- Show one private technique identifier and the non-factual symbolic-context disclaimer.
- Open one source link from Retrieved Sources.
- Show Total, Model, RAG, and Sources metrics.
- Trigger **Safe copy** on the selected image.

**Narration**

> The result recommends the safer candidate, explains every score, and surfaces the QR code as
> visible disclosure. The private tool adds one bounded symbolic association with a technique
> reference, but the safety layer removes personality, health, wealth, relationship, and predictive
> claims. Public contextual claims still link to retrieved source cards. The safe-copy tool exports
> a metadata-free JPEG without asking the model to rewrite the image.

### 3:05–3:40 — Demonstrate real multi-turn context and consent-first memory

**Screen**

- In **Continue the conversation**, ask: “Why is Candidate A safer than Candidate B for this
  audience?”
- Show Turn 2 plus the `recall_context` and `reuse_analysis` trace nodes; point out that the VLM is
  skipped and compare the follow-up latency with the initial multimodal run.
- Send: “Remember that a red accent is an intentional part of my brand identity.”
- Show **Permission required** and click **Approve memory**.
- Show the preference under Approved Memory, then ask one more follow-up and show it in recalled
  context.

**Narration**

> This is a real multi-turn agent interaction, not a fresh prompt disguised as chat. Every follow-up
> keeps the same thread, image candidates, target context, and prior user-assistant messages. It
> reuses the verified observations, privacy findings, comparison, and citations, so the expensive
> vision pass is not repeated. The trace proves both recall and cached-analysis reuse. Separately,
> the model cannot write long-term
> memory: my explicit preference creates only a pending proposal. After approval it can be recalled
> with consent provenance, deleted individually, or erased with Forget All Private State.

### 3:40–4:10 — Show Radeon optimization and measurements

**Screen**

- Show the final `benchmarks/results/llama_cpp_w7900_optimized.md` summary.
- Show the exact llama-server command beside `rocm-smi` telemetry.
- Highlight 87.09 ms median first delta, 83.42 tok/s decode throughput, 11.92 s end-to-end latency,
  and 100% valid JSON. Record peak VRAM separately in the telemetry view; do not add a number that
  is absent from the reviewed result.

**Narration**

> In five warm multimodal runs, the first generated delta arrived in 87.09 milliseconds, decode
> throughput held at 83.42 tokens per second, end-to-end latency was 11.92 seconds, and every run
> returned valid JSON. A separate cold reference reached its first delta in 825.58 milliseconds,
> and the final-output hash matched across all six captures. This measures the tuned stack; it does
> not assign the result to one feature or make an unsupported FP8 claim.

### 4:10–4:30 — Close

**Screen**

- Return to the finished report.
- End on the title, repository, and three value words.

**Narration**

> XiangLens helps a user choose how to communicate—not who a model thinks they are. It combines a
> complete local Agent workflow with source-backed context, explicit memory consent, and practical
> Radeon performance. The code, reproduction guide, benchmark protocol, and dataset provenance are
> all included in the submission.

**Final frame**

```text
XiangLens
Private · Evidence-backed · User-controlled
github.com/ld0574/Radeon-hackathon-2026-07
```

## Pre-Recording Checklist

### Environment

- Build the final Milvus Lite database with the selected embedding provider.
- Provision the private distillation outside the checkout and verify `private_lens_available: true`.
- Start llama-server with the exact recorded command.
- Start FastAPI and verify the localhost model endpoint.
- Start the Radeon tunnel and update `XIANGLENS_API_BASE` if its URL changed.
- Confirm GitHub Pages is on the exact commit being submitted.
- Run one warmup analysis before recording, but create a fresh application session for the take.
- Prepare the reviewed benchmark Markdown and GPU telemetry command.

### Privacy

- Use only repository fixtures.
- Hide `.env`, API keys, Bearer tokens, tunnel identity files, and browser developer-storage views.
- Crop or blur any private hostname if the public URL should not remain in the video.
- Close personal tabs, notifications, terminal history, and unrelated applications.
- Do not display the private path, course prompt, source text, screenshots, or unlicensed images;
  show only the checkbox, trace metadata, technique identifier, and filtered output.

### Readability

- Record at 1920×1080 or higher.
- Use browser zoom between 110% and 125%.
- Increase terminal font size until commands are readable on a 13-inch screen.
- Keep the cursor away from text being read.
- Use English captions and check spelling of Radeon, ROCm, llama.cpp, LangGraph, and Milvus.

## Editing Rules

- Keep real execution causally honest. A cut may remove idle time but must not imply a cached result
  was generated by the visible click.
- Prefer hard cuts and one consistent caption style; avoid decorative transitions.
- Keep background music below narration or omit it.
- Display every numeric performance claim long enough to read.
- If a run fails, record another complete take rather than hiding an error inside the successful
  sequence.

## Fallback Plan

If the public tunnel is unstable, record directly inside the Radeon Notebook with FastAPI and a
local browser, preserving the same localhost model proof. If a live second analysis would exceed
five minutes, prepare the approved preference before the take, then demonstrate its real recall and
deletion without claiming the approval occurred during the visible recording.
