# AMD Track 1 Competition Package

This document is the canonical map for the Team Banyan submission.

## Identity

| Field | Value |
|---|---|
| Team | Banyan |
| Application | ProofLaunch |
| Direction | Multimodal GTM Studio |
| Track | Track 1 — Development of Multimodal Content Creation Tools |
| GitHub submitter | `sylvanccc` |
| Repository destination | `prooflaunch/` |
| PR title | `Track 1, Banyan, ProofLaunch: Multimodal GTM Studio` |
| Official language | English |

## Judge route

1. Read [`JUDGE_START_HERE.md`](../JUDGE_START_HERE.md).
2. Review the required [`ProofLaunch_Project_Profile.pdf`](ProofLaunch_Project_Profile.pdf).
3. Review the [`ProofLaunch_Submission_Deck.pptx`](ProofLaunch_Submission_Deck.pptx).
4. Open the finished product website at `web/index.html` and start at
   `/control/frontier-gtm`.
5. Run the truth-bounded local replay:

   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   python -m pip install -e .
   .venv/bin/python demos/run_track1_demo.py
   ```

6. Inspect the generated receipt and hash-bound campaign pack.
7. Watch the Demo Video (official guidance recommends 3–5 minutes) and compare
   its live Radeon receipt with the exported evidence manifest.

## Required deliverables

| Requirement | Public path | State |
|---|---|---|
| Project Profile PDF | `docs/ProofLaunch_Project_Profile.pdf` | Ready |
| Complete source | `src/`, `scripts/`, `web/`, `notebooks/` | Ready for reviewed export |
| Finished product website | `web/index.html` → `/control/frontier-gtm` | Ready |
| English setup and reproduction | `README.md`, `docs/INSTALLATION.md` | Ready |
| AMD Radeon / ROCm adaptation | `docs/RADEON_SETUP.md` | Mechanically ready; live receipt pending |
| Model and algorithm description | `docs/MODEL_CARD.md` | Ready |
| Architecture | `docs/ARCHITECTURE.md` | Ready |
| Evaluation and evidence | `docs/EVALUATION.md`, `SUBMISSION_GATE.json` | Local evidence ready; live Radeon pending |
| Supplementary PPT | `docs/ProofLaunch_Submission_Deck.pptx` | Ready |
| Demo Video (3–5 minutes recommended) | `docs/ProofLaunch_Demo_Video_191s.mp4`, `docs/demo-video-url.txt` | Included — 190.9-second product operation; live Radeon evidence remains separate |
| English PR body | `submission/track1-prooflaunch/PR_BODY.md` | Open at PR #308 |

## Product scope

ProofLaunch converts approved product evidence into a governed campaign pack:
strategy, messaging, channel copy, calendar, SEO/GEO, analytics, image, audio,
and video. It binds claims to source spans, audits multimodal candidates,
allows at most two recorded repair rounds, and stops at an authenticated human
release boundary.

The competition core does not use a closed online API for key inference. Local
model roles are sequenced so only one heavy model is resident at a time.

## Truth boundary

The local replay verifies workflow, artifact registration, approvals, hashes,
and export mechanics. It is not new Radeon inference. The product-operation
Demo Video is included; the submission remains blocked until the final package
contains independently inspectable live Radeon hardware/model receipts.

## Public export

Never push the 6GB working directory. Build a reviewed export:

```bash
python scripts/build_amd_public_export.py
python scripts/validate_amd_public_export.py dist/amd-track1/prooflaunch
```

The output includes a file-level SHA-256 manifest and excludes credentials,
private runtime state, caches, research workbenches, raw teacher outputs, and
unreviewed media.
