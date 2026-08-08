# Screen-AI Memory File

This file provides **fast context loading** for AI agents working on Screen-AI. Read this first before exploring the codebase.

## Quick Facts

- **Project**: Screen-AI (Local AI PC Operator)
- **Track**: Hackathon Track 2 - Agentic AI
- **Platform**: Windows (primary), cross-platform future
- **Hardware Target**: 4GB RAM laptops (low-resource)
- **GPU**: AMD ROCm (cloud), RTX (local dev)
- **Language**: Python (backend), JavaScript (frontend)
- **Database**: SQLite
- **Server**: FastAPI
- **Browser**: Playwright
- **UI Automation**: Windows UIA + OpenCV + OCR

## Core Architecture (30-Second Summary)

```
Mobile Remote (phone)
    ↓ text commands / approvals
Local PC Agent Server (FastAPI)
    ↓
Agent Brain (LLM planner)
    ↓
Risk + Permission Engine
    ↓
Tool Executor
    ↓
File/Browser/App/System/Vault/Passkey/Download/Screen tools
```

## Current Model Routing

Updated: 2026-07-25 17:55:31 +05:30

- `app/runtime/model_insights.py` is the metadata-only model route brain.
- `/runtime` exposes `model_insights`.
- `/command/preview` and command execution return `model_plan`.
- Phone `worker.js` gives instant `MODEL_ROUTE_HINT` and `MEMORY_SCORE_COMMAND`.
- Phone `app.js` renders model lanes before and after backend preview.

Model roles:

| Model | Use |
|-------|-----|
| Qwen2.5 Coder 1.5B Q4 | complex/unknown command planning; SSD mmap, no low-RAM prefetch |
| OCR det v3 | text region detection; ONNX, fast perception |
| OCR rec English | text recognition; ONNX, fast perception |
| OmniParser v2 icon detect | teacher/high-confidence fallback; not default 4GB resident |

## Key Principles

1. **Local-first**: Everything runs on user's PC
2. **Phone approval**: Critical actions need phone confirmation
3. **Quarantine first**: Deletes go to quarantine, not permanent
4. **Log redaction**: Passwords never appear in logs
5. **Tiered models**: Small models for simple tasks, big for complex
6. **Lazy loading**: Heavy models loaded only when needed

## Current Status

Updated: 2026-08-05

### ✅ Working

- FastAPI backend with `/runtime`, `/command`, `/command/preview`
- Mobile web remote with pairing, command send, preview, history, approvals
- Inline command-screen approval buttons for pending risky actions
- Execution graph preview for observe/act/verify/finish pipelines
- Plan-to-action controls from preview:
  - low risk: `Send this plan`
  - approval gated: `Approve and send`
  - lab low risk: `Run Low-Risk Plan`
- Browser Model Lab at `/remote/lab.html`
- Shared frontend API client (`api.js`) and UI helpers (`ui.js`)
- Pytest-safe backend test suite using isolated DB paths where needed
- Screen scanning (UIA + OpenCV)
- Click-by-text execution with semantic OCR matching (login ↔ sign in)
- Screenshot capture
- JSON UI maps
- Debug overlay images
- **Cognitive planner**: `browser_open` first-class intent, single-pass alias resolution, `take me to`/`browse` navigation vocabulary
- **External reasoning**: `external_planner.py` (DeepSeek-V4-Flash via AMD Radeon API, env-var key only), wired into unknown-intent path
- **Camera**: `take_camera_photo` intent + `system.capture_photo` (ffmpeg dshow, graceful failure)
- **Chat mode**: local rules + external model, `status: "chat"` response
- **Execution graph metadata**: per-node `pipeline` + `models` + `verify_goal` node (Phase 3/4/10)
- **Status messages**: `statuses` list ("Opening Chrome...") + `goal` in responses
- **Generic task decomposition**: `extract_entities()` (FILE/CONTACT/CHANNEL), entity-driven `send_file` plan
- **Compound command planner**: `_plan_multi_intent_sequence` splits chained commands into one `compound_sequence` execution graph

### 🚧 In Progress

- Live WhatsApp/DOM attach automation (graph plans honestly; partial-progress reporting)
- Better verification after tool execution
- Real model artifact loading and low-RAM scheduling refinements

