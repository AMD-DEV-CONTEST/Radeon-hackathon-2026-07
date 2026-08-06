# Qingxi Rift - Character Workshop - Local Testing Guide (Windows)

For **MOCK mode** (no AMD GPU needed / no large model downloads). Used to verify: environment, unit tests, regression scripts, and the full Web workshop flow.

**Code location (worktree):**

```text
D:\APP\...\.worktrees\character-workshop\character-workshop
```

In the rest of this guide, `$APP` refers to that directory.

---

## 0. Prerequisites

| Item | Requirement |
|----|------|
| OS | Windows 10/11 |
| Python | 3.10+ (verified locally on 3.11.5) |
| Network | First `pip install` needs access to PyPI |
| GPU | **Not needed** (MOCK=1) |
| Terminal | **PowerShell** (recommended) |

Check Python:

```powershell
python --version
```

You should see `Python 3.10.x` or higher.

---

## 1. Enter the directory and create a virtual environment (recommended, required on first run)

```powershell
cd "D:\APP\...\.worktrees\character-workshop\character-workshop"

python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If it says scripts cannot be run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

Confirm your prompt is prefixed with `(.venv)`.

---

## 2. Install dependencies (first time / after dependency changes)

For **local MOCK testing only**, you can install the slim set first (faster):

```powershell
pip install -U pip
pip install pytest pydantic pyyaml Pillow numpy gradio
```

Or install per the project files (pulls transformers/diffusers etc., slower, but matches the repo):

```powershell
pip install -r requirements-dev.txt
```

> Note: `requirements.txt` contains `transformers`/`diffusers`. Local MOCK does **not load** the large models, but the install size is big. In a hurry, use the slim `pip install` above to get tests and the UI running.

---

## 3. Turn on the MOCK environment variable (set every time you open a new terminal)

```powershell
$env:MOCK = "1"
```

Verify:

```powershell
echo $env:MOCK
# should output 1
```

Optional: check whether device detection recognizes mock:

```powershell
python -c "from src.device import detect_device; print(detect_device())"
```

Expected: `mock_mode=True` (with or without a GPU).

---

## 4. Automated tests (command line)

### 4.1 All unit tests

```powershell
cd "D:\APP\...\.worktrees\character-workshop\character-workshop"
$env:MOCK = "1"
pytest -v
```

**Expected:** `16 passed` (or everything green as of now).

### 4.2 Run a single module only

```powershell
pytest tests/test_device.py -v
pytest tests/test_world.py -v
pytest tests/test_models_schema.py -v
pytest tests/test_llm_role.py -v
pytest tests/test_card_compose.py -v
pytest tests/test_image_gen_mock.py -v
pytest tests/test_orchestrator.py -v
```

### 4.3 Eval-case regression (24 settings -> JSON)

```powershell
$env:MOCK = "1"
python scripts\run_eval_json.py
```

**Expected:** the last line looks like:

```text
summary ok=24 fail=0
```

### 4.4 UI import smoke test without launching a browser

```powershell
$env:MOCK = "1"
python -c "from app import build_app; a=build_app(); print('ok', type(a))"
```

**Expected:** prints `ok <class 'gradio.blocks.Blocks'>` with no Traceback.

---

## 5. End-to-end: generate one character card from the command line

Without opening a browser, test the orchestrator directly:

```powershell
$env:MOCK = "1"
python -c @"
from src.orchestrator import generate_card_job, JobState
r = generate_card_job(
    user_text='A green-robed Void traveler carrying a paper lantern, calm and quiet',
    affinity_pref='Void',
    mock=True,
)
print('state=', r.state)
print('job_id=', r.job_id)
print('card=', r.card_path)
print('portrait=', r.portrait_path)
print('error=', r.error)
print('--- lore ---')
print(r.lore_md[:500] if r.lore_md else None)
assert r.state == JobState.READY
assert r.card_path and r.card_path.exists()
print('E2E OK')
"@
```

**Expected:**

- `state= JobState.READY` (or `ready`)
- `E2E OK`
- The output directory `outputs\<job_id>\` contains:
  `character.json`, `portrait.png`, `card.png`, `meta.json`, `input.txt`

To view the poster:

```powershell
# replace job_id below with the one printed above
explorer outputs
```

---

## 6. Manual Web UI testing (main path)

### 6.1 Start

```powershell
cd "D:\APP\...\.worktrees\character-workshop\character-workshop"
.\.venv\Scripts\Activate.ps1   # if not activated yet
$env:MOCK = "1"
python app.py
```

The terminal shows something like:

```text
Running on local URL:  http://127.0.0.1:7860
```

Open in browser: **http://127.0.0.1:7860**

To stop: `Ctrl + C` in the terminal.

### 6.2 Page check list

| # | Action | Expected result |
|---|------|----------|
| 1 | Look at the top bar | "Qingxi Rift - Character Workshop" title, tagline, device/mock info |
| 2 | Left side has | description box, reference image, six-affinity dropdown, generate card, revise, apply revision |
| 3 | Right side has | character card poster, settings, progress |
| 4 | Footer | AMD Radeon + ROCm / Qingxi Rift related text |

### 6.3 Case A - generate a character card (required)

1. Fill in **Describe the character**:

   ```text
   A green-robed Void traveler carrying a paper lantern, quiet, skilled at folding shortcuts through alleys
   ```

2. Set **Affinity preference** to: `Void`
3. Click **Generate Character Card**
4. Wait for the progress to finish (MOCK usually takes a few seconds)

**Pass criteria:**

- [ ] The character card poster appears on the right (portrait placeholder area + radar + text)
- [ ] The settings Markdown has name, primary affinity, appearance, etc.
- [ ] The progress box shows steps like `planning` / `imaging` / `composing` / `ready`
- [ ] No red error popup

### 6.4 Case B - revise (required)

1. After case A succeeds, **do not refresh the page**
2. Fill in **Revise the result**: `change to golden short hair`
3. Click **Apply Revision**

**Pass criteria:**

- [ ] Poster/settings update
- [ ] The settings or appearance-related text shows revision traces (MOCK writes the revision into appearance / prompt)
- [ ] No full-page crash

### 6.6 Case D - reference image (recommended)

1. Upload any local image (a selfie or sketch is fine)
2. Description: `red-haired Matter-affinity heavy armor, metal arm guards`
3. Affinity: `Matter`
4. Generate Character Card

**Pass criteria:**

- [ ] Card is generated successfully (under MOCK the reference image is saved; the art style being a placeholder is normal)
- [ ] `outputs\<job_id>\ref.png` exists (optional check)

### 6.7 Case E - validation and error messages

| Action | Expected |
|------|------|
| Click generate with an empty description | Shows a prompt to fill in the description (e.g. "Please fill in the character setting description") |
| Click "Apply Revision" before generating | Prompts to generate a character card first |

### 6.8 Case F - affinity sampling (optional)

Select each of `Form/Mind/Life/Matter/Void/Time` and generate a short description once each, confirming:

- [ ] All produce a card
- [ ] The primary affinity in the settings matches the selection (MOCK respects `affinity_pref`)

---

## 7. Outputs and directory layout

```text
character-workshop/
  outputs/<job_id>/
    input.txt          # raw user text
    ref.png            # if a reference image was uploaded
    character.json     # structured character
    portrait.png       # portrait (placeholder image in MOCK)
    card.png           # composed poster * the main file to check
    meta.json          # device and timing info
