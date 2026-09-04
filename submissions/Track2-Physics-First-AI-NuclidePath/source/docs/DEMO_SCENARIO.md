# Demo Scenario and 3–5 Minute Recording Script

## Goal

Show that NuclidePath is a real private agent on AMD hardware, not an LLM wrapper around fabricated numbers.

## Scenario

A hypothetical maintained Cs-137 boundary concentration is applied to a homogeneous groundwater domain. The analyst compares K+ = 0 and 20 mg/L at a monitoring point 100 m away, then inspects missing site data, local evidence and propagated uncertainty.

Input: `scenarios/cs137_emergency_full.json`
Ranges: `scenarios/uncertainty_ranges.json`

## Recording plan — target 4:36 (current master)

### 0:00–0:25 — problem and differentiator

**Screen:** title slide and architecture diagram.

**Narration:**

> Emergency analysis needs AI for coordination, but not for inventing physics. NuclidePath is a private local agent where the LLM can plan and explain, while versioned deterministic tools produce every physical value.

### 0:25–0:55 — AMD/private deployment

**Screen:** terminal with `amd-smi`, health endpoint and model server command; briefly show benchmark table.

**Narration:**

> Qwen3.5-9B Q8 runs entirely on this AMD Radeon system through llama.cpp and ROCm. All layers are on the GPU, and the OpenAI-compatible endpoint is bound only to localhost. The final core benchmark snapshot measured 2,877.30 ± 153.36 prompt tokens per second and 67.66 ± 0.14 generated tokens per second; the older 2,862 measurement is retained only in the dated benchmark record.

### 0:55–1:35 — scenario and workflow

**Screen:** dashboard inputs, then click **Run private workflow**.

**Narration:**

> The scenario is explicitly demonstrative. The Site Agent refuses to invent mineralogy, pH, exchange capacity or a site-specific Kd. The safe planner returns six allow-listed steps. Local retrieval finds bundled scientific sources, and the Environment Agent invokes the deterministic transport contract.

### 1:35–2:25 — physical results

**Screen:** overview metrics and concentration chart.

**Narration:**

> At zero potassium, effective Kd is 0.2 cubic metres per kilogram and retardation is about 972. At 20 milligrams per litre potassium, the empirical competition term reduces effective Kd to 0.167 and retardation to about 811, so estimated travel time decreases. These numbers come from model version 0.3, not from the LLM.

### 2:25–3:05 — uncertainty and provenance

**Screen:** uncertainty tab, then provenance tab.

**Narration:**

> A seeded Monte Carlo run propagates declared ranges and reports P05, median and P95. Only the Cs Kd bracket is literature-classified. Hydraulic and competition ranges are clearly marked as demonstrative. Every local knowledge hit includes an excerpt, path, source URL and retrieval score.

### 3:05–3:35 — privacy and artifacts

**Screen:** capability badges and artifact downloads.

**Narration:**

> NuclidePath implements all five Track 2 capabilities. Session memory stays in a mode-0600 local file after sensitive-field redaction. External network, operational control, equipment control and public alerts are denied. JSON, Markdown, CSV and SVG outputs are covered by a SHA-256 manifest.

### 3:35–4:10 — proof and close

**Screen:** terminal running tests, then offline/LLM equality output.

```bash
pytest -q
```

Show:

```text
364 passed, 15 skipped (recorded PR #15 merged-bridge integration gate; historical video checkpoint)
AMD core-platform snapshot: 231 passed; exact FP64 parity recorded
physics_identical True
```

**Narration:**

> The full test suite passes on the AMD workspace, and the offline and LLM-planned paths produce identical physical runs. NuclidePath demonstrates how private agents can improve technical workflows without surrendering scientific traceability.

## Commands used in the recording
## Scope note for the current source

The recording demonstrates the canonical transport/agent path. The optional
PHREEQC compiler and multicomponent fixtures are part of the current source but
are not shown in this video; no video claim should imply that the recording
performed a trusted PHREEQC run.


```bash
curl -s http://127.0.0.1:8000/health
nuclear-emergency-dashboard --host 127.0.0.1 --port 8080 --samples 256
pytest -q
nuclear-emergency-demo \
  --scenario scenarios/cs137_emergency_full.json \
  --knowledge-dir knowledge \
  --uncertainty-ranges scenarios/uncertainty_ranges.json \
  --output results/video-demo \
  --samples 128 \
  --planner llm \
  --llm-base-url http://127.0.0.1:8000/v1 \
  --llm-model qwen35-9b-q8 \
  --session-id video-demo
```

## Recording checklist

- 1920×1080, 30 fps;
- terminal font at least 18 px;
- browser zoom adjusted so badges and metrics are legible;
- no SSH host, token, private key or personal account visible;
- demonstrate actual click and result, not edited mockups;
- keep total length between 3 and 5 minutes;
- add captions for technical numbers;
- end with repository URL and project name.
