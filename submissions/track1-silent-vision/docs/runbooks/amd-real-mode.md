# AMD Radeon / ROCm Runbook

Silent Vision's official classifier path uses the ROCm Python environment:

```bash
/opt/venv/bin/python
```

The Torch phrase classifier has no CPU fallback. Video decode, face detection,
alignment, and mouth cropping remain CPU preprocessing.

## Official Torch Startup

From the synchronized repository on the AMD machine:

```bash
cd /path/to/silent-vision
export PERSISTENCE_ROOT=/workspace/persistent/silent-vision
export COMMAND_BACKEND=torch
export COMMAND_CLASSIFIER_CHECKPOINT=/workspace/persistent/silent-vision/models/fixed-phrase.pt
export ALLOWED_ORIGINS='*'
bash scripts/amd_real_oneclick.sh
```

The setup and startup scripts fail closed when the checkpoint is missing, HIP is
unavailable, `cuda:0` is not visible, or a one-element allocation on the device
fails. They print the Python executable, PyTorch version, HIP version, device
availability, selected device, and device name before Uvicorn starts.

The launchers default to `COMMAND_BACKEND=torch` and to
`$PERSISTENCE_ROOT/models/fixed-phrase.pt`; the explicit exports above make the
demo inputs visible in the terminal recording.

In a second AMD terminal, expose the service if the event image provides
`rc-tunnel`:

```bash
$HOME/.local/bin/rc-tunnel expose --port 8000
```

Open the emitted HTTPS URL from the browser that has the camera. Replace `*`
with the final public origin when practical.

## Explicit Prototype Recording Mode

Prototype mode is for recording and inspecting samples. It is not the official
classifier demo and is never selected automatically as a fallback.

```bash
cd /path/to/silent-vision
export PERSISTENCE_ROOT=/workspace/persistent/silent-vision
export COMMAND_BACKEND=prototype
export ALLOWED_ORIGINS='*'
bash scripts/amd_real_oneclick.sh
```

The launcher prints `Recording mode` before startup. Save independent takes to
the global profile by selecting the registered catalog phrase; the catalog
supplies the exact text, language, and mapped intent. Use free-form text only for
unrelated clips with source intent `UNKNOWN`.

## Build the Dataset Partitions

```bash
/opt/venv/bin/python scripts/build_command_manifest.py \
  --profile-root /workspace/persistent/silent-vision/profiles \
  --catalog command/phrase_catalog.json \
  --output-dir /workspace/persistent/silent-vision/manifests \
  --seed 17
```

The official command requires 15 independent takes for each registered phrase
and 15 unrelated clips spanning both zh and en. Append
`--allow-small-dataset` only for an execution smoke; that inventory is marked
non-evidentiary.

## Train and Calibrate

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

Training authenticates the inventory and all five manifest roles, checks official
counts plus sample-ID/ROI-hash disjointness, trains only on the training role,
calibrates only on the calibration roles, and binds the full lineage and frozen
thresholds into the checkpoint. Evaluation roles are validated but never used
for training or calibration.

## Frozen Final Evaluation

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

Do not pass threshold overrides for official evidence. The command verifies the
complete inventory/checkpoint lineage and rejects non-evidentiary, renamed,
mixed, or overlapping bundles before evaluating the untouched final partitions.
It writes metric numerators, denominators, an explicit evidence status, all five
manifest hashes, threshold provenance, backend, and device.

## One-Clip and ROCm Smoke Checks

```bash
/opt/venv/bin/python scripts/infer_command_clip.py \
  --checkpoint /workspace/persistent/silent-vision/models/fixed-phrase.pt \
  --mouth-roi /absolute/path/to/mouth_roi.npy \
  --language zh
```

```bash
export COMMAND_CLASSIFIER_CHECKPOINT=/workspace/persistent/silent-vision/models/fixed-phrase.pt
export COMMAND_SMOKE_SAMPLE=/absolute/path/to/mouth_roi.npy
export COMMAND_SMOKE_LANGUAGE=zh
bash scripts/smoke_rocm.sh
```

The smoke verifies the guarded Torch path and a checkpoint-backed prediction on
`cuda:0`. It is not a substitute for final evaluation.

## Runtime Notes

- `Start` records one 2-5 second clip and submits it once.
- Recognition starts after the complete clip arrives.
- An accepted result displays exact catalog text and the mapped intent.
- A clip that fails either the probability or centroid-distance gate returns
  `UNKNOWN` and cannot execute.
- Top-1 margin is diagnostic only for the fixed-phrase Torch path.
- `Cancel` ends the active capture and releases the server session.
- Debug artifacts are saved only when `DEBUG_DUMP_WINDOWS=true`.