### 📋 Planned

- Passkey flow
- Deeper browser research collection
- More local LLM planner coverage
- AMD ROCm demo packaging

## File Structure (Critical Files)

```
Screen-AI/
├── AGENTS.md              # Agent guide (read first)
├── FUTUREPLANS.md         # Roadmap and future plans
├── MEMORY.md              # This file (fast context)
├── README.md              # Project overview
│
├── screen_element_scanner/
│   ├── scan_screen.py     # Main scanner (UIA + OpenCV)
│   └── uia_scan.ps1       # PowerShell UIA scanner
│
├── hackathon_ui_operator_distill/
│   ├── cloud/             # AMD ROCm training pipeline
│   ├── data/              # Datasets
│   ├── docs/              # Documentation
│   ├── local_runtime/     # Local execution
│   └── native/            # C/C++ native code
│
└── ai_pc_operator/        # NEW - Main product (to be built)
    ├── backend/
    │   └── app/
    │       ├── main.py
    │       ├── agent/
    │       ├── security/
    │       ├── tools/
    │       ├── approvals/
    │       ├── db/
    │       └── logs/
    └── frontend/
        └── src/
```

## Key Commands

### Screen Scanning

```powershell
# Scan current screen
python .\screen_element_scanner\scan_screen.py

# Click by text (dry-run)
python .\hackathon_ui_operator_distill\local_runtime\click_by_text.py "Share" --dry-run

# Collect screenshots for training
python .\hackathon_ui_operator_distill\local_runtime\collect_screenshot.py
```

### Cloud GPU (AMD ROCm)

```bash
# Setup cloud environment
bash cloud/setup_cloud_gpu.sh

# Download OmniParser v2
bash cloud/download_omniparser_v2.sh

# Train YOLO student model
python cloud/train_student_yolo.py --data data/yolo_dataset/ui_dataset.yaml --model yolov8n.pt --epochs 80 --device 0

# Export to INT8 ONNX
python cloud/export_int8_onnx.py --weights runs/ui_student/weights/best.pt --out ui_detector_int8.onnx
```

## Model Stack (4GB RAM)

| Component | Model | RAM | When |
|-----------|-------|-----|------|
| UI Detection | UIA + OpenCV | ~150 MB | Always |
| OCR | PaddleOCR Mobile | ~50 MB | Fallback |
| UI Detector | YOLOv8n INT8 ONNX | ~300 MB | Fallback |
| Action LLM | Qwen2.5-1.5B Q4 | ~1.2 GB | Always |
| Vision LLM | Florence-2-base Q4 | ~1.5 GB | Optional |
| **Total** | | **~3 GB** | |

## Access Levels

| Level | Action | Approval |
|-------|--------|----------|
| 0 | Read status, search | None |
| 1 | Open app/site | None |
| 2 | Download, rename | Maybe |
| 3 | Email, login, install | Phone |
| 4 | Delete, bulk ops | Phone required |
| 5 | Permanent delete, export | Special mode |

## Database Tables

- `commands` - All user commands
- `approvals` - Pending/resolved approvals
- `actions` - Executed tool actions
- `devices` - Paired phones
- `vault_entries` - Encrypted credentials
- `quarantine` - Quarantined files
- `sessions` - Active sessions
- `settings` - User preferences

## Tool List

### File Tools
- `file.list`, `file.scan`, `file.read`
- `file.move`, `file.copy`
- `file.quarantine`, `file.restore`
- `file.delete_permanent`

### System Tools
- `system.status`, `system.disk_usage`
- `system.ram_usage`, `system.processes`
- `system.open_app`, `system.kill_process`
- `system.network_status`, `system.run_command`

### Browser Tools
- `browser.open`, `browser.search`
- `browser.click`, `browser.type`
- `browser.read`, `browser.download`

### Auth Tools
- `auth.password_login`
- `auth.passkey_login`
- `auth.vault_unlock`

### Approval Tools
- `approval.request`
- `approval.resolve`

## Protected Folders

- `C:\Windows`
- `C:\Program Files`
- `C:\Program Files (x86)`
- `AppData`
- Browser credential stores
- SSH keys
- `.env` files
- Wallet files

