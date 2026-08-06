# Silent Vision Demo Video Script

Status: official Radeon training and evaluation complete; video recording
pending. Target length: 3-5 minutes.

This script demonstrates the application that exists in the repository: one
silent clip in a user-selected language, one fixed-phrase decision, and an
explicit rejection path. It does not stage a physical-device or content-creation
action.

## Recording Checklist

- Record the real terminal and browser in one continuous take.
- Show `/opt/venv/bin/python`, the PyTorch version, `torch.version.hip`,
  accelerator availability, and the Radeon device name.
- Start with `COMMAND_BACKEND=torch` and the actual checkpoint path.
- Show whether the inventory and checkpoint are official or were created with
  `--allow-small-dataset`.
- If the artifacts are non-evidentiary, say that they prove execution only and
  show no accuracy claim.
- Select the language in the browser before recording. Do not describe it as
  inferred from the clip.
- Use one registered phrase and one unrelated or deliberately ambiguous clip.
- Keep the returned phrase metadata, acceptance decision, and agent action
  visible.
- Do not paste simulated GPU output or edit benchmark values into the video.
- Add the final URL to `submission/README.md` and
  `submission/pull-request-description.md` after upload.

## 0:00-0:40 - Problem and Scope

**On screen:** Repository README, phrase catalog, then the browser.

**Say:**

“Silent Vision is a personalized fixed-phrase visual classifier for situations
where audio is unavailable, unreliable, or unwanted. The browser records a
short camera clip with audio disabled. This is not open-vocabulary lipreading.
The model chooses between registered phrase IDs, and accepted text and intent
come from this catalog. The current source returns a structured decision; it
does not operate a physical device or content-creation tool.”

**Show:** `command/phrase_catalog.json`, including all four registered phrases:
Chinese `你好，请帮我打开灯` and `你吃饭了吗？`, and English
`Hello, please turn on the light.` and `Have you eaten?`.

## 0:40-1:25 - Radeon Environment and Startup

**On screen:** Run these commands rather than using a prepared screenshot.

```bash
/opt/venv/bin/python - <<'PY'
import torch
print("torch:", torch.__version__)
print("HIP:", torch.version.hip)
print("available:", torch.cuda.is_available())
print("device:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
PY

export PERSISTENCE_ROOT=/workspace/persistent/silent-vision
export COMMAND_BACKEND=torch
export COMMAND_CLASSIFIER_CHECKPOINT=/workspace/persistent/silent-vision/models/fixed-phrase.pt
export ALLOWED_ORIGINS='*'
bash scripts/start_real_rocm.sh
```

**Say:**

“This is the Python and PyTorch environment used by the server. A non-empty HIP
value and the displayed Radeon device identify the ROCm build. The startup guard
stops when ROCm or the phrase checkpoint is missing. PyAV decode, MediaPipe face
detection, alignment, and mouth cropping run on CPU. The fixed-phrase Torch
model runs on the Radeon device shown as `cuda:0`.”

## 1:25-2:20 - Accepted Exact Phrase

**On screen:** Open the HTTPS tunnel URL. Record one registered phrase. Keep the
result JSON and visible phrase result in frame. First select the same language
as the phrase in the browser.

Suggested phrase: `你好，请帮我打开灯`.

**Say:**

“I selected the language before recording; the application does not infer it.
For this request, the model applies selected-language softmax only among phrases
in that language, then predicts a stable phrase ID and normalized embedding.
Acceptance requires both the checkpoint probability threshold and this phrase's
maximum distance from its training centroid. The text on screen is copied exactly
from the checkpoint catalog, and the catalog maps it to `LIGHT_ON`.”

**Show:** `backend: "torch"`, accepted status, `phraseId`, exact displayed text,
mapped intent, `openSetDistance`, threshold values, and
`thresholdSource: "checkpoint"`. Margin may be visible, but describe it only as
a diagnostic.

If the recorded checkpoint does not accept the live clip, do not retry until a
desired result appears and call that evaluation. Explain the failure and use a
known checkpoint-backed sample for an execution smoke if needed.

## 2:20-3:05 - Rejection Path

**On screen:** Record an unrelated phrase or a deliberately ambiguous clip.

**Say:**

“This clip is not one of the registered phrases. When either probability or
phrase-centroid distance fails, the public result becomes `UNKNOWN`. It contains
no matched phrase text, the agent action is `reject`, and no executable route is
available. This is calibrated heuristic rejection, not a guarantee for every
possible unseen phrase.”

**Show:** rejected status, `UNKNOWN`, rejection reason, and the agent action.

## 3:05-3:45 - Evidence Boundary and Close

**On screen:** Show `inventory.json`, the training run summary, and final
evaluation report if official artifacts exist; otherwise show the
`evidentiary: false` field and do not show performance figures.

**Say for an official run:**

“The manifest builder hashes immutable recordings and keeps training,
calibration, and final evaluation separate. Thresholds were frozen before this
final report. The report includes metric numerators and denominators, partition
hashes, checkpoint hash, backend, and device.”

**Say for a small-data smoke:**

“This inventory is explicitly non-evidentiary. The run proves that manifest
building, Radeon training, checkpoint loading, and inference execute end to end.
It does not support an accuracy or rejection-rate claim.”

For this official run, show the measured counts rather than saying evidence is
pending: 12/12 phrase top-1 accuracy, 5/12 known acceptance, 5/5 accepted known
phrase accuracy, 9/10 unrelated rejection, and 5/6 accepted precision. State
that these are personalized, same-speaker fixed-phrase results.

**Close:**

“Silent Vision turns a deliberate silent clip into a small, inspectable phrase
decision. CPU preprocessing feeds a fixed-phrase classifier on AMD Radeon and
ROCm. Uncertain clips stop at the rejection boundary. The source and submission
materials are available at github.com/fangjixin/silent-vision.”

Stop only after the repository URL is readable.
