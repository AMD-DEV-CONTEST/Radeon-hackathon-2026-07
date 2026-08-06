# Demo Video - Operation Flow & Script

Qingxi Rift Character Workshop - AMD AI DevMaster Hackathon Track 1
Language: English (submission requirement). Recommended length: 3:30-5:00.

---

## 0. Environment & recording setup

| Item | Preparation |
|------|-------------|
| Machine | Radeon Cloud instance (Navi31 / RX 7900 XTX, 24GB), ROCm torch OK |
| Code | `git pull` on `feature/character-workshop`, latest commit |
| Models | `bash scripts/download_models.sh` (Qwen2.5-7B + SDXL anime) |
| App deps | `bash scripts/install_app_deps.sh` passed |
| Recorder | OBS / screen recorder; capture 1920x1080 full screen |
| Audio | Optional narration, or subtitles only |
| Fonts | Not needed (all-English cards) |

Warm up before recording:

```bash
cd /persistent/qingxi-character-workshop/character-workshop
export MOCK=0
python3 - <<'PY'
from src.orchestrator import generate_card_job
r = generate_card_job("A Void traveler carrying a paper lantern", affinity_pref="Void", mock=False)
print("warmup", r.state)
PY
```

This loads 7B + SDXL so the recording run is fast and stable.

---

## 1. Recording order (timeboxed)

| # | Section | Duration | What is shown |
|---|---------|----------|---------------|
| 1 | Title card | 0:00-0:10 | App name, tagline, "Powered by AMD Radeon + ROCm" |
| 2 | Hardware proof | 0:10-0:35 | `rocm-smi`, device detect, torch HIP |
| 3 | App launch | 0:35-0:55 | `python3 app.py`, open browser, workbench UI |
| 4 | Case 1 - full card | 0:55-2:20 | Generate card from prompt (see pool) |
| 5 | Case 2 - revise | 2:20-3:00 | One-line revision, re-render |
| 6 | Case 3 - reference img | 3:00-3:40 | Upload sketch -> card influenced by it |
| 7 | Case 4 - diversity | 3:40-4:30 | 3 short prompts across affinities, quick montage |
| 8 | Wrap up | 4:30-5:00 | Architecture one-liner, thanks |

---

## 2. Section-by-section script

### Section 2 - Hardware proof (0:10-0:35)

Terminal:

```bash
rocm-smi
python3 - <<'PY'
import torch
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
print("hip", getattr(torch.version, "hip", None))
print("gpu", torch.cuda.get_device_name(0))
PY
```

Narration (or subtitle): "All inference runs locally on an AMD Radeon GPU through the ROCm software stack."

### Section 3 - App launch (0:35-0:55)

```bash
export MOCK=0
export PORT=7860
python3 app.py
```

Open browser to the proxy/tunnel URL. Point out: left panel inputs, right panel results, device badge shows ROCm.

### Section 4 - Case 1: full character card (0:55-2:20)

Paste prompt, affinity = Void, click **Generate Character Card**.
Show progress steps (Planning -> Painting -> Composing), then the card.
Download and open card.png. Mention: original lore JSON + anime portrait + affinity radar + spirit domain.

### Section 5 - Case 2: revise (2:20-3:00)

With the card still up, type a revision, click **Apply Revision**.
Show the appearance/prompt changed, card re-rendered.

### Section 6 - Case 3: reference image (3:00-3:40)

Upload a simple sketch (or selfie), describe the character, generate.
Point out the output follows the reference pose/hair while staying original anime style.

### Section 7 - Case 4: diversity montage (3:40-4:30)

Run 3 short prompts (from pool below), cut between results quickly.
Emphasize: different affinities -> different visual keywords, radar shapes, lore.

### Section 8 - Wrap up (4:30-5:00)

One-line: "Text plus optional image becomes an original character card - fully local on AMD Radeon."

---

## 3. Prompt pool (pick per demo)

Primary demo prompt (Case 1):

```
A quiet Void traveler in teal robes carrying a paper lantern
```

Revisions (Case 2):

```
change to short golden hair
make the robe dark blue with silver trim
give them a soft smile
```

Reference-image briefs (Case 3):

```
A Form street performer whose jacket reshapes like clay
A Mind counselor who draws soothing runes with her fingertips
```

Diversity montage (Case 4) - one per affinity:

```
A white-haired Life healer who keeps a pot of living moss
A silver-haired Mind rune master with pale blue eyes
A Matter heavy-armor fighter with a mineral crystal shield
A Form street performer whose jacket reshapes like clay
A Time clock keeper with a stopped pocket watch
A Void drone pilot who folds signal dead zones into shortcuts
```

Everyday/slice-of-life (optional extra):

```
A night-market candy-sugar artist who sometimes lets sugar strands float for three seconds
A primary-school music teacher who steadies a restless class by humming
A retired firefighter with a Matter shield and mineral-patterned burn scars
```

Notes:
- Always keep prompts original (no third-party IP names).
- Pick 4-6 total prompts; 3:30 demo -> 3 prompts, 5:00 demo -> 5-6.

---

## 4. Post-production checklist

- [ ] Intro title with app name + AMD Radeon + ROCm mention
- [ ] No third-party IP visible in inputs or outputs
- [ ] Captions/subtitles in English match narration
- [ ] Keep the browser URL (tunnel/proxy) out of frame if it exposes credentials
- [ ] Final export 3-5 min, 1080p, MP4

---

## 5. If something fails during recording

| Failure | Action on camera |
|---------|------------------|
| LLM JSON error | Show the error message + note "3-attempt retry" design, retry once |
| Image OOM | Lower resolution note; restart app |
| Network/API | Not used - all local, so nothing to show |

Have a pre-recorded fallback card output ready in `outputs/` in case a live run fails during the take.