## Dangerous Extensions

- `.exe`, `.msi`, `.bat`, `.cmd`
- `.ps1`, `.vbs`, `.scr`
- `.jar`, `.js`

## Temperature Settings

| Task | Temperature |
|------|-------------|
| Tool selection | 0.0 |
| Risk classification | 0.0 |
| File operations | 0.0 |
| Login flow | 0.0-0.2 |
| Browser automation | 0.1-0.2 |
| Summarization | 0.2-0.4 |
| Writing messages | 0.4-0.7 |

## Non-Negotiable Rules

1. Critical actions require phone approval
2. Passwords are redacted from logs
3. Destructive actions use quarantine first
4. Emergency stop always works
5. All non-secret actions are logged
6. Login target domain shown before approval
7. Downloaded executables require approval
8. Full access sessions are time-limited
9. Model proposes; tool system executes
10. User can wipe logs, vault, memory, quarantine

## Common Patterns

### Command Flow

```python
# 1. Receive command
command = await receive_command()

# 2. Classify intent
intent = await classify_intent(command)

# 3. Assess risk
risk = await assess_risk(intent)

# 4. Check approval
if risk >= 3:
    approval = await request_phone_approval(intent)
    if not approval.approved:
        return "User rejected"

# 5. Execute tools
result = await execute_tools(intent)

# 6. Verify
verified = await verify_result(result)

# 7. Log
await log_action(command, intent, result)

# 8. Return
return format_response(result)
```

### Quarantine Pattern

```python
# Instead of permanent delete:
def quarantine_file(path):
    quarantine_id = generate_id()
    quarantine_path = f"data/quarantine/{quarantine_id}"
    shutil.move(path, quarantine_path)
    db.insert("quarantine", {
        "id": quarantine_id,
        "original_path": path,
        "quarantine_path": quarantine_path,
        "created_at": now()
    })
    return quarantine_id

def restore_file(quarantine_id):
    record = db.get("quarantine", quarantine_id)
    shutil.move(record.quarantine_path, record.original_path)
    db.update("quarantine", quarantine_id, {"restored_at": now()})
```

### Password Vault Pattern

```python
# Encrypt with AES-256-GCM
def encrypt_password(password, master_key):
    salt = os.urandom(16)
    key = argon2id(master_key, salt)
    nonce = os.urandom(12)
    ciphertext, tag = aes_gcm_encrypt(key, nonce, password)
    return {
        "salt": salt,
        "nonce": nonce,
        "ciphertext": ciphertext,
        "tag": tag
    }

# Decrypt
def decrypt_password(encrypted, master_key):
    key = argon2id(master_key, encrypted.salt)
    return aes_gcm_decrypt(key, encrypted.nonce, encrypted.ciphertext, encrypted.tag)
```

## Troubleshooting

### Common Issues

1. **UIA returns nothing**: App doesn't expose UI Automation
   - Solution: Fall back to OCR + OpenCV

2. **Click misses target**: Coordinates are off
   - Solution: Add verification screenshot after click

3. **Password not working**: Vault not unlocked
   - Solution: Request phone unlock first

4. **Approval timeout**: User didn't respond
   - Solution: Default to reject after 60s

5. **Model too slow**: LLM taking too long
   - Solution: Use smaller model or rule-based fallback

### Performance Tips

- Cache frequent commands
- Summarize old conversations
- Use SQLite for fast lookups
- Lazy-load heavy models
- Stream responses
- Avoid background indexing

## References

- [AGENTS.md](AGENTS.md) - Full agent guide
- [FUTUREPLANS.md](FUTUREPLANS.md) - Roadmap
- [README.md](README.md) - Project overview
- [hackathon_ui_operator_distill/docs/](hackathon_ui_operator_distill/docs/) - Technical docs

## Quick Start for New Agents

1. Read this file (MEMORY.md) - 2 minutes
2. Read AGENTS.md - 10 minutes
3. Read FUTUREPLANS.md - 5 minutes
4. Explore screen_element_scanner/ - 10 minutes
5. Check current issues/todos - 5 minutes
6. Start working on assigned task

**Total onboarding**: ~30 minutes

---

## Latest Run Memory: 2026-07-23 17:03:33 +05:30

