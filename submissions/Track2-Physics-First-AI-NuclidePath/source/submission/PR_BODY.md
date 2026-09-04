# NuclidePath — Track 2 submission

**Track:** AMD AI DevMaster Hackathon 2026, Track 2 (Development & Local Deployment of Private AI Agents)
**Team / Author:** Physics-First AI — Stefano Rigante (nuclear engineer, contaminant transport)

### Project

**NuclidePath** is a private, physics-first AI agent for traceable Cs-137
groundwater screening. A local Qwen3.5-9B model may plan an allow-listed
workflow, while deterministic versioned tools remain authoritative for
physics, uncertainty, reporting and artifact hashes.

### Track 2 capabilities

- local knowledge retrieval with cited bundled sources;
- local multi-turn memory with redaction and SHA-256 provenance;
- multi-step planning constrained to an allow list;
- explicit permission and privacy control;
- deterministic tool invocation with auditable outputs.

All five listed capabilities are implemented and exercised. Core inference
requires no remote API.

### Current source state

The current private `main` includes an opt-in PHREEQC chemistry bridge with
schema `nuclidepath-phreeqc-chemistry-2`. It compiles an explicitly declared
Cs chemistry block with any non-empty subset of K, Na, Ca and Mg into
SOLUTION/EXCHANGE/SELECTED_OUTPUT/TRANSPORT input, supports K-free
Central Oklahoma brine/recharge fixtures, and adds deterministic per-ion
diagnostics to the report.

The canonical `transport-prototype-0.3` path remains the authoritative
screening calculation. PHREEQC is **PROCESS-QUALIFIED ONLY**: Example 2 has a
process qualification record; the new multicomponent fixtures have passed the
compiler, parser, independent arithmetic oracle and local replay checks, but
still await a trusted real run and calibrated Cs chemistry. No regulatory,
dose, operational or site-safety claim is made.

The repository also includes a separately validated EPA/Fuller/Dubus external Cs benchmark registry with source digests, CSV integrity checks and `calibration_eligible: false`. It remains outside scientific promotion.

The repository also includes a dependency-free traceable Cs exchange
calibration/hold-out gate. It validates explicit units and provenance, enforces
group-disjoint calibration and hold-out data, records hold-out metrics and a
canonical report digest, and fails closed for synthetic or unverified data. No
experimental dataset is bundled and no promotion claim is made.

### AMD deployment evidence

The AMD evidence includes a dated core-platform snapshot from 28 July 2026:
ROCm 7.2.1, HIP `llama.cpp`, Qwen3.5-9B-Q8_0, all model layers offloaded,
and 231 tests passed on the recorded AMD workspace. The exact FP64
device-resident primary-GCS → transport → receptor pipeline evaluated 147,456
concentrations in a 1.784 ms median, 137.09× faster than scalar, with
maximum relative concentration error `7.94e-14`.

A **post-merge AMD/ROCm rerun of the `main` tree at head `b6d4c61e74`** was executed on
5 August 2026 (gfx1100, ROCm 7.2.1, torch `2.9.1+gitff65f5b`, head `b6d4c61e74`):
**388 tests passed, 2 skipped** (only the external-PHREEQC solver tests), with
the FP64 platform benchmark reproducing 1.82 ms median / 132.8× speedup /
`7.94e-14` max error. Evidence is archived under
`artifacts/amd-2026-08-05/post-merge/` with SHA-256 digests.
All 13 PyTorch/ROCm tests skipped in the dependency-light CI pass on the AMD GPU.

The GitHub-hosted CI gate for the current source passes **377 tests, 15 skipped**
(review hardening: atomic session-memory rewrite, free-text secret redaction,
tightened calibration promotion gate), with workflow policy, Python
compilation, wheel, editorial-toolchain and whitespace checks all PASS. These
are GitHub-hosted integration checkpoints, not a fresh post-merge AMD rerun or
a trusted self-hosted PHREEQC run.

### Demo video

`https://drive.google.com/file/d/19fHhF9CXuQyX2jn6m9DFrUuHR6EyQD-1/view?usp=drivesdk`

The private core-path master is 4:36 at 1920×1080 and 30 fps with H.264/AAC
narration and embedded English subtitles. It demonstrates the canonical
agent/transport workflow; it does not show the later PHREEQC bridge. The
public judge-accessible copy is hosted on Google Drive (SHA-256
`47dc62f419c778d19af5724314a5d3bf3e04c3ee2175349897393162977c0d80`).

The contest branch stores the editorial package and a complete copied source
tree under `submissions/Track2-Physics-First-AI-NuclidePath/source/`, synchronized
from private `main` (excluding the internal `.hermes/` planning directory).
The contest-local manifest is `nuclidepath-contest-manifest-2.0` and the complete
current source is judge-accessible inside the submission.

### Reproduce locally

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
nuclear-emergency-demo --samples 128 --output results/demo
nuclear-emergency-dashboard --host 127.0.0.1 --port 8080 --samples 128
```

For the optional bridge:

```bash
nuclear-phreeqc-scenario \
  scenarios/central_oklahoma_brine_multicomponent.json \
  --output results/phreeqc-brine
```

The full pipeline writes the deterministic report and manifest; the PHREEQC
path remains compile-only unless the trusted manual workflow is explicitly
run on `refs/heads/main`.

### Submission artifacts

- `README.md` — project narrative and reproduction;
- `submission/NuclidePath_Track2_Deck.pptx` — ten-slide core Track 2 deck;
- `submission/NuclidePath_Project_Specification.pdf` — current specification;
- `submission/ARTIFACT_MANIFEST.json` — twenty-two tracked visual, editorial and AMD evidence hashes;
- `docs/RELEASE_STATE.md` — source/evidence/submission boundary;
- `docs/SCIENTIFIC_VALIDATION_GATE.md` — offline calibration/hold-out contract;
- `docs/SUBMISSION_CHECKLIST.md` — release gates.