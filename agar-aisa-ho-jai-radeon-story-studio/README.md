# Agar Aisa Ho Jai — Radeon Story Studio

**AMD AI DevMaster Hackathon — Track 1: Multimodal AI**
**Participant:** Ankur Sawhney
**Public snapshot source commit:** `eba2f1544f03fbc6e7ad6dd137138147e5be3f26`

Agar Aisa Ho Jai — Radeon Story Studio is the contest-facing part of **Agar Aisa Ho Jai**, a content-production system that turns a short educational idea into a structured, reviewable storyboard and child-safe visual lesson.

The submission contains two complementary Radeon/ROCm workflows:

1. **Radeon Story Studio** — SDXL Turbo image inference through PyTorch, Diffusers, and ROCm on an AMD Radeon GPU. It creates candidate story panels, records runtime evidence and hashes, and fails closed until technical, safety, semantic, and continuity review pass.
2. **Animal Storyboard Factory** — a locally served Qwen model through vLLM on AMD Radeon generates a constrained storyboard plan and performs an independent textual safety review. Pillow and FFmpeg then create a deterministic preview animatic on CPU.

No closed-source online inference API performs either core workflow in this public snapshot.

## Why it matters

Generative media can look polished while depicting the wrong action. This project separates generation from acceptance. Hazard scenes, character reactions, and adult-assistance scenes are generated as distinct content classes; candidates are not accepted merely because inference succeeded.

## Architecture

```text
Transcript / sealed scene manifest
              |
              +--> Local Qwen + vLLM on Radeon/ROCm
              |       -> structured storyboard + textual safety review
              |
              +--> Local SDXL Turbo + Diffusers on Radeon/ROCm
                      -> candidate images + runtime/benchmark evidence
                                      |
                                      v
                   deterministic validation + human editorial review
                                      |
                                      v
                         accepted lesson card / storyboard
```

## Environment

Validated evidence in this snapshot records:

- AMD Radeon GPU architecture: `gfx1100`
- PyTorch: `2.9.1+rocm7.2.1.gitff65f5bc`
- HIP: `7.2.53211-e1a6bc5663`
- SDXL Turbo immutable revision: `71153311d3dbb46851df1931d3ca6e939de83304`
- Qwen workload served locally through vLLM
- Python 3.12 on the successful Radeon Cloud run

Install the contest dependencies **inside an environment that already contains a working ROCm-enabled PyTorch build**:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Do not replace a working ROCm PyTorch installation with a generic PyPI `torch` wheel.

## Fast local validation

```bash
python3 tools/episode_factory/amd_story_studio.py validate   examples/story-studio-manifest.json

python3 -m compileall -q src tests

python3 -m unittest -v   tests.test_amd_story_studio   tests.test_radeon_cloud_execution   tests.test_radeon_cloud_session   tests.test_radeon_runtime_discovery
```

## Prepare the sealed Radeon image-generation package

```bash
python3 tools/episode_factory/manage_amd_story_studio.py prepare   --manifest examples/story-studio-manifest.json   --output-directory /tmp/aahj-radeon-story-studio   --remote-python /workspace/aahj-rocm-venv/bin/python

python3 tools/episode_factory/manage_amd_story_studio.py inspect-package   /tmp/aahj-radeon-story-studio/execution-package.tar.gz
```

The remote runner validates that `torch.version.hip` is non-empty, an AMD Radeon device is present, and a real tensor operation succeeds on PyTorch's `cuda:0` ROCm device API.

## Run the Qwen storyboard workflow

Start a local OpenAI-compatible vLLM endpoint on the Radeon machine and expose it only on a trusted interface. The supplied example uses loopback:

```bash
python3 src/storyboard_factory/factory.py   --config examples/storyboard-factory-config.json   --transcript examples/sample-transcript.txt   --output /tmp/aahj-storyboard-output
```

The 17.7 GB GGUF model used for the measured run is intentionally not bundled. Model metadata and measured outputs are under `evidence/qwen/`.

## Measured results

### SDXL Story Studio

- 8 measured candidates
- 10.504696 seconds measured candidate phase
- 0.368234-second median candidate latency
- 45.693848 candidates per minute
- 10,451,900,416 bytes peak allocated GPU memory
- Technical acceptance passed; incomplete semantic scenes were rejected rather than silently accepted

### Qwen Storyboard Factory

- 7-scene storyboard with 6 cast members
- 1,259 completion tokens in 14.941 seconds for planning
- 84.264 completion tokens/second for planning
- 315 completion tokens in 5.395 seconds for textual safety review
- 7 of 7 motion scenes and semantic action checks validated

## Evidence and accepted output

- `assets/accepted-safe-lesson-card.png` — accepted deterministic lesson card built from Radeon-generated source assets
- `evidence/sdxl/` — immutable model/runtime summaries, measured performance, accepted-output report, and rejected-candidate reasons
- `evidence/qwen/` — runtime metrics, Radeon telemetry, storyboard plan, motion evidence, and safety-review output
- `docs/` — design decisions, failure analysis, and workload boundaries

The safety pass for the Qwen workflow applies to the structured textual storyboard. It is not presented as a multimodal judgment of every rendered frame.

## Privacy and publication boundary

This folder was constructed from an explicit allowlist at one immutable Git commit. It excludes private real-person/children corpora, Codex context archives, nested repositories, local sessions, credentials, personal paths, model weights, rejected raw media, historical campaigns, unrelated provider adapters, and uncommitted work. See `PRIVACY_AND_SCOPE.md`.

## Demo and documents

- **Demo video:** https://youtu.be/JSiUvk6Xhog
- **Project Profile:** `submission/Project_Profile_Agar_Aisa_Ho_Jai_Radeon_Story_Studio.pdf`
- **Presentation:** `submission/AAHJ_Radeon_Story_Studio_Presentation.pptx`
- **Presentation PDF:** `submission/AAHJ_Radeon_Story_Studio_Presentation.pdf`
- **Video details:** `submission/DEMO_VIDEO.md`

## License and third-party components

See `LICENSE` and `THIRD_PARTY_NOTICES.md`. The source code is made available for hackathon review under the stated terms; model and framework licenses remain governed by their respective owners.