Focus: low-memory tuning after review notes about DB connection churn, vault Argon2 spikes, Playwright idle memory, recursive scan cost, regex hot loops, missing DB indexes, screen cache wiring, and dependency bloat.

Changed:

- Added shared SQLite connection lifecycle in `ai_pc_operator/backend/app/db/database.py`.
- Added `db_session()` and migrated router, approvals, pairing, file tools, vault, and history reads to it.
- Added indexes for `approvals.command_id` and `quarantine.command_id`.
- Changed history endpoint to specific columns plus result truncation and limit clamp.
- Added router shutdown and browser close on FastAPI lifespan shutdown.
- Added browser idle unload after 300 seconds.
- Bounded file scan traversal to 5000 files, depth 3, and 10 seconds.
- Precompiled planner/risk/redactor regexes.
- Added vault per-session entry-key cache and lazy cryptography imports.
- Added configurable vault KDF profile for faster tests while keeping production defaults strong.
- Fixed vault `last_used` update and made credential upserts idempotent.
- Added scanner identical-screen cache with `--cache-ttl`.
- Trimmed backend requirements and updated Playwright pin.
- Fixed async smoke tests and ASCII console output.

Verification:

```text
py_compile: pass
backend test_basic.py: pass
screen scanner --quiet: pass
```

Operational note:

If smoke tests time out while using the shared DB, check for stale Python processes holding SQLite locks and stop them before rerunning.

## Latest Run Memory: 2026-07-23 23:41:06 +05:30

Focus: start the real model/tool runtime pipeline.

Implemented:

- Added backend runtime package:
  - `app/runtime/resource_budget.py`
  - `app/runtime/io_pool.py`
  - `app/runtime/model_registry.py`
  - `app/runtime/heatmap.py`
  - `app/runtime/tier_manager.py`
- `AgentRouter` now wires TierManager into real command processing.
- RAM budget is measured at command start.
- Intent classification overlaps with memory measurement.
- Risk assessment overlaps with tier decision and async prefetch.
- Tool heat map records tools used by each intent.
- Hot models/tools can be prefetched without blocking the event loop.
- Sync tools execute through the shared I/O thread pool.
- Browser and auth tools gained safe `prepare()` methods.
- Added `/runtime` endpoint for RAM/model status.

Current model registry uses placeholders:

```text
ocr-mobile
ui-detector-int8
qwen-1.5b-q4
vault-crypto
browser-warmup
```

Next work:

- Replace placeholders with real PaddleOCR/ONNX/GGUF lazy loaders.
- Add model download script and local model manifest.
- Add click-by-text endpoint into `ai_pc_operator`.
- Add runtime tests around `AgentRouter.process_command()`.

**Last Updated**: 2026-07-23 23:41:06 +05:30
**Version**: 1.2.0
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-24 00:09:12 +05:30

Focus: fix browser/search commands that returned `completed` with `No actions taken`.

Changed:

- Broadened planner intent matching for natural browser commands.
- Added support for:
  - `search ... in chrome`
  - `open YouTube`
  - `open github.com`
  - `close browser`
- Added common site aliases in the planner.
- Cleaned browser hints out of search queries.
- URL-encoded search queries before navigation.
- Added system-browser fallback when Playwright Chromium is unavailable.
- Changed no-step plans to return `unsupported` instead of fake success.
- Added PBKDF2-HMAC-SHA256 fallback when the Windows `cryptography` Argon2 binding is broken.
- Added smoke assertions for search and browser-close planning.
- Installed Playwright Chromium locally for structured browser automation.

Current behavior:

- Browser search/open should now execute through Playwright when available.
- If Playwright browser binaries are missing, the command opens through the Windows default browser.
- Click/type/read still require Playwright to be installed and working.
- Verified `/command` with `search best gaming mouse in chrome` and `close browser`.

Next work:

- Add Playwright install/check endpoint.
- Add screen click-by-text tools into `ai_pc_operator`.
- Replace runtime placeholder models with real OCR/ONNX/GGUF loaders.

**Last Updated**: 2026-07-24 00:09:12 +05:30
**Version**: 1.2.1
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-24 00:19:07 +05:30

Focus: replace model placeholders with real loader/discovery wiring and connect unused architecture pieces.

