# Silent Vision

Silent Vision recognizes a personalized catalog of fixed phrases from a short,
silent camera clip. It is not open-vocabulary lipreading and does not transcribe
arbitrary speech.

The browser records a 2-5 second WebM clip with audio disabled. Before recording,
the user selects the language; Silent Vision does not infer it from the clip. CPU
code decodes the video, detects one face, aligns it, and extracts a 96 x 96
grayscale mouth sequence. The official classifier then trains and runs in
PyTorch on AMD Radeon through ROCm. An accepted result gets its exact text and
business intent from the registered phrase catalog.

The official Radeon run completed on 2026-08-06 with 73 known clips and 15
unrelated clips. The frozen final evaluation achieved 12/12 phrase top-1
accuracy, accepted 5/12 known clips, and rejected 9/10 unrelated clips; one
unrelated clip was falsely accepted. These are personalized, same-speaker,
fixed-phrase results, not an open-vocabulary or cross-speaker claim. The recorded
demonstration remains pending.

Repository: <https://github.com/fangjixin/silent-vision>

## Current Catalog and Product Boundary

The fixed-phrase checkpoint schema has one learned class per enabled `phraseId`.
`UNKNOWN` is a rejection result, not a trained class. The current catalog is one
four-phrase bilingual catalog:

| phraseId | Exact displayed text | Language | Mapped intent |
| --- | --- | --- | --- |
| `zh_light_on_hello` | `你好，请帮我打开灯` | `zh` | `LIGHT_ON` |
| `zh_chat_meal` | `你吃饭了吗？` | `zh` | `CHAT_OTHER` |
| `en_light_on_hello` | `Hello, please turn on the light.` | `en` | `LIGHT_ON` |
| `en_chat_meal` | `Have you eaten?` | `en` | `CHAT_OTHER` |

The user selects the language before a clip starts; the service validates that
selection rather than guessing a language from visual input. For that request,
the Torch classifier calculates a selected-language softmax over only the
enabled phrases in the selected language. It then emits exact text from the
checkpoint catalog only when the probability and centroid-distance gates pass.
Otherwise it emits the heuristic `UNKNOWN` rejection result without matched
phrase text.

An accepted `LIGHT_ON` decision can cross the current agent boundary as
`action="execute"`; an accepted `CHAT_OTHER` decision becomes `action="ignore"`;
a rejected clip becomes `action="reject"`. This repository returns structured
decisions only. It does not control a light, door, camera recorder, or editing
application.

The same boundary can be integrated into a creator workflow as a deliberate,
hands-free command input, but that downstream integration is outside this
repository. Before connecting an executable intent to any device or production
tool, add an allowlist, confirmation policy, adapter, and failure handling.

## System Architecture

```text
Browser camera (audio: false)
  -> user-selected language
  -> 2-5 second WebM over WebSocket
  -> PyAV decode and 25 FPS resampling on CPU
  -> MediaPipe single-face detection and landmarks on CPU
  -> alignment and 96 x 96 grayscale mouth crop on CPU
  -> fixed-phrase Torch model on AMD Radeon / ROCm
  -> selected-language softmax + probability and phrase-centroid distance acceptance
  -> exact phrase text and intent from the checkpoint catalog
  -> command.result
  -> agent.result (execute, ignore, or reject)
```

FastAPI creates a short-lived session at `POST /api/sessions` and accepts the
clip at `/ws/{sessionId}`. Health endpoints are available at `/health/live` and
`/health/ready`. WebSocket origins are restricted by `ALLOWED_ORIGINS`.

The Torch model downsamples each mouth frame to 16 x 16, combines appearance
with the signed adjacent-frame difference, projects the result to 64 features,
and applies two depthwise-separable temporal blocks. Attentive pooling feeds a
normalized embedding and a dynamic phrase head. The implementation enforces a
trainable-parameter cap below 150,000.

The checkpoint stores one calibrated minimum probability and a maximum cosine
distance for each phrase's training centroid. Both gates must pass. Top-1 margin
is reported only as a diagnostic; it is not an acceptance gate for the
fixed-phrase Torch model. Rejected output has intent `UNKNOWN`, contains no
matched phrase text, and cannot execute.

## Requirements

Use Python 3.11. Runtime dependencies and their exact version ranges are in
[`requirements.txt`](requirements.txt):

- FastAPI, Uvicorn, Pydantic, and pydantic-settings for the service;
- NumPy, OpenCV, PyAV, MediaPipe, and Pillow for CPU video preprocessing;
- orjson and python-multipart for API serialization and uploads.

[`requirements-dev.txt`](requirements-dev.txt) adds pytest, browser-test tools,
Ruff, ReportLab, pypdf, pdfplumber, and QR-code support. `package.json` records
the Playwright dependency.