```

View the latest output:

```powershell
Get-ChildItem outputs -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { Get-ChildItem $_.FullName }
```

---

## 8. One-shot minimal acceptance script (copy the whole block)

In a fresh PowerShell, from scratch through all the automated checks:

```powershell
$APP = "D:\APP\...\.worktrees\character-workshop\character-workshop"
cd $APP

if (-not (Test-Path .\.venv)) { python -m venv .venv }
.\.venv\Scripts\Activate.ps1

pip install -q pytest pydantic pyyaml Pillow numpy gradio

$env:MOCK = "1"

Write-Host "=== pytest ===" -ForegroundColor Cyan
pytest -q
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

Write-Host "=== eval ===" -ForegroundColor Cyan
python scripts\run_eval_json.py
if ($LASTEXITCODE -ne 0) { throw "eval failed" }

Write-Host "=== build_app ===" -ForegroundColor Cyan
python -c "from app import build_app; build_app(); print('build_app OK')"

Write-Host "=== e2e job ===" -ForegroundColor Cyan
python -c "from src.orchestrator import generate_card_job, JobState; r=generate_card_job('Test Void traveler', affinity_pref='Void', mock=True); assert r.state==JobState.READY; print('e2e OK', r.job_id, r.card_path)"

Write-Host "ALL AUTOMATED CHECKS PASSED" -ForegroundColor Green
Write-Host "Next: python app.py  then open http://127.0.0.1:7860"
```

After all automated checks pass, run:

```powershell
$env:MOCK = "1"
python app.py
```

Then do the manual UI checklist in **Section 6**.

---

## 9. FAQ

| Symptom | Fix |
|------|------|
| `python` is not a recognized command | Install Python and check Add to PATH, or use `py -3.11` |
| `Activate.ps1` cannot be run | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `ModuleNotFoundError: gradio` | `pip install gradio` and make sure the venv is activated |
| `ModuleNotFoundError: src` | Must run from the `character-workshop` directory (the level that contains `app.py`) |
| Port 7860 already in use | `$env:PORT=7861; python app.py`, or kill the process holding the port |
| Forgot to set MOCK, real-inference error | Always `$env:MOCK="1"` locally; real models are only tested on Radeon Cloud |
| Chinese characters in paths look garbled | Use the fully quoted `cd "..."` path from above |
| pytest not found | `pip install pytest`, run inside the venv |
| UI opens but generation is slow | MOCK should be fast; check whether `MOCK=0` and a model is downloading |

Confirm the current MOCK value:

```powershell
python -c "import os; print('MOCK=', os.environ.get('MOCK'))"
```

---

## 10. Acceptance conclusion template (fill in after self-test)

```text
Date: ____
Python: ____
venv: yes / no

[ ] pytest all passed (____ passed)
[ ] run_eval_json ok=24 fail=0
[ ] build_app import succeeded
[ ] CLI E2E produced card.png
[ ] UI generated a character card
[ ] UI revision
[ ] UI empty-input error works

Verdict: PASS / FAIL
Notes:
```

---

## 11. Boundary with real cloud inference (avoid testing the wrong thing)

| Mode | Command | What it tests |
|------|------|--------|
| **Local MOCK** | `$env:MOCK="1"` | Flow, UI, card composition, tests (this guide) |
| **Radeon real inference** | `$env:MOCK="0"` + ROCm + model download | Real image quality (see the README Cloud section) |

Locally, do **not** use "does the image look like a great anime production" as the MOCK pass criteria; the MOCK portrait is a placeholder image. What matters: flow completes, card composition is correct, interactions do not crash.

---

## 12. Recommended test order

1. Sections 1-2: environment and dependencies
2. Section 8: one-shot automation
3. Section 6: manual UI checklist

If any step fails, keep the full terminal output for troubleshooting.

---

## Related documents

- English README: `README.md` (one directory up from docs)
- Design spec: repo `docs/superpowers/specs/2026-07-26-amd-hackathon-character-workshop-design.md`
- Implementation plan: repo `docs/superpowers/plans/2026-07-26-character-workshop-implementation.md`
