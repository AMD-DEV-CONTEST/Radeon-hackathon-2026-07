# Track 2, Physics-First AI, NuclidePath

**Track:** 2 — Development & Local Deployment of Private AI Agents

**Team:** Physics-First AI (Stefano Rigante, GitHub [@anakinsuper](https://github.com/anakinsuper))

**Application:** NuclidePath

NuclidePath is a private, physics-first AI agent for traceable Cs-137 groundwater screening. A local Qwen3.5-9B planner proposes a constrained six-step workflow, while deterministic, versioned tools remain authoritative for every physical value, uncertainty result, warning, report and artifact hash.

## Links

| Item | URL |
|---|---|
| Source code | [`source/`](./source/) — complete current tree copied from private `main` (release `00d8619`) |
| Demo video | [Google Drive](https://drive.google.com/file/d/19fHhF9CXuQyX2jn6m9DFrUuHR6EyQD-1/view?usp=drivesdk) |
| Project specification | [`NuclidePath_Project_Specification.pdf`](./NuclidePath_Project_Specification.pdf) |
| Presentation deck | [`NuclidePath_Track2_Deck.pptx`](./NuclidePath_Track2_Deck.pptx) |
| Artifact manifest | [`ARTIFACT_MANIFEST.json`](./ARTIFACT_MANIFEST.json) |

> The public video URL and final contest PR remain human approval gates. This branch must not be opened as the official PR while the placeholder remains.

## Track 2 capabilities — 5/5

- **Local knowledge retrieval:** bundled Markdown corpus with cited workflow evidence.
- **Tool invocation:** allow-listed deterministic transport, GCS and uncertainty tools.
- **Multi-step planning:** local Qwen planner constrained to a validated six-step workflow, with deterministic fallback.
- **Local multi-turn memory:** private redacted JSONL session store with mode `0600` and deletion support.
- **Permission and privacy controls:** loopback-only HTTP/LLM endpoints, action allow list and denied-action evidence.

## Current AMD Radeon / ROCm evidence

- AMD Radeon `gfx1100`, ROCm 7.2.1;
- Qwen3.5-9B Q8 through a local `llama.cpp` HIP endpoint;
- 231 tests passed on AMD ROCm;
- exact FP64 primary-GCS → transport → receptor pipeline;
- 147,456 concentration evaluations in a 1.784 ms median;
- 137.09× versus the canonical scalar reference;
- maximum relative concentration error `7.94e-14`;
- controller gates: 216 passed/13 optional-PyTorch skips dependency-light and 231 passed with PyTorch.

Raw benchmark metadata, timings and hashes are retained in the source repository under `artifacts/amd-2026-07-28/platform-current/`.

## Reproduce

```bash
git clone https://github.com/anakinsuper/NuclidePath.git
cd NuclidePath
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
nuclear-emergency-demo --samples 128 --output results/demo
nuclear-emergency-dashboard --host 127.0.0.1 --port 8080 --samples 128
```

The contest-local manifest (`nuclidepath-contest-manifest-2.0`) verifies the deck, specification and the complete source copy under `source/`. The source copy is a clean current-`main` tree (release `00d8619`) excluding `.git`, `.venv`, `node_modules`, `build`, `dist`, `results` and `private-deliverables`. The private `main` retains the separate ten-entry evidence manifest covering screenshots and AMD runtime evidence. The clean wheel includes the primary-paper rock validation dataset used by the dashboard.

## Scientific scope

NuclidePath is a transparent research screening demonstration—not an operational emergency-response system, dose model or site-validated digital twin. The primary Cs GCS covers K/Na competition on three illite site types and NH4 only on frayed-edge sites. Sr-90 remains a provenance-bearing linear-Kd path; unsupported Sr/Ca/Mg coefficients are not invented. The rock reconstructions are paper-input predictions, not digitized experimental validation. The local LLM never generates or modifies physical values.

The current `main` also includes an opt-in PHREEQC multicomponent chemistry bridge (schema `nuclidepath-phreeqc-chemistry-2`) with an independent arithmetic oracle, K-free Central Oklahoma Na-Ca-Mg fixtures and a dependency-free traceable Cs calibration/hold-out gate. PHREEQC remains **PROCESS-QUALIFIED ONLY**: no calibrated multi-cation Cs chemistry, experimental agreement, GCS equivalence or regulatory validity is claimed. The demo video shows the canonical core Track 2 path and does not display the optional PHREEQC bridge.

## Recent extensions (post-merge work)

The latest work adds four deterministic, auditable layers around the canonical screening path:

- **PHREEQC scenario compiler** — maps declared water chemistry, CEC and Cs plus one or more K/Na/Ca/Mg exchange coefficients into PHREEQC `SOLUTION`/`EXCHANGE`/`SELECTED_OUTPUT`/`TRANSPORT` input (schema `nuclidepath-phreeqc-chemistry-2`).
- **Independent arithmetic oracle** — machine-readable checks for units, grid mapping, non-negativity and exchange-site occupancy, persisted in diagnostics and replay JSON.
- **Calibration/hold-out gate** — dependency-free traceable Cs exchange calibration contract with group-disjoint splits and fail-closed promotion; no experimental dataset is bundled and no promotion claim is made.
- **External Cs benchmark registry** — separate EPA/Fuller/Dubus material with source digests, CSV integrity checks and `calibration_eligible: false`.

A **post-merge AMD/ROCm rerun of the full current `main` tree** (5 August 2026) passed **388 tests, 2 skipped** (only the external-PHREEQC tests), with the FP64 platform benchmark reproducing 1.82 ms median / 132.8× / `7.94e-14` max error under `artifacts/amd-2026-08-05/post-merge/`. The canonical `transport-prototype-0.3` path remains authoritative; the bridge is opt-in and does not replace it.