PyTorch is intentionally not installed from `requirements.txt`. The AMD machine
must supply a PyTorch build compatible with its ROCm image. Training and the
production Torch backend fail closed unless `torch.version.hip` is non-empty,
`torch.cuda.is_available()` is true, and `cuda:0` is visible. PyTorch uses the
name `cuda:0` for its ROCm device namespace; this does not mean an NVIDIA runtime
is in use.

Local development setup:

```bash
cd /path/to/silent-vision
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm install
```

A current Chromium-based browser is recommended. Camera access requires a
secure context; `http://localhost` is allowed for local work, while a remote
browser should use HTTPS.

## 1. Record Phrase Samples

Prototype mode is an explicit recording and data-inspection mode. It is not the
official classifier demo. On the Radeon workspace, start it with:

```bash
cd /path/to/silent-vision
export PERSISTENCE_ROOT=/workspace/persistent/silent-vision
export COMMAND_BACKEND=prototype
export ALLOWED_ORIGINS='*'
bash scripts/amd_real_oneclick.sh
```

Open the emitted local or tunnel URL. In the Calibration panel, save independent
takes under `profileId=global` by selecting the registered catalog phrase; the
catalog supplies its exact text, language, and mapped intent. Free-form text is
only for unrelated clips with source intent `UNKNOWN`, which are used only for
rejection calibration and final evaluation.

Official evidence requires 15 independent takes for each of the four phrases
(10 training, 2 threshold-calibration, and 3 final-evaluation clips), plus at
least 15 unrelated clips spanning both selected languages (5 for calibration and
10 for final evaluation). Duplicate sample IDs or duplicate mouth-array hashes
are excluded. Source recordings and metadata are never rewritten by the manifest
builder. Do not train or report bilingual results until English recordings exist
and the final evaluation report is complete.

Inspect the stored profile:

```bash
/opt/venv/bin/python scripts/inspect_prototypes.py \
  --root /workspace/persistent/silent-vision
```

## 2. Build Immutable Manifests

Build the five disjoint manifests and their inventory from the global profile:

```bash
/opt/venv/bin/python scripts/build_command_manifest.py \
  --profile-root /workspace/persistent/silent-vision/profiles \
  --catalog command/phrase_catalog.json \
  --output-dir /workspace/persistent/silent-vision/manifests \
  --seed 17
```

The command fails when the official sample minimums are not met. For a local or
Radeon execution smoke only, append `--allow-small-dataset`. The resulting
inventory records `evidentiary: false` and must not support performance claims.

The catalog owns the corrected phrase label and intent. The source intent is
retained in each manifest row as `source_intent`, so a mislabeled recording can
be audited without editing the source files.

## 3. Train and Calibrate on ROCm

Training optimizes only on `train.jsonl` and calibrates only on the two
calibration partitions. It nevertheless requires all five role manifests so it
can validate their inventory hashes, official counts, and cross-split sample/ROI
disjointness before binding the complete lineage into the checkpoint. It has no
CPU classifier fallback.

```bash
mkdir -p /workspace/persistent/silent-vision/models \
  /workspace/persistent/silent-vision/reports

/opt/venv/bin/python scripts/train_command_classifier.py \
  --catalog command/phrase_catalog.json \
  --inventory /workspace/persistent/silent-vision/manifests/inventory.json \
  --train-manifest /workspace/persistent/silent-vision/manifests/train.jsonl \
  --calibration-known /workspace/persistent/silent-vision/manifests/calibration-known.jsonl \
  --calibration-unknown /workspace/persistent/silent-vision/manifests/calibration-unknown.jsonl \
  --evaluation-known /workspace/persistent/silent-vision/manifests/evaluation-known.jsonl \
  --evaluation-unknown /workspace/persistent/silent-vision/manifests/evaluation-unknown.jsonl \
  --output /workspace/persistent/silent-vision/models/fixed-phrase.pt \
  --run-summary /workspace/persistent/silent-vision/reports/training-run.json \
  --epochs 80 \
  --seed 17
```

For an inventory created with `--allow-small-dataset`, a shorter epoch count may
be used to check execution. That checkpoint and run summary remain
non-evidentiary.

## 4. Run the Frozen Final Evaluation

After training and calibration have frozen the checkpoint thresholds, evaluate
only the untouched final partitions:

```bash
/opt/venv/bin/python scripts/validate_command_classifier.py \
  --checkpoint /workspace/persistent/silent-vision/models/fixed-phrase.pt \
  --catalog command/phrase_catalog.json \
  --inventory /workspace/persistent/silent-vision/manifests/inventory.json \
  --train-manifest /workspace/persistent/silent-vision/manifests/train.jsonl \
  --calibration-known /workspace/persistent/silent-vision/manifests/calibration-known.jsonl \
  --calibration-unknown /workspace/persistent/silent-vision/manifests/calibration-unknown.jsonl \
  --known-manifest /workspace/persistent/silent-vision/manifests/evaluation-known.jsonl \
  --unknown-manifest /workspace/persistent/silent-vision/manifests/evaluation-unknown.jsonl \
  --output /workspace/persistent/silent-vision/reports/final-evaluation.json
```