Changed:

- Added model artifact discovery:
  - `app/runtime/artifact_store.py`
  - searches `ai_pc_operator/data/models`, hackathon distill outputs, and `SCREEN_AI_MODEL_DIR`
- Added optional real loaders:
  - PaddleOCR for `ocr-mobile`
  - ONNX Runtime for `ui-detector-int8`
  - llama.cpp GGUF for `qwen-1.5b-q4`
  - cryptography warmup for `vault-crypto`
  - Playwright warmup for `browser-warmup`
- Removed `placeholder_loader` from the runtime registry.
- Added `app/agent/llm_planner.py`.
- `LLMPlanner` now imports and uses `SYSTEM_PROMPT` and `USER_PROMPT_TEMPLATE`.
- `AgentRouter` can attempt LLM planning only for unknown intents when RAM allows and a real Qwen GGUF model is loaded.
- Added backend `ScreenCache`:

```text
ai_pc_operator/data/.screen_ai_cache/
  ui_maps/
  ocr_results/
  detector_results/
```

- `AgentRouter` writes redacted plan metadata into the cache.
- `/runtime` now reports:
  - memory budget
  - model registry status
  - artifact inventory
  - screen cache stats
- `LogRedactor` is now used:
  - as a global logging filter
  - when saving commands
  - when saving action input/output JSON
  - when saving memory entries
- Nested list/dict redaction now works.
- Added artifact CLI:

```powershell
python .\ai_pc_operator\backend\scripts\model_artifacts.py inventory
python .\ai_pc_operator\backend\scripts\model_artifacts.py stage-yolo <ui_detector_int8.onnx>
python .\ai_pc_operator\backend\scripts\model_artifacts.py stage-gguf <qwen.gguf>
```

Verification:

```text
py_compile: pass
backend test_basic.py: pass
model_artifacts.py inventory: pass
/runtime: pass
/command search best air coolers in chrome: pass
/command close browser: pass
```

Current artifact inventory:

```text
ocr-mobile: missing
ui-detector-int8: missing
qwen-1.5b-q4: missing
vault-crypto: no artifact required
browser-warmup: no artifact required
```

**Last Updated**: 2026-07-24 00:19:07 +05:30
**Version**: 1.3.0
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-24 01:50:32 +05:30

Focus: repair the enhanced mobile/PC login flow and stop the stuck test process.

Problems found:

- A stale `python -u ai_pc_operator/backend/test_login_v2.py` process was still running.
- `test_login_v2.py` did not close the shared SQLite connection.
- FastAPI lifespan did not declare `pairing_manager_v2` as global, so V2 endpoints could stay unavailable.
- `/remote/index.html` still used the old `pairing-screen` DOM while `app.js` expected `login-screen`.
- Frontend QR flow depended on browser X25519 WebCrypto support.
- Trusted reconnect returned a token but frontend did not save it.
- QR completion had a bad DB fallback path when the in-memory private key was gone.

Changed:

- Stopped the stale Python process.
- Added DB shutdown to `test_login_v2.py`.
- Fixed FastAPI V2 manager initialization.
- Aligned `index.html` with the enhanced login UI.
- Kept the 6-digit code flow as reliable fallback.
- Made QR scanner fail gracefully when camera/jsQR is unavailable.
- Removed frontend dependency on X25519 for MVP pairing.
- QR pairing and trusted reconnect now return/store usable local session tokens.
- Token rotation records an audit row.

Verification:

```text
py_compile: pass
node --check frontend/app.js: pass
test_login_v2.py: pass
test_basic.py: pass
/pair/qr: pass
/pair/code: pass
/remote/index.html: pass
/pair/qr/complete: pass
/auth/rotate: pass
/pair/trusted: pass
```

Current server:

```text
localhost:8000
PID seen during verification: 22372
```

**Last Updated**: 2026-07-24 01:50:32 +05:30
**Version**: 1.3.1
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-24 02:10:11 +05:30

Focus: install real model artifacts into the project model directory.

Model directory:

```text
ai_pc_operator/data/models/
```

Added downloader:

```powershell
python .\ai_pc_operator\backend\scripts\download_models.py
```

Artifacts selected for low-resource hackathon runtime:

- Qwen2.5 Coder 1.5B GGUF Q4_0 for local LLM planning.
- PaddleOCR ONNX detection and English recognition files for OCR artifacts.
- OmniParser V2 icon detector `.pt` as a teacher/cloud distillation artifact.

Notes:

- Active 4 GB laptop runtime should use GGUF + ONNX artifacts.
- OmniParser teacher weights are for cloud distillation/export, not normal laptop startup.
- The final `ui_detector_int8.onnx` still needs to be produced by the cloud AMD/ROCm pipeline and staged into `ai_pc_operator/data/models/`.

**Last Updated**: 2026-07-24 02:10:11 +05:30
**Version**: 1.3.2
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-24 02:25:43 +05:30

Focus: solve the unresolved codebase-analysis gaps that were practical blockers.

Solved:

- Backend screen scan/click is now wired through `screen.scan` and `screen.click_text`.
- Planner routes `scan screen buttons` and `click Share` into backend tools.
- System shell injection risks were removed from app opening and raw command execution.
- Pairing verification now checks token hashes.
- Authenticated endpoints now support/require paired-device token verification where mobile calls need it.
- Frontend history/approval rendering no longer injects server strings as HTML.
- Frontend history, approval resolve, emergency stop, and WebSocket now send authenticated device context.
- Cloud teacher labeling now runs OmniParser V2 icon detector through Ultralytics instead of only printing placeholder instructions.
- YOLO converter writes `ui_dataset.yaml`; ONNX export stages `ui_detector_int8.onnx`.
- UIA scanner is more tolerant of unavailable desktop elements.
- Browser idle timeout reduced to 120 seconds.
- Long-term memory file I/O moved off the event loop.

Verified:

```text
test_basic.py: pass
test_login_v2.py: pass
node --check app.js: pass
ScreenTools.scan: pass, 226 actionable controls
ScreenTools.click_text("Close", dry_run=True): pass
```

Remaining:

- Build mobile vault unlock UI.
- Build passkey approval UI.
- Build Full Access Session UI.
- Run the AMD/ROCm cloud workflow to produce real `ui_detector_int8.onnx`.

**Last Updated**: 2026-07-24 02:25:43 +05:30
**Version**: 1.3.3
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-24 02:33:30 +05:30

Focus: implement the codiii-inspired SSD tiering strategy for 4 GB no-GPU laptops.

Added:

- `SSDTierManager` for resident/warm/SSD-cold/SSD-off placement.
- `SCREEN_AI_RAM_MB` low-memory override.
- `SCREEN_AI_MMAP`, `SCREEN_AI_PREFETCH`, `SCREEN_AI_ALLOW_COLD_LLM`, `SCREEN_AI_LLM_CTX`, and `SCREEN_AI_LLM_THREADS` runtime knobs.
- llama.cpp Qwen loader now defaults to mmap, low context, low batch, and two CPU threads.
- Model usage heat persists in `ai_pc_operator/data/memory/model_usage.json`.
- Large models are never prefetched.
- `/runtime` exposes SSD plan and usage.
- Native C LFRU/hysteresis tier policy scaffold in `hackathon_ui_operator_distill/native/`.

4 GB policy:

- Keep the rule planner, mobile remote, UIA scanner, and OpenCV resident/light.
- Keep Qwen on SSD/off by default.
- Load OCR/detector only when memory budget permits.
- Run OmniParser/training/export on cloud AMD/ROCm, then stage tiny INT8 ONNX locally.

**Last Updated**: 2026-07-24 02:33:30 +05:30
**Version**: 1.3.4
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-24 19:03:38 +05:30

Focus: improve the command brain so compound user commands become real task plans.

Added:

- `TaskPlanner` for high-level task decomposition before single-intent planning.
- `browser.research_collect` for search -> visit multiple pages -> extract text -> save report.
- HTTP Bing fallback and redirect decoding when browser search result DOM is empty.
- `system.open_settings`.
- `system.keep_awake` using Windows `SetThreadExecutionState`.
- Native C endpoint ranking scaffold.
- Screen click scoring now accounts for text score, confidence, bounds, and UIA source priority.

Validated:

- Compound research command plans to `browser.research_collect`.
- `browser.research_collect("AMD ROCm", max_sites=1)` visited AMD ROCm page and saved a report.
- `endpoint_rank.c` compiled.
- Backend smoke tests passed.

Remaining intelligence gap:

- We still need a full execution loop with step repair/retry and observation-based replanning.
- We still need mobile UI for complex task progress/cancel.

**Last Updated**: 2026-07-24 19:03:38 +05:30
**Version**: 1.3.5
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-24 19:24:26 +05:30

Focus: make the paired mobile remote feel alive, connected, and recoverable.

Added:

- Visible connection badge on the mobile command header.
- WebSocket state wiring for connected, reconnecting, offline, and socket-error states.
- Pairing success transition before entering the command console.
- Command progress timeline for receive, plan/risk/model-budget, approval, execution, and failure states.
- `ai_pc_operator/stop.bat` for stopping local HTTP/HTTPS servers on ports `8000` and `8443`.
- Cleaner `login.html` redirect fallback that uses the app stylesheet and points to `index.html`.

Validated:

- `node --check ai_pc_operator/frontend/app.js`: pass.
- `cmdc` was queried with `cmdc -p ... --max-turns 8` and its useful non-stealth recommendations were implemented.

Remaining:

- Add backend-originated streamed progress events for long browser/research jobs.
- Add a richer cancel/resume UI for multi-step tasks.
- Keep all automation visible, approved, and auditable.

**Last Updated**: 2026-07-24 19:24:26 +05:30
**Version**: 1.3.6
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-24 21:28:08 +05:30

Focus: verify the new relation map and make phone text instructions easier for the agent to understand before execution.

Added:

- `AgentRouter.preview_plan()` and `POST /command/preview`.
- Mobile plan preview with intent, risk, approval requirement, runtime info, and redacted tool steps.
- Lightweight JS command memory using `localStorage`.
- Command draft restore using `localStorage`.
- IndexedDB offline draft storage.
- PWA service worker and web worker files.
- Native C core bridge, build scripts, and strategy/telemetry runtime modules.

Corrected:

- Relation maps now reference `process_command()` and `preview_plan()` instead of stale `route_command()`.
- Offline commands are drafts only; they do not auto-run when network returns.
- Native C core includes `stdlib.h` and handles allocation failure.
- `build.bat` was cleaned up and produces the native DLL/import files.

Validated:

- `python -u ai_pc_operator/backend/test_basic.py`: pass.
- `python -m pytest ai_pc_operator/backend/test_strategy.py -q`: 47 passed.
- `node --check ai_pc_operator/frontend/app.js`: pass.
- `node --check ai_pc_operator/frontend/sw.js`: pass.
- `node --check ai_pc_operator/frontend/worker.js`: pass.
- `python -m py_compile` for router, main, strategy, telemetry, and native bridge: pass.
- `cmd /d /c ai_pc_operator/backend/build.bat`: produced Windows native artifacts; command exits `0`.
- `bash ai_pc_operator/backend/build.sh`: script is valid, but this Windows bash environment does not expose gcc/clang.
- `relation-map.md` and `ai_pc_operator/relation-map.md`: identical.

Note:

- The Windows shell still prints a stray environment message after `build.bat`, but the build command exits `0` and artifacts are produced.

**Last Updated**: 2026-07-24 21:28:08 +05:30
**Version**: 1.3.7
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-30 21:01:51 +05:30

Focus: make the latest run-memory/Phase 17 changes durable and testable instead of relying on a temporary audit file.

Added:

- `pipeline/test_agent_runtime.js` permanent runtime regression test.
- Checks for `IntentEngine`, `AgentRuntime`, `globalAgentRuntime`, string/object intent input, low-risk execution, high-risk approval insertion, and runtime memory/history.

Corrected:

- `pipeline/screenai_pipelines.js` now auto-detects the real app layout at `ai_pc_operator/` and routes `BACKEND`, `FRONTEND`, `DATA`, and `DOCS` there.
- `build-frontend` now builds from `ai_pc_operator/frontend` and reports `13 files copied, 0 errors`.
- `.gitignore` now excludes generated frontend build output at `ai_pc_operator/frontend/dist/` and legacy `frontend/dist/`.
- `AGENTS.md` no longer references deleted `_test_tmp/phase17_audit.js`; it references `pipeline/test_agent_runtime.js`.

Validated:

- `node --check pipeline/screenai_pipelines.js`: pass.
- `node --check pipeline/engine.js`: pass.
- `node --check pipeline/operations.js`: pass.
- `node --check pipeline/cli.js`: pass.
- `node pipeline/test_pipeline.js`: 43/43 passed.
- `node pipeline/test_agent_runtime.js`: pass.
- `node --check ai_pc_operator/frontend/api.js`: pass.
- `node --check ai_pc_operator/frontend/app.js`: pass.
- `node --check ai_pc_operator/frontend/ui.js`: pass.
- `node --check ai_pc_operator/frontend/sw.js`: pass.
- `python -m pytest ai_pc_operator/backend -q`: 62 passed with isolated temp DB.

Remaining:

- Commit/push is still separate from this hardening pass unless explicitly requested.
- The backend Flasgger warning is expected when optional Swagger dependencies are absent.

**Last Updated**: 2026-07-30 21:01:51 +05:30
**Version**: 1.3.8
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-30 21:07:08 +05:30

Focus: move beyond "tests pass" and verify real command execution paths.

Fixed:

- `ai_pc_operator/backend/app/main.py` `RedactingFilter` now redacts string log fields only and preserves non-string logging arguments.
- This prevents logging formatter crashes when libraries log numeric args, for example HTTP status codes with `%d`.

Runtime verified with a fresh isolated FastAPI app:

- `POST /command` with `show system status`: 200 OK, executed `system.status`.
- `POST /command/preview` with `open gx browser`: 200 OK, planned `system.open_app`.
- `POST /command/preview` with `open chrome and search screen ai hackathon`: 200 OK, planned browser launch with search URL.

Operational note:

- A live server already running on port `8000` may still have old code loaded. Restart with `ai_pc_operator/stop.bat` and `ai_pc_operator/start.bat` before judging the browser UI.
- Direct PID restart/background launch was blocked by the current Codex execution policy, so the verification used the real app code in-process with a temp DB.

**Last Updated**: 2026-07-30 21:07:08 +05:30
**Version**: 1.3.9
**Maintainer**: Screen-AI Team

## Latest Run Memory: 2026-07-30 21:15:07 +05:30

Focus: make the large `pipeline/screenai_pipelines.js` file runnable as an agent-planning runtime.

Added:

- `node pipeline/cli.js agent <text...>` command.
- Native C++ op coverage for event helpers `70-73` and memory helpers `80-83`.

Fixed:

- `ExecutionGraphRunner` inserts approval nodes before validating high-risk graphs.
- Graph CLI validates the executable post-approval graph shape.
- Phase 17 runtime history now uses `executions` internally and exposes `history()`.
- Phase 17 verification reads nested execution status correctly.
- AgentRuntime native helpers now call runtime ops `130-133`.
- Native C++ `VerifyResult` duplicate definition and duplicate verifier export issues are resolved.
- Windows native build links `iphlpapi` and `psapi`.

Runtime verified:

- `node pipeline/cli.js agent open chrome --dry-run --auto-approve`: completed.
- `node pipeline/cli.js agent delete file C:\Temp\danger.txt --dry-run --auto-approve`: approval inserted, completed.
- `node pipeline/cli.js agent run whoami --dry-run --auto-approve`: risk 4 approval inserted, completed.
- Direct high-risk `ExecutionGraphRunner` run: approval node inserted, completed.

Native verified:

- `g++` compiled `hackathon_ui_operator_distill/native/screenai_core.cpp` plus `verifier_bridge.cpp`.
- Output artifact: `ai_pc_operator/data/native/screenai_core_native.dll`.
- `node pipeline/cli.js run build-native`: 2 command(s), 0 errors.

Important:

- The native DLL is a plain ABI artifact. JS still uses fallbacks because no Node N-API binding exists yet.
- Add a Node binding that exposes `call(op, input)` before expecting `NativeBridge.isAvailable()` to become true.

**Last Updated**: 2026-07-30 21:15:07 +05:30
**Version**: 1.4.0
**Maintainer**: Screen-AI Team