The JSON report records counts and denominators for phrase accuracy,
mapped-intent accuracy, known acceptance, accepted-phrase accuracy, and unknown
false acceptance/rejection. It also records an explicit evidence status, the
verified inventory/checkpoint lineage, effective threshold source, checkpoint
hash, all five manifest hashes, backend, and device. A renamed, mixed, reused,
non-evidentiary, or lineage-mismatched bundle is rejected. Do not tune thresholds
on these final partitions.

Run one checkpoint-backed mouth-ROI clip with:

```bash
/opt/venv/bin/python scripts/infer_command_clip.py \
  --checkpoint /workspace/persistent/silent-vision/models/fixed-phrase.pt \
  --mouth-roi /absolute/path/to/mouth_roi.npy \
  --language zh
```

## 5. Start the Official Radeon Demo

The official launchers default to the Torch backend and stop before startup when
the ROCm device or phrase checkpoint is unavailable:

```bash
cd /path/to/silent-vision
export PERSISTENCE_ROOT=/workspace/persistent/silent-vision
export COMMAND_BACKEND=torch
export COMMAND_CLASSIFIER_CHECKPOINT=/workspace/persistent/silent-vision/models/fixed-phrase.pt
export ALLOWED_ORIGINS='*'
bash scripts/amd_real_oneclick.sh
```

In a second Radeon terminal, expose port 8000 if the event image provides
`rc-tunnel`:

```bash
$HOME/.local/bin/rc-tunnel expose --port 8000
```

Restrict `ALLOWED_ORIGINS` to the final public origin when practical. The
application itself does not provide authentication or TLS termination.

For a checkpoint-backed ROCm smoke, provide one real mouth-ROI sample:

```bash
export COMMAND_CLASSIFIER_CHECKPOINT=/workspace/persistent/silent-vision/models/fixed-phrase.pt
export COMMAND_SMOKE_SAMPLE=/absolute/path/to/mouth_roi.npy
export COMMAND_SMOKE_LANGUAGE=zh
bash scripts/smoke_rocm.sh
```

This smoke proves that the guarded Torch path executes on `cuda:0`; it does not
replace the untouched final-evaluation report.

## Other Development Modes

Fake mode is for deterministic API and browser-flow tests only:

```bash
export COMMAND_BACKEND=fake
export ALLOWED_ORIGINS=http://localhost:8000
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Prototype mode compares saved examples and supports collection/debugging. It is
not a fallback in the official Torch startup and is not Radeon classifier
evidence.

## Persistent Artifacts

```text
/workspace/persistent/silent-vision/
|-- profiles/global/<SOURCE_INTENT>/<sample-id>/
|   |-- original.webm
|   |-- mouth_roi.npy
|   |-- embedding.npy
|   `-- metadata.json
|-- manifests/
|   |-- inventory.json
|   |-- train.jsonl
|   |-- calibration-known.jsonl
|   |-- calibration-unknown.jsonl
|   |-- evaluation-known.jsonl
|   `-- evaluation-unknown.jsonl
|-- models/fixed-phrase.pt
|-- reports/training-run.json
`-- reports/final-evaluation.json
```

Recordings, checkpoints, and private reports remain outside Git. The contest
bundle contains the source, phrase catalog, README, generated project profile,
poster, and demo script, while excluding those private artifacts.

## Verification

Local tests that require Torch skip when Torch is not installed:

```bash
.venv/bin/python -m pytest -q
```

Generate and verify the submission assets:

```bash
.venv/bin/python scripts/generate_submission_assets.py
.venv/bin/python -m pytest -q tests/test_deployment_files.py tests/test_submission_docs.py tests/test_contest_bundle.py
.venv/bin/python scripts/build_contest_bundle.py
```

## Privacy and Limitations

- Browser capture requests video only; this application sets `audio: false`.
- Normal command clips are processed from memory and a temporary decode file.
- Prototype recording mode persists the original video and derived arrays. The
  repository has no consent or retention UI; operators must define a policy.
- Recognition is personalized and closed-set. Camera angle, lighting,
  occlusion, speaking style, and sample quality can change results.
- Probability and centroid-distance rejection is a calibrated heuristic, not a
  guarantee that every unrelated phrase will be rejected.
- The current source returns structured decisions only and contains no physical
  device or creator-tool integration.
- No performance figure is published until the official final-evaluation report
  exists.

## Submission Materials

English submission materials are indexed in
[`submission/README.md`](submission/README.md). The required pull request title
is `Track 1, Jixin Fang, Silent Vision`.
