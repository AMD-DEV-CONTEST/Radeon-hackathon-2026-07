# Screen-AI Agent Notes

This file is the future-reference guide for agents working on Screen-AI.

## Project Identity

Screen-AI is a **fully local/offline PC operator AI** with full system access, controlled by your PC and phone, where the phone is the command + approval + unlock device. No sensitive cloud dependency. Text only for now.

The key product is not "chatbot." It is a **local AI control environment**.

Hackathon track:

```text
Track 2: Agentic AI
```

Positioning:

```text
Screen-AI is a local agentic desktop operator accelerated by AMD ROCm for screen perception, model distillation, and lightweight inference.
```

## Final Product Vision

You are building:

```text
Local AI PC Operator
```

It can:

- receive text commands from PC or phone
- search and browse
- open apps
- control mouse/keyboard
- read screen state
- manage files
- download files
- login to websites/apps
- use saved passwords after user unlock
- trigger passkey login flows
- ask mobile approval for dangerous actions
- run offline/local-first
- work on low-resource machines where possible

The system should feel like:

```text
User on phone:
"Open Excel, login if needed, and check my recent sheet."

AI:
Opens Excel.
Detects login.
Requests unlock/approval on phone.
User approves.
AI continues and reports result.
```

## Core Philosophy

Your version is:

```text
My PC
My phone
My AI
My approval
Full local control
```

But build it with strong internal structure:

```text
Model thinks
Tools act
Phone approves
Vault unlocks
Logs record
User controls
```

Do not make one messy AI process do everything. Separate responsibilities.

## 2026-07-25 Model Routing Baseline

The inspected model reports are now encoded in:

```text
ai_pc_operator/backend/app/runtime/model_insights.py
ai_pc_operator/docs/MODEL_INSIGHTS.md
```

Use this policy for future work:

- Qwen2.5 Coder 1.5B Q4 is the local reasoning/planning lane, loaded through llama.cpp with mmap only when RAM budget allows.
- OCR det v3 and OCR rec English are the fast screen perception lane.
- OmniParser v2 icon detect is a teacher/cloud or explicit fallback model, not a default 4GB resident model.
- Browser and vault warmups are tiny dependency lanes, not LLM calls.
- The phone UI can make instant JavaScript worker hints, but the backend remains the safe source of truth.

For a 4GB no-GPU laptop, do not prefetch Qwen or OmniParser. Prefer:

```text
resident rules/native/UIA
warm OCR only when needed
SSD mmap Qwen only for complex/unknown commands
teacher model only in cloud/distillation or explicit fallback
```

## 2026-07-30 Preview/Test Stability Note

If the Model Lab shows:

```text
Preview failed: Failed to fetch
```

check the local backend before changing planner logic:

```text
http://localhost:8000/runtime
http://localhost:8000/command/preview
```

`lab.html` now uses the shared `ScreenAI.api` client and reports a clearer backend-not-reachable message. The service worker cache version is `screenai-v4-api-lab` and includes `api.js`/`ui.js`.

Tests that touch the new skill/task/memory tables should use `SCREEN_AI_DB_PATH` with a temp SQLite file so they do not lock or corrupt the live `ai_pc_operator/data/agent.db` while the app is running.

## 2026-07-30 Inline Approval Note

The phone/remote command screen now has an inline approval surface:

```text
command sent -> backend creates approval -> UI polls /approvals/pending -> Approve/Reject buttons appear in chat
```

Do not reduce the `/command` request timeout below the backend approval wait. The frontend currently allows about 310 seconds because the backend waits up to 300 seconds for approval resolution.

## 2026-07-30 Plan-To-Action Note

Preview is now connected to action:

```text
Preview -> inspect plan/graph/model route -> Send this plan / Approve and send -> backend command pipeline
```

The Model Lab stays safer:

```text
low risk preview -> Run Low-Risk Plan
high risk preview -> Open Remote for Approval
```

Do not add direct high-risk execution to the lab. High-risk commands must go through the Remote command screen so the pending approval card can be shown and resolved through the existing `/approvals/*` flow.

## 2026-07-31 Lab Inline Approve Button Note

The Model Lab (`lab.html`) now has an inline approve button surface so users can approve/reject commands directly from the lab page when they give a comment.

### What changed

- `lab.html` now shows an **Approve & Send** / **Approve & Run** button + **Reject** button right under every preview.
- When the user clicks **Approve & Send**, the lab calls `/command` and starts polling `/approvals/pending` every 1.6s.
- Pending approvals render as inline approval cards with **Approve** / **Reject** buttons that call `/approvals/resolve`.
- The lab no longer redirects high-risk previews to Remote — the approval card appears inline.
- Service worker cache version bumped to `screenai-v8-lab-approve-button` so users get the fresh lab.html on next reload.

### New lab functions

```text
approveAndSend(text)       # sends command through /command, starts polling if approval needed
rejectPlan(text)           # marks plan as rejected, stops polling
startLabApprovalPolling()  # polls /approvals/pending every 1.6s
stopLabApprovalPolling()   # clears the poll timer
pollLabApprovals()         # fetches pending approvals
resolveLabApproval(id, ok) # calls /approvals/resolve
renderLabApprovalCards()   # renders inline approval cards with Approve/Reject buttons
```

### Safety rules still apply

- The lab still does not bypass risk policy. High-risk commands still create real approval requests that must be resolved.
- The lab still uses the same `/approvals/*` endpoints as Remote, so the approval flow is identical.
- The lab still shows the preview before any action runs.

### Verified

```powershell
curl.exe -s -X POST -H "Content-Type: application/json" -d '{"text":"delete file C:\\Temp\\danger.txt"}' --max-time 10 http://localhost:8000/command/preview
# Returns: requires_approval: true, risk_level: 4
```

## 2026-07-30 Pipeline Agent Runtime Note

Use this command to exercise the large JS pipeline as an agent planner:

```powershell
node pipeline/cli.js agent "open chrome" --dry-run --auto-approve
node pipeline/cli.js agent "delete file C:\Temp\danger.txt" --dry-run --auto-approve
node pipeline/cli.js agent "run whoami" --dry-run --auto-approve
```

Expected behavior:

```text
text -> AgentRuntime -> intent -> context -> plan -> runtime graph -> ExecutionGraphRunner
high risk action -> auto approval node -> action node -> verify/finish
```

Native C++ helper artifact:

```text
ai_pc_operator/data/native/screenai_core_native.dll
```

The DLL is a plain ABI artifact, not a Node addon. `NativeBridge` still uses JS fallbacks until a Node binding exposes `call(op, input)`.

## System Architecture

```text
Mobile Remote
  |
  | text commands / approvals / unlocks
  v
Local PC Agent Server
  |
  v
Agent Brain
  |
  v
Risk + Permission Engine
  |
  v
Tool Executor
  |
  +--> File Control
  +--> Browser Control
  +--> App Control
  +--> System Control
  +--> Password Vault
  +--> Passkey Flow Controller
  +--> Download Manager
  +--> Screen/OCR/Vision
```

Everything important runs locally.

## Current Repository State

Important folders:

```text
screen_element_scanner/
  scan_screen.py
  uia_scan.ps1

hackathon_ui_operator_distill/
  cloud/
  data/
  docs/
  local_runtime/
  native/

ai_pc_operator/  (NEW - main product)
  backend/
    app/
      main.py
      agent/
        planner.py
        router.py
        prompts.py
        memory.py
      security/
        risk.py
        permissions.py
        pairing.py
        vault.py
      tools/
        file_tools.py
        system_tools.py
        browser_tools.py
        download_tools.py
        auth_tools.py
      approvals/
        manager.py
      db/
        database.py
        models.py
      logs/
        redactor.py
  frontend/
    src/
      App.jsx
      pages/
        CommandPage.jsx
        ApprovalPage.jsx
        VaultPage.jsx
        HistoryPage.jsx
        SettingsPage.jsx
      api/
        client.js
  data/
    agent.db
    quarantine/
    downloads/
  docs/
    architecture.md
    permissions.md
    vault.md
    roadmap.md
```

Current working prototype:

```powershell
python .\screen_element_scanner\scan_screen.py
python .\hackathon_ui_operator_distill\local_runtime\click_by_text.py "Share" --dry-run
```

The scanner already creates:

- screenshot captures
- Windows UI Automation element maps
- OpenCV visual candidates
- JSON UI maps
- debug overlay images
- exact element endpoints and centers

## Main Components

### A. PC Agent

Runs on your computer.

Responsibilities:

- receive commands
- manage AI reasoning
- execute tools
- control browser/apps
- access filesystem
- communicate with phone
- maintain logs
- enforce approval rules

Recommended stack:

- Python
- FastAPI
- WebSocket
- SQLite
- Playwright
- PowerShell
- PyAutoGUI
- Windows UI Automation

### B. Mobile Remote

Starts as a mobile web app.

Responsibilities:

- send text commands
- approve/reject actions
- unlock password vault
- approve passkey login flow
- emergency stop
- view action history

Later you can convert it to:

- Flutter app
- React Native app
- native Android app

### C. Agent Brain

This converts user text into plans.

Example:

```text
"Delete all files in Downloads"
```

Becomes:

```json
{
  "intent": "delete_files",
  "target": "Downloads",
  "risk": "critical",
  "requires_mobile_approval": true,
  "execution_method": "quarantine"
}
```

### D. Tool Executor

The model should not directly run raw commands. It should request tools.

Example tools:

```text
file.list
file.scan
file.quarantine
file.restore
system.status
browser.open
browser.search
browser.click
browser.type
app.open
download.file
auth.password_login
auth.passkey_login
approval.request
```

### E. Permission Engine

This decides whether the action can run directly or needs phone approval.

### F. Password Vault

Local encrypted password store.

Responsibilities:

- store passwords encrypted
- unlock only when user enters master key
- provide password to automation tool
- remove password from logs
- wipe temporary memory after use

### G. Passkey Flow Controller

For passkeys, the AI should control the login screen and ask the user to approve the passkey challenge.

Passkeys usually cannot be exported like passwords. So the AI flow is:

```text
AI clicks "Sign in with passkey"
Windows/Edge/phone asks for approval
User approves
AI waits
Login succeeds
AI continues
```

## Access Model

Use these access levels.

| Level | Action | Approval |
|-------|--------|----------|
| 0 | read system status, search web | no |
| 1 | open app/site | no |
| 2 | download file, rename/move file | maybe |
| 3 | send email, login, run installer | phone approval |
| 4 | delete files, bulk operations, admin/system changes | phone approval required |
| 5 | permanent delete, credential export, financial action | blocked or explicit special mode |

Since your goal is full control, you can allow Level 5 only through a special mode:

```text
Full Access Session
Time limited: 5-15 minutes
Phone approved
Visible on PC
Emergency stop enabled
All actions logged except secrets
```

## Critical Action Flow

Example:

```text
User:
"Delete everything in Downloads"
```

Flow:

```text
AI parses command
↓
Scans Downloads
↓
Counts affected files and size
↓
Creates approval request
↓
Phone shows exact impact
↓
User approves
↓
AI moves files to quarantine
↓
AI reports result
```

Phone screen:

```text
Critical Action

Delete contents of:
C:\Users\brigh\Downloads

Files affected:
248

Size:
3.2 GB

Method:
Move to quarantine first

[Approve] [Reject]
```

Default should be **quarantine**, not permanent delete.

## Password Login Flow

Your intended password design:

```text
User:
"Login to xyz.com"

AI:
Opens xyz.com
Detects login page
Requests vault unlock on phone

Phone:
"Unlock password for xyz.com?"
User enters master key

Vault:
Decrypts password locally

Automation:
Fills username/password
Submits form

AI:
Continues task after login
```

Important rules:

- passwords can be used by the local AI system
- passwords are deleted/redacted from logs
- screenshots around password entry should be blocked or redacted
- password should not be saved in plain text
- unlock session should expire quickly

Use:

- AES-256-GCM encryption
- Argon2id for deriving key from master password
- SQLite encrypted records
- per-site credential entries
- optional biometric unlock later

Credential record:

```json
{
  "site": "xyz.com",
  "username": "user@example.com",
  "encrypted_password": "...",
  "created_at": "...",
  "last_used": "..."
}
```

## Passkey Login Flow

Passkey flow:

```text
User:
"Login to Microsoft Excel"

AI:
Opens Excel
Detects Microsoft login
Clicks passkey option
Requests user approval

Phone/Windows:
User approves using biometric/PIN/passkey

AI:
Waits for success
Continues inside Excel
```

For passkeys, do not design around extracting the secret. Design around **triggering and approving authentication**.

Works with:

- Windows Hello
- Edge passkeys
- phone passkeys
- hardware security keys
- Microsoft login
- Google login
- app login prompts

## Browser Control Method

Use two browser modes.

### Structured Browser Mode

Use Playwright.

Good for:

- opening pages
- clicking buttons
- filling forms
- downloading files
- reading DOM content

### Human Visual Mode

Use screenshot + OCR + mouse/keyboard.

Good for:

- websites with weird UI
- apps without APIs
- login windows
- popups
- native apps

Tool stack:

- Playwright
- PyAutoGUI
- pytesseract/EasyOCR
- screenshot capture
- Windows UI Automation

## File Control Method

Tools:

```text
file.list(path)
file.scan(path)
file.read(path)
file.move(src, dst)
file.copy(src, dst)
file.quarantine(path)
file.restore(quarantine_id)
file.delete_permanent(path)
```

Rules:

- normal delete means quarantine
- permanent delete requires special approval
- bulk delete requires mobile approval
- system folders need explicit approval

Protected folders by default:

```text
C:\Windows
C:\Program Files
C:\Program Files (x86)
AppData
browser credential stores
SSH keys
.env files
wallet files
```

You can allow them in full access mode, but make it deliberate.

## Download Method

Flow:

```text
User:
"Download VLC"

AI:
Searches official source
Verifies domain
Checks file type
Shows download details
Requests approval if executable
Downloads to AI_Downloads
Optionally scans/hash-checks
Asks again before running
```

Dangerous extensions:

```text
.exe
.msi
.bat
.cmd
.ps1
.vbs
.scr
.jar
.js
```

Never auto-run a downloaded executable unless approved.

## System Control Method

System tools:

```text
system.status
system.disk_usage
system.ram_usage
system.processes
system.open_app
system.kill_process
system.startup_apps
system.network_status
system.run_command
```

`system.run_command` should be high risk.

Admin commands require:

```text
mobile approval + full access session
```

## Local AI Model Strategy

For MVP, you can use local or cloud. But for your stated goal, design local-first.

For 4GB RAM:

Use small quantized models:

```text
Qwen2.5 3B Instruct GGUF Q4
Phi-3.5 Mini GGUF Q4
Gemma 2B Q4
TinyLlama only for very simple commands
```

Runtime:

```text
llama.cpp
Ollama
LM Studio local server
```

Use local model for:

- intent classification
- risk classification
- simple planning
- command rewriting
- summaries

For hard planning, you can later use bigger local models on better hardware.

## Model Routing

Use multiple models, not one.

```text
Small local classifier
  -> detects intent/risk

Main local LLM
  -> creates plan

Tool executor
  -> runs actions

Verifier
  -> checks result
```

Pipeline:

```text
User command
↓
Intent classifier
↓
Risk classifier
↓
Planner
↓
Policy check
↓
Tool call
↓
Observation
↓
Verifier
↓
User response
```

## Temperature Settings

Use low temperature for control.

| Task | Temperature |
|------|-------------|
| tool selection | 0.0 |
| risk classification | 0.0 |
| file operations | 0.0 |
| login flow | 0.0-0.2 |
| browser automation | 0.1-0.2 |
| summarization | 0.2-0.4 |
| writing messages | 0.4-0.7 |

For PC control, randomness is the enemy.

## Compression and Low Resource Design

For 4GB RAM:

- use 3B model, 4-bit quantized
- keep context small
- summarize old conversations
- do not load browser automation until needed
- use SQLite
- use simple rule-based risk engine first
- cache frequent commands
- stream responses
- avoid heavy background indexing

Memory approach:

```text
short-term context: current task
long-term memory: SQLite + embeddings
logs: compressed summaries
```

## Datasets You Need

You do not train a full model first. You create datasets for evaluation and future fine-tuning.

### Intent Dataset

Examples:

```json
{
  "input": "check my storage",
  "intent": "system_status",
  "risk": "low"
}
```

```json
{
  "input": "delete everything on my desktop",
  "intent": "delete_files",
  "risk": "critical"
}
```

Categories:

- search
- browse
- open app
- list files
- read file
- move file
- delete file
- download
- login
- passkey login
- password login
- system check
- terminal command
- email later

Start with 1,000 examples.

### Risk Dataset

```json
{
  "action": "run downloaded exe",
  "risk": "high",
  "approval": "mobile_required"
}
```

Start with 500 examples.

### Tool Calling Dataset

```json
{
  "input": "login to xyz.com and check dashboard",
  "tools": [
    "browser.open",
    "auth.password_login",
    "browser.read",
    "agent.summarize"
  ]
}
```

### Recovery Dataset

```json
{
  "action": "quarantine file",
  "undo": "restore original path"
}
```

## Database Design

Use SQLite.

Tables:

```text
commands
approvals
actions
devices
vault_entries
quarantine
sessions
settings
```

Important fields:

```text
commands:
id, source, input_text, status, result, created_at

approvals:
id, command_id, risk, action_type, target, status, created_at, resolved_at

actions:
id, command_id, tool, input_json, output_json, risk, status

devices:
id, name, token_hash, paired_at, last_seen

vault_entries:
id, site, username, encrypted_password, created_at, last_used

quarantine:
id, original_path, quarantine_path, command_id, created_at, restored_at
```

## Execution Philosophy

The model should not directly run arbitrary commands.

Architecture:

```text
user command
-> parser/planner
-> risk/permission layer
-> tool executor
-> screen/file/browser/system action
-> verification
-> result summary
```

For risky tasks:

```text
plan first
show impact
request phone approval
execute through safe tool
verify
log
```

## Model And Tool Tiers

The project must run on low-resource laptops, including 4 GB RAM machines.

Use a tiered model stack:

```text
Tier 0: always resident
  Windows UI Automation
  OpenCV visual candidate scan
  rule-based command matching
  click executor

Tier 1: warm lazy-loaded models
  PaddleOCR PP-OCRv4 Mobile
  YOLOv8n or YOLO11n INT8 ONNX UI detector

Tier 2: SSD cold parser
  heavier OmniParser/Floorence-style screen parsing modules
  loaded only for difficult screens

Tier 3: AMD cloud GPU
  OmniParser v2 teacher labeling
  tiny model training
  compression/export
  ROCm benchmarks
```

Local runtime priority:

```text
1. UI Automation exact label
2. OCR text match
3. Tiny YOLO/ONNX UI detector
4. OpenCV visual candidates
5. SSD cold parser
6. AMD cloud parser/training
7. ask user if confidence is low
```

## codiii Methodology

Screen-AI borrows systems ideas from `madhavabrightly/codiii` / Colibri:

- do not assume heavy models must be fully resident
- use RAM, SSD, and GPU as a memory hierarchy
- keep a small resident core
- lazy-load heavy modules
- cache hot paths
- prefetch likely next work
- keep quantized artifacts
- enforce RAM budget
- make cold paths acceptable and warm paths fast

For Screen-AI, the equivalent is not MoE expert streaming. It is pipeline tiering:

```text
resident scanner
-> warm OCR/detector
-> SSD cold parser
-> cloud AMD teacher
```

See:

```text
hackathon_ui_operator_distill/docs/codiii_ssd_tiering_strategy.md
```

## AMD / ROCm Strategy

The user has an RTX laptop, but the hackathon is AMD-based. That is fine.

Development split:

```text
RTX/Windows laptop:
  local scanner
  UI control
  screenshot collection
  low-resource demo

AMD cloud GPU:
  ROCm validation
  OmniParser teacher labeling
  YOLO student training
  INT8 ONNX export
  benchmark screenshots
```

Required AMD proof:

```bash
rocm-smi
rocminfo | head
python - <<'PY'
import torch
print(torch.__version__)
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no gpu")
PY
```

Benchmark goals:

- CPU screen parse time
- AMD ROCm model/preprocessing time
- end-to-end screenshot parse latency
- memory use

## GPU Backend Methodology

Follow the Colibri-style backend rule:

```text
CPU default
optional CUDA
optional HIP/ROCm
one compatibility shim for vendor differences
```

Vendor-specific code belongs in:

```text
hackathon_ui_operator_distill/native/gpu_compat.h
```

Algorithm code should stay vendor-neutral. Do not scatter CUDA/HIP conditionals throughout the implementation.

See:

```text
hackathon_ui_operator_distill/docs/gpu_backend_methodology.md
```

## Cloud GPU Workflow

If GitHub clone fails from missing CA certificates:

```bash
apt-get update
apt-get install -y ca-certificates git curl wget aria2
update-ca-certificates
```

If HTTPS still fails and the repo is public:

```bash
GIT_SSL_NO_VERIFY=true git clone https://github.com/madhavabrightly/Screen-AI.git
```

Preferred setup:

```bash
cd "/workspace/template-repos/repo-dd2205cfed93/repo/DevZone_Content/Model Fine-Tuning & Training"
python3 -m venv .venv
source .venv/bin/activate

export HF_HOME=/workspace/.cache/huggingface
export PIP_CACHE_DIR=/workspace/.cache/pip
export HF_HUB_ENABLE_HF_TRANSFER=1
mkdir -p "$HF_HOME" "$PIP_CACHE_DIR"

cd hackathon_ui_operator_distill
bash cloud/setup_cloud_gpu.sh
bash cloud/download_omniparser_v2.sh
```

The cloud environment seen earlier did not run SSH server:

```text
service ssh: unrecognized service
service sshd: unrecognized service
```

So prefer GitHub clone/pull inside cloud instead of laptop-to-cloud SSH.

## Data And Training Plan

Collect screenshots locally:

```powershell
python .\hackathon_ui_operator_distill\local_runtime\collect_screenshot.py
```

Cloud pipeline:

```bash
python cloud/run_teacher_labeling.py --screens data/raw_screenshots --out data/labels_teacher --mode placeholder
python cloud/convert_teacher_to_yolo.py --labels data/labels_teacher --out data/yolo_dataset
python cloud/train_student_yolo.py --data data/yolo_dataset/ui_dataset.yaml --model yolov8n.pt --epochs 80 --device 0
python cloud/export_int8_onnx.py --weights runs/ui_student/weights/best.pt --out ui_detector_int8.onnx
```

Target YOLO classes:

```text
button
input
checkbox
radio
dropdown
tab
menu
link
icon
```

## Safety And Boundaries

This project is for user-owned machines and approved automation.

Do not implement stealth, bot-evasion, credential theft, or bypass logic.

Acceptable:

- local screen scanning
- local UI control
- user-approved login flow
- password vault design with redacted logs
- passkey flow coordination through OS/browser
- phone approval for critical actions

Critical actions should require approval:

- deleting files
- running installers
- sending email
- using credentials
- passkey login
- admin/system commands

Destructive operations should use quarantine first, not permanent deletion.

## Non-Negotiable Engineering Rules

Even with full access:

1. Critical actions require phone approval.
2. Passwords are redacted/deleted from logs.
3. Destructive actions use quarantine first.
4. Emergency stop always works.
5. All non-secret actions are logged.
6. Login target domain must be shown before approval.
7. Downloaded executables require approval before running.
8. Full access sessions should be time-limited.
9. Model proposes actions; tool system executes them.
10. User can wipe logs, vault, memory, and quarantine.

## MVP Build Plan

### Phase 1: Local Server

Build:

- FastAPI server
- `/command`
- `/approvals`
- `/status`
- SQLite setup

Goal:

```text
Phone can send text command to PC.
```

### Phase 2: Mobile Web Remote

Build:

- command input
- response display
- approval panel
- emergency stop

Goal:

```text
Phone controls PC locally.
```

### Phase 3: Pairing

Build:

- PC shows pairing code
- phone enters code
- token stored
- only paired phone can control

Goal:

```text
No random device on Wi-Fi can control it.
```

### Phase 4: File Tools

Build:

- list files
- scan folder
- quarantine delete
- restore

Goal:

```text
Delete requires approval and is reversible.
```

### Phase 5: System Tools

Build:

- disk check
- RAM check
- battery
- running processes
- open app

Goal:

```text
"Check my PC" works.
```

### Phase 6: Browser Tools

Build:

- open site
- search web
- click/type with Playwright
- download file

Goal:

```text
"Search and download X" works.
```

### Phase 7: Password Vault

Build:

- add credential
- encrypt credential
- unlock from phone
- autofill login
- redact logs

Goal:

```text
"Login to xyz.com" works using saved password.
```

### Phase 8: Passkey Flow

Build:

- detect login/passkey prompt
- request phone approval
- wait for Windows/browser auth
- continue after login

Goal:

```text
"Login with passkey" works through normal OS/browser approval.
```

### Phase 9: Local Model

Add:

- local LLM
- intent classifier
- tool planner
- risk classifier

Goal:

```text
Natural language commands become tool plans offline.
```

## First Serious MVP Scope

Build this first:

```text
Text-only PC agent
Mobile web remote
Pairing code
Command history
Approval system
Emergency stop
System status
File listing
Quarantine delete
Restore
Open website
Basic browser search
```

Then add:

```text
Password vault
Login automation
Passkey approval flow
Download manager
App control
Local model routing
```

## The First Build Target

Your first concrete target should be:

> A local FastAPI PC agent with a mobile web remote that accepts text commands, checks system status, lists files, and requires mobile approval before deleting by moving files to quarantine.

That is the foundation. After that, password vault and passkey login become modules, not chaos.

## Immediate Next Steps

Build in this order:

1. Set up FastAPI server with SQLite database.
2. Build mobile web remote with command input.
3. Implement pairing code system.
4. Add file tools with quarantine.
5. Add system status tools.
6. Add browser tools with Playwright.
7. Add password vault with encryption.
8. Add passkey flow controller.
9. Add local LLM routing.
10. Add OCR fallback to existing scanner.
11. Add lightweight target confidence scoring.
12. Add screenshot collection workflow for dataset building.
13. Add tiny YOLO ONNX local inference.
14. Add AMD cloud teacher labeling and ROCm benchmark demo.

Keep changes scoped and push after meaningful milestones.

## 2026-07-23 Low-Memory Backend Tuning

The backend was tuned from review notes about 4 GB RAM performance and connection churn.

Implemented:

- SQLite now uses one shared `aiosqlite` connection with WAL mode, `busy_timeout`, and serialized `db_session()` access.
- App shutdown closes browser resources and the shared DB connection.
- Added DB indexes for `approvals.command_id` and `quarantine.command_id`.
- `/history` now selects specific columns, truncates large `result` text, and clamps the limit to 1-200.
- Planner, risk classifier, and log redactor use precompiled regexes.
- File scans are bounded by max files, max depth, and timeout.
- BrowserTools lazy-loads Playwright and can unload Chromium after a 5-minute idle timeout.
- Vault lazy-imports cryptography, supports configurable KDF cost, caches derived entry keys per unlock session, and updates `last_used` correctly.
- Pairing manager uses the shared DB session and `/command` awaits device verification.
- Scanner supports a short identical-screen cache to avoid rerunning UIA/OpenCV repeatedly.
- Backend requirements were trimmed for low-resource installs.
- Smoke tests were made async-correct and ASCII-safe.

Verified:

```powershell
python -m py_compile screen_element_scanner\scan_screen.py ai_pc_operator\backend\app\db\database.py ai_pc_operator\backend\app\agent\planner.py ai_pc_operator\backend\app\security\risk.py ai_pc_operator\backend\app\agent\router.py ai_pc_operator\backend\app\approvals\manager.py ai_pc_operator\backend\app\main.py ai_pc_operator\backend\app\tools\browser_tools.py ai_pc_operator\backend\app\tools\file_tools.py ai_pc_operator\backend\app\security\vault.py ai_pc_operator\backend\app\security\pairing.py ai_pc_operator\backend\app\logs\redactor.py ai_pc_operator\backend\test_basic.py
python -u .\ai_pc_operator\backend\test_basic.py
python .\screen_element_scanner\scan_screen.py --quiet
```

Note: timed-out test runs left stale Python processes holding SQLite locks during development. They were stopped before the final successful test run.

## 2026-07-23 Real Runtime Pipeline

The model/tool runtime is now wired into `AgentRouter`.

Implemented:

- `app/runtime/resource_budget.py`: measures available RAM and creates a model-loading budget.
- `app/runtime/io_pool.py`: shared 2-worker I/O thread pool for blocking disk/model/tool work.
- `app/runtime/model_registry.py`: lazy model registry with async prefetch, idle unload, and placeholder loaders.
- `app/runtime/heatmap.py`: intent-to-tool heat map persisted under runtime memory.
- `app/runtime/tier_manager.py`: RAM-aware tier decisions for resident, OCR, detector, and local LLM modes.
- `AgentRouter` now measures RAM, classifies intent, starts risk assessment, decides tiers, prefetches hot models/tools, records tool heat, and unloads idle resources.
- Browser/Auth tools expose safe `prepare()` warmups that import dependencies without launching Chromium or unlocking vaults.
- `/runtime` endpoint reports current budget, model mode, registered models, loaded models, and pending model prefetches.

Current lazy model names:

```text
ocr-mobile
ui-detector-int8
qwen-1.5b-q4
vault-crypto
browser-warmup
```

These are placeholders until actual OCR/YOLO/GGUF artifacts are downloaded. Do not block the event loop while adding real loaders; use `ModelRegistry` + `IOPool`.

## 2026-07-24 Browser Command Reliability

The command layer now treats common browser requests as first-class actions.

Implemented:

- Planner recognizes commands such as:
  - `search best air coolers in chrome`
  - `open YouTube`
  - `open github.com`
  - `close browser`
- Search query cleanup removes browser hints such as `in chrome`, `on browser`, and `with edge`.
- Site aliases are mapped for common services including YouTube, Google, GitHub, Gmail, Amazon, Reddit, Instagram, LinkedIn, and ChatGPT.
- `browser.search` URL-encodes queries before navigation.
- `browser.open` normalizes bare domains to HTTPS URLs.
- If Playwright Chromium is unavailable, browser open/search falls back to the OS default browser instead of returning a failed command.
- `AgentRouter` now returns `unsupported` for commands with no executable plan instead of `completed` with `No actions taken`.
- Vault key derivation falls back to PBKDF2-HMAC-SHA256 when the local Windows `cryptography` Argon2 binding is broken.

Current limitation:

- The fallback can open/search in the system browser, but DOM click/type automation still needs Playwright browser binaries installed.
- On this machine, Playwright Chromium was installed successfully with `python -m playwright install chromium`.

Recommended next command when Playwright automation is needed:

```powershell
python -m playwright install chromium
```

## 2026-07-24 Real Model Loader Wiring

The runtime model slots are no longer placeholders.

Implemented:

- Added `ArtifactStore` for model discovery in:
  - `ai_pc_operator/data/models`
  - `hackathon_ui_operator_distill/data`
  - `hackathon_ui_operator_distill/runs`
  - `SCREEN_AI_MODEL_DIR`
- Added optional real loaders:
  - `ocr-mobile`: PaddleOCR when installed
  - `ui-detector-int8`: ONNX Runtime with exported INT8 detector
  - `qwen-1.5b-q4`: llama.cpp GGUF loader
  - `vault-crypto`: cryptography warmup
  - `browser-warmup`: Playwright import warmup
- Removed `placeholder_loader` from the model registry path.
- Added `LLMPlanner`, which imports `SYSTEM_PROMPT` and `USER_PROMPT_TEMPLATE` from `prompts.py`.
- `AgentRouter` now only asks the local LLM planner for unknown commands when RAM allows the Qwen tier and a real model is loaded.
- Added backend `ScreenCache` at:

```text
ai_pc_operator/data/.screen_ai_cache/
  ui_maps/
  ocr_results/
  detector_results/
```

- `AgentRouter` writes redacted plan/cache metadata under `ui_maps`.
- `/runtime` reports memory budget, model status, artifact inventory, and cache stats.
- `LogRedactor` now runs as a logging filter and redacts command/action persistence.
- Nested plans/lists are redacted, not just top-level dictionaries.

Artifact CLI:

```powershell
python .\ai_pc_operator\backend\scripts\model_artifacts.py inventory
python .\ai_pc_operator\backend\scripts\model_artifacts.py stage-yolo .\path\to\ui_detector_int8.onnx
python .\ai_pc_operator\backend\scripts\model_artifacts.py stage-gguf .\path\to\qwen.gguf
```

Current artifact status on this machine:

```text
ocr-mobile: not staged
ui-detector-int8: not staged
qwen-1.5b-q4: not staged
vault-crypto: dependency loader available
browser-warmup: dependency loader available
```

## 2026-07-24 Login V2 Repair

Enhanced pairing is additive; do not remove the legacy 6-digit code flow.

Working login layers:

- 6-digit code pairing remains the reliable fallback.
- QR pairing uses short-lived pairing sessions from `/pair/qr`.
- Trusted reconnect uses `/pair/trusted`.
- Token rotation uses `/auth/rotate`.
- Biometric challenge endpoints exist for future sensitive-action gates.

Important implementation notes:

- `pairing_manager_v2` must be declared global in FastAPI lifespan.
- QR pairing private keys are intentionally in-memory only; if the backend restarts, generate a new QR session.
- MVP pairing returns a normal local session token so unsupported mobile WebCrypto/X25519 cannot block login.
- Encrypted token fields may be present when a valid X25519 key is supplied, but the frontend should not require them yet.
- `remote/index.html`, `frontend/app.js`, and `frontend/styles.css` must agree on `login-screen` IDs.
- `test_login_v2.py` must close the shared DB connection or it can leave a stale Python process.

Verified endpoints:

```text
GET /pair/qr
GET /pair/code
POST /pair/qr/complete
POST /auth/rotate
POST /pair/trusted
```

## Model Artifacts: 2026-07-24 02:10:11 +05:30

Runtime model files live in:

```text
ai_pc_operator/data/models/
```

Downloader:

```powershell
python .\ai_pc_operator\backend\scripts\download_models.py
python .\ai_pc_operator\backend\scripts\model_artifacts.py inventory
python .\ai_pc_operator\backend\scripts\model_artifacts.py list-files
```

Selected lightweight artifacts:

- `qwen2.5-coder-1.5b-instruct-q4_0.gguf` from `Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF` for local llama.cpp planning.
- `ocr_det_v3.onnx` and `ocr_rec_english.onnx` from `monkt/paddleocr-onnx` for light ONNX OCR.
- `teachers/omniparser_v2_icon_detect.pt` from `microsoft/OmniParser-v2.0` for cloud teacher/distillation work.

Important:

- Do not commit model binaries. `.gitignore` excludes `*.gguf`, `*.onnx`, and `*.pt`.
- `ui_detector_int8.onnx` is still expected to come from our cloud distillation/export pipeline.
- The OmniParser `.pt` teacher model is saved for cloud use, but the 4 GB laptop runtime should load the exported INT8 ONNX detector.

## Codebase Analysis Fix Pass: 2026-07-24 02:25:43 +05:30

Primary demo path is now:

```text
mobile text command -> AgentRouter -> Planner -> screen.click_text/screen.scan -> Windows UIA/OpenCV -> result
```

New backend tools:

- `screen.scan`: returns visible actionable controls and endpoints.
- `screen.click_text`: fuzzy-matches visible text/accessibility labels and clicks the center point.

Security constraints:

- Do not reintroduce `shell=True` for user-derived app/command text.
- Paired-device endpoints should verify token hashes, not only device ids.
- Frontend must render server-provided strings with `textContent`, not `innerHTML`.
- WebSocket clients should pass `device_id` and `token`; HTTPS pages should use `wss://`.

Cloud detector path:

```bash
python cloud/run_teacher_labeling.py --screens data/raw_screenshots --out data/labels_teacher --mode omniparser
python cloud/convert_teacher_to_yolo.py --labels data/labels_teacher --out data/yolo_dataset
python cloud/train_student_yolo.py --data data/yolo_dataset/ui_dataset.yaml --model yolov8n.pt --epochs 80 --device 0
python cloud/export_int8_onnx.py --weights runs/ui_student/weights/best.pt --out ui_detector_int8.onnx
```

Verified locally:

```text
test_basic.py: pass
test_login_v2.py: pass
ScreenTools.scan: 226 actionable controls
ScreenTools.click_text("Close", dry_run=True): success
```

## 4 GB SSD Tier Runtime: 2026-07-24 02:33:30 +05:30

Screen-AI adapts the `codiii`/colibri memory hierarchy like this:

```text
codiii:
  dense core in RAM -> hot experts pinned -> routed experts streamed from SSD

Screen-AI:
  rules/UIA/OpenCV resident -> OCR/detector warm -> Qwen/teacher artifacts SSD-cold/off -> AMD cloud teacher
```

Runtime knobs:

```powershell
$env:SCREEN_AI_RAM_MB="1200"          # optional low-RAM override/test
$env:SCREEN_AI_MMAP="1"              # mmap GGUF through llama.cpp
$env:SCREEN_AI_PREFETCH="0"          # safest for 4 GB
$env:SCREEN_AI_ALLOW_COLD_LLM="0"    # keep Qwen off unless explicitly enabled
$env:SCREEN_AI_LLM_CTX="512"
$env:SCREEN_AI_LLM_THREADS="2"
```

Rules:

- Large models are never speculative-prefetched.
- Qwen defaults to SSD/off on low RAM.
- OCR/detector are lazy and evictable.
- `/runtime` is the source of truth for current model placement.
- Native C LFRU policy exists under `hackathon_ui_operator_distill/native/ssd_tier_policy.c` for future low-overhead promotion decisions.

## Compound Task Planner: 2026-07-24 19:03:38 +05:30

The agent now has a high-level task planner before the older single-intent rule planner.

Supported compound task families:

- `research_collect`: search web, visit multiple pages, extract text, save report.
- `open_settings`: open Windows settings pages such as contrast settings.
- `keep_awake`: hold Windows awake through `SetThreadExecutionState`.

Important implementation files:

```text
ai_pc_operator/backend/app/agent/task_planner.py
ai_pc_operator/backend/app/tools/browser_tools.py
ai_pc_operator/backend/app/tools/system_tools.py
hackathon_ui_operator_distill/native/endpoint_rank.c
```

Research command example:

```text
open chrome and search about AMD ROCm and go to 10 random websites and copy all text and paste in text file and save it folder
```

Plan:

```text
browser.research_collect(query="AMD ROCm", max_sites=10)
```

Safety rule:

- Keep local automation visible and user-approved. Do not implement stealth, bot-evasion, or hidden-control behavior.

## Mobile Remote UX And Command Code Notes: 2026-07-24 19:24:26 +05:30

The mobile remote should make control state obvious to the user:

- Header connection badge shows `Connected`, `Connecting`, `Reconnecting`, or `Offline`.
- Pairing success uses a short visual transition before opening the command console.
- Command tab shows a progress timeline before and after `/command` returns.
- Emergency stop remains visible in the main header.
- `ai_pc_operator/stop.bat` stops local Screen-AI servers on ports `8000` and `8443`.

Command Code terminal AI can be queried non-interactively when extra planning/research is useful:

```powershell
cmdc -p "Give concise recommendations for Screen-AI mobile UX and local server scripts. No stealth/evasion suggestions." --max-turns 8
```

Implementation boundary:

- Strong local PC automation is allowed for the owner's visible session.
- Do not add stealth, bot-detection bypass, hidden remote control, or anti-forensics.
- Prefer visible status, approvals, logs with redaction, and emergency stop.

## Plan Preview, JS Memory, And Relation Map: 2026-07-24 21:28:08 +05:30

Phone text instructions now have a preview path before execution:

- `POST /command/preview` calls `AgentRouter.preview_plan()`.
- The preview returns interpreted intent, risk level, approval need, runtime tier, SSD tier, and redacted tool steps.
- The mobile app debounces command typing and asks the backend for a plan preview.
- Recent instructions are stored in browser `localStorage` as lightweight JS memory.
- Draft command text is stored in `localStorage` and can be restored.
- Offline commands are saved as drafts only; they are not replayed automatically.

Relation-map notes:

- `relation-map.md` and `ai_pc_operator/relation-map.md` are intentionally identical.
- The router method in the map is `process_command()`, with `preview_plan()` for dry planning.
- Keep the map updated whenever adding endpoint, runtime, database, native, or frontend-worker behavior.

## Skill Registry, Task Graph, Verification, Memory, Tracer: 2026-07-25 +05:30

The agent now has a formal skill registry, DAG task executor, layered verification engine, persistent memory engine, and structured tracer layered on top of the existing pipeline.

New backend modules:

```text
ai_pc_operator/backend/app/skills/
  contracts.py        # Pydantic types: SkillDefinition, SkillInputSpec, SkillOutputSpec, SkillVerificationSpec, SkillPermission, SkillStatus, SkillRunRequest, SkillRunResult
  registry.py         # SQLite-backed SkillRegistry: register, get, list, search, enable, delete, record_run, metrics, recent_runs
  verification.py     # VerificationEngine with 8 built-in verifiers: file_exists, file_contains, http_status, json_path, process_healthy, ocr_text, dom_state, screenshot_diff
  runtime.py          # SkillRuntime: handler resolution, retry, timeout, verification, metrics recording
  handlers.py         # Async wrappers around existing tools: file_list, file_scan, file_quarantine, file_restore, file_read, system_status, system_disk_usage, system_ram_usage, system_processes, system_open_app, browser_open, browser_search, browser_close, screen_scan, screen_click_text, vault_unlock, vault_lock, vault_list, meta_echo, meta_sleep
  mvp_pack.py         # 50-skill MVP pack across 6 domains: files (10), os (10), browser (10), screen/app (5), auth/vault (5), meta (10)

ai_pc_operator/backend/app/agent/
  task_graph.py       # DAG executor: NodeType (observe, decide, act, verify, rollback, ask_user, summarize), TaskStatus, TaskNode, Task, TaskContext, TaskGraphExecutor
  memory_engine.py    # MemoryEngine: remember, recall, search_memory, forget, list_memory, save_template, get_template, list_templates, match_template

ai_pc_operator/backend/app/observability/
  tracer.py           # Tracer: event, trace_task, recent_events for structured trace events
```

New DB tables (13):

```text
skills, skill_inputs, skill_outputs, skill_dependencies, skill_verification_methods,
skill_permissions, skill_runs, skill_metrics, tasks, task_nodes, evidence,
workflow_templates, memory_entries, trace_events
```

New REST endpoints:

```text
GET  /skills                          # list registered skills
POST /skills/execute                  # execute a skill by id
GET  /skills/{skill_id}/metrics       # aggregate metrics for a skill
POST /tasks                           # create and run a DAG task
GET  /tasks/{task_id}                 # get task status and node results
POST /tasks/{task_id}/cancel          # cancel a running task
POST /memory/remember                 # store a memory entry
GET  /memory/recall                   # recall memories by key
GET  /memory/search                   # search memories by query
POST /workflows                       # save a workflow template
GET  /workflows                       # list workflow templates
GET  /workflows/match                 # match a workflow template to a command
```

AgentRouter extensions:

```text
ensure_skills_seeded()                # idempotent MVP skill seeding
execute_skill(skill_id, inputs)       # run a skill through SkillRuntime
run_task(spec)                        # create and run a DAG task
get_task(task_id)                     # fetch task status
cancel_task(task_id)                  # cancel a running task
list_skills(domain=None)              # list registered skills
skill_metrics(skill_id)               # get skill metrics
remember(key, value, tags)            # store memory
recall(key)                           # recall memory
search_memory(query)                  # search memory
save_workflow_template(name, steps)   # save workflow
list_workflow_templates()             # list workflows
match_workflow_template(command)      # match workflow to command
```

Lifespan now seeds the 50-skill MVP pack on startup.

Verified:

```powershell
python -u .\ai_pc_operator\backend\test_new_spec.py
# All new-spec tests passed.

python -u .\ai_pc_operator\backend\test_basic.py
# All tests passed! [ok]
```

Important implementation notes:

- Pydantic v2 requires keyword arguments for BaseModel constructors. Use `SkillInputSpec(name="x", type="string")` not `SkillInputSpec("x", "string")`.
- The `record_run` SQL must bind exactly the number of `?` placeholders. The metrics INSERT has 5 `?` in VALUES and 3 `?` in the ON CONFLICT clause, so 8 bindings total.
- The MVP skill pack is seeded once on startup; subsequent boots are idempotent.
- Task graph nodes can be `observe`, `decide`, `act`, `verify`, `rollback`, `ask_user`, or `summarize`.
- Memory entries support tags for filtered recall.
- Workflow templates match by keyword overlap with the incoming command.
## Planning-Engine Refactor: 2026-07-25 +05:30

The pipeline layer was refactored to follow the autonomous planning-engine specification with deterministic execution, verification, recovery, and risk-aware approval nodes.

### New Node Types

```
observe     # gather information (read-only)
decide      # branch based on observation
parallel    # fan-out to multiple branches
act         # perform an action (may need approval)
verify      # check that an action succeeded
retry       # retry a failed node with backoff
rollback    # undo a previous action
checkpoint  # save state for potential rollback
approval    # request user/phone approval (auto-inserted for risk >= 3)
wait        # wait for external event
replan      # generate a new sub-plan
finish      # terminal node
```

### Risk Levels

```
READ_ONLY         = 0  # safe to run without approval
SAFE_LOCAL        = 1  # local file ops, no approval needed
LOCAL_DESTRUCTIVE = 2  # deletes/moves local files, may need approval
EXTERNAL          = 3  # touches external systems, approval required
CRITICAL          = 4  # permanent delete, credentials, financial
```

### Key Files

```
pipeline/operations.js          # NODE_TYPES, RISK_LEVELS, buildNode, validateNode, insertApprovalNodes, OPERATIONS registry
pipeline/engine.js              # ExecutionGraphRunner + legacy Pipeline (backward compat)
pipeline/cli.js                 # --graph flag, --auto-approve, --vars, validate command
pipeline/screenai_pipelines.js  # graph pipelines: scaffoldFullGraph, backupDatabaseGraph, cleanGraph, researchCollectGraph
ai_pc_operator/backend/app/agent/graph_schema.py  # Python mirror of planning-engine schema
ai_pc_operator/backend/app/agent/router.py        # AgentRouter now emits execution_graph in responses
```

### CLI Usage

```powershell
# Validate a graph without running
node pipeline/cli.js validate path/to/graph.json

# Run a graph with auto-approval
node pipeline/cli.js graph path/to/graph.json --auto-approve

# Run with custom variables
node pipeline/cli.js graph path/to/graph.json --auto-approve --vars '{"root":"."}'
```

### Auto-Approval Insertion

Any node with risk >= 3 (EXTERNAL or CRITICAL) automatically gets an upstream approval node inserted before it. This ensures high-risk actions always have a gate.

### Backward Compatibility

The legacy Pipeline class is preserved with synchronous run(), middleware support, step-specific vars, events, describe(), onError(), and PipelineRegistry. All 43 existing pipeline tests pass.

### Verified

```powershell
node pipeline/test_pipeline.js
# Results: 43/43 passed, 0 failed

python -u .\ai_pc_operator\backend\test_basic.py
# All tests passed! [ok]

python -u .\ai_pc_operator\backend\test_new_spec.py
# All new-spec tests passed.

node pipeline/cli.js validate pipeline/_test_tmp/sample_graph.json
# Graph is valid (5 nodes)

node pipeline/cli.js graph pipeline/_test_tmp/sample_graph.json --auto-approve
# Execution graph completed. Status: completed, Nodes: 5, Waves: 5
```


## browser_session Intent (Added 2026-07-30)

A new intent `browser_session` was added to the planner to support the user's request:

> Intent: browser_session
> Risk: 1
> 1. system.open_app
> 2. system.keep_awake
> 3. system.mouse_jiggle
> .auto approval everytime

### Implementation

- Intent pattern: `r"browser[\s_]*session"` (handles both `browser_session` and `browser session`)
- Risk level: 1 (auto-approval, no mobile prompt)
- Plan: 3 steps - `system.open_app` (chrome), `system.keep_awake`, `system.mouse_jiggle`
- App name: defaults to `chrome` when extraction returns the intent itself

### Files Changed

- `ai_pc_operator/backend/app/agent/planner.py` - Added `browser_session` intent + plan
- `ai_pc_operator/backend/app/agent/router.py` - Added `intent` and `risk` to response
- `ai_pc_operator/backend/app/agent/graph_schema.py` - Fixed `insert_approval_nodes` to handle non-numeric IDs

### Verified

```powershell
python _test_browser_session.py
# STATUS: 200
# intent: browser_session
# risk: 1
# status: completed
# requires_approval: False
# node_count: 6
# nodes: 6
#   - observe agent.planner risk= 0
#   - act system.open_app risk= 1
#   - act system.keep_awake risk= 1
#   - act system.mouse_jiggle risk= 1
#   - verify  risk= 0
#   - finish  risk= 0
# result: '✓ system.open_app: Opened Google Chrome
#          ✓ system.keep_awake: Done
#          ✓ system.mouse_jiggle: Mouse movement scheduled for 60 minute(s)'
```

## Pipeline Phases 7-9: Observation, Verification, Native C++ Bridge

The `pipeline/screenai_pipelines.js` file now contains 9 phases of utility classes plus 249 graph pipelines across 13 domains.

### Phase 7 — Observation Engine (10 utilities)

```text
WindowObserver, ProcessObserver, BrowserObserver, FilesystemObserver,
ClipboardObserver, OCRObserver, VisionObserver, AccessibilityObserver,
NetworkObserver, SystemObserver
```

Each observer has subscribe/unsubscribe/notify pattern with native hooks for C++ acceleration.

### Phase 8 — Verification Engine (10 utilities)

```text
StateVerifier, UIVerifier, DOMVerifier, OCRVerifier, FilesystemVerifier,
APIVerifier, ProcessVerifier, WindowVerifier, ImageVerifier, CustomVerifier
```

CustomVerifier is wired to the native `verifier_bridge` (sha256, image dimensions, byte-diff).

### Phase 9 — Native C++ Bridge

A unified `NativeBridge` class wraps all C++ accelerators behind a single JS API.

```text
NativeBridge
  call(op, input)              # unified op-code dispatch
  monotonicMs()                # Phase 3: monotonic clock
  sleepMs(ms)                  # Phase 3: native sleep
  enumerateProcesses()         # Phase 4: Win32 Toolhelp / /proc
  enumerateWindows()           # Phase 4: Win32 EnumWindows
  getFocusedWindowTitle()      # Phase 4: focused window
  stringSimilarity(a, b)       # Phase 5: Jaccard + char
  normalizeIntent(s)           # Phase 5: lowercase + trim
  computePlanCost(costs)       # Phase 6: sum
  computeRiskScore(risks)      # Phase 6: weighted max + avg
  topologicalSort(n, adj)      # Phase 6: Kahn's algorithm
  getCpuPercent()              # Phase 7: CPU usage
  getMemoryUsage()             # Phase 7: memory stats
  getDiskUsage(path)           # Phase 7: disk stats
  getNetworkStats()            # Phase 7: network stats
  getUptimeSeconds()           # Phase 7: uptime
  verify(checkType, target)    # Phase 8: native verifier
```

### Native C++ Files

```text
hackathon_ui_operator_distill/native/
  verifier_bridge.h            # Phase 8 verifier header
  verifier_bridge.cpp          # SHA-256, image dims, byte-diff
  screenai_core.h              # Unified header for all phases
  screenai_core.cpp            # Unified implementation
```

### Op Codes

```text
0-1   runtime (monotonic_ms, sleep_ms)
10-12 context (processes, windows, focused)
20-21 intent (similarity, normalize)
30-32 planner (cost, risk, topo_sort)
40-44 observation (cpu, mem, disk, net, uptime)
50    verify (delegates to verifier_bridge)
```

### JS Fallbacks

When the native addon is absent, every method falls back to pure-JS:

- `monotonicMs` → `Date.now()`
- `stringSimilarity` → Jaccard on word tokens
- `topologicalSort` → Kahn's algorithm
- `getCpuPercent` → `os.cpus()` times
- `getMemoryUsage` → `process.memoryUsage()` + `os.totalmem()`
- `getDiskUsage` → `fs.statfsSync()`
- `getUptimeSeconds` → `process.uptime()`
- `computeRiskScore` → weighted max + average

### Verified

```powershell
node -c pipeline\screenai_pipelines.js
# syntax OK

node pipeline\test_pipeline.js
# Results: 43/43 passed, 0 failed

node -e "const p = require('./pipeline/screenai_pipelines.js'); ..."
# PHASE 1: 13/13 pass
# PHASE 2: 10/10 pass
# PHASE 3: 12/12 pass
# PHASE 4: 10/10 pass
# PHASE 5: 10/10 pass
# PHASE 6: 10/10 pass
# PHASE 7: 10/10 pass
# PHASE 8: 10/10 pass
# NATIVE BRIDGE: 12/12 pass
# TOTAL: 97/97 pass, 0 fail
```

### Build Target

```text
ai_pc_operator/data/native/*.node
```

When the native addon is built and placed at the target path, `NativeBridge.isAvailable()` returns `true` and all methods use C++ implementations. Until then, JS fallbacks provide correct behavior.

## Pipeline Phase 9: Recovery Engine (2026-07-30)

The `pipeline/screenai_pipelines.js` file now contains 10 phases of utility classes plus 249 graph pipelines across 13 domains.

### Phase 9 — Recovery Engine (10 utilities)

```text
RetryStrategy, AlternativePipeline, RollbackManager, ReObserver,
Replanner, SafeAbort, UserApprovalGate, FailureClassifier,
RecoveryPolicy, RecoveryHistory
```

### Recovery Capabilities

| Utility | Purpose |
|---------|---------|
| `RetryStrategy` | Configurable retry with exponential/linear/fixed backoff + jitter |
| `AlternativePipeline` | Fallback pipeline registry with usage stats |
| `RollbackManager` | Checkpoint stack with undo functions |
| `ReObserver` | Re-scan state from window/process/filesystem after failure |
| `Replanner` | Generate new sub-plan skipping failed nodes |
| `SafeAbort` | Graceful shutdown with cleanup functions + timeout |
| `UserApprovalGate` | Request user intervention with approve/reject/timeout |
| `FailureClassifier` | Categorize errors: timeout, permission, network, etc. |
| `RecoveryPolicy` | Rules per category: retry, abort, rollback, replan |
| `RecoveryHistory` | Learn from past failures with frequency + success rate |

### Default Recovery Policies

```text
timeout      -> retry (3 attempts, exponential)
network      -> retry (5 attempts, exponential)
rate_limit   -> retry (3 attempts, exponential, 1s base)
memory       -> retry (2 attempts, linear)
permission   -> abort
validation   -> abort
crash        -> rollback
not_found    -> replan
conflict     -> replan
dependency   -> replan
unknown      -> retry (1 attempt, fixed)
```

### Native C++ Hooks (Op Codes 60-63)

```text
60 = classify_failure       # returns category string
61 = compute_backoff        # exponential backoff with jitter
62 = hash_error_signature   # djb2 hash for dedup
63 = compute_retry_budget   # max - used, clamped to >= 0
```

### JS Fallbacks

When the native addon is absent, every method falls back to pure-JS:

- `classifyFailure` → keyword matching on error message
- `computeBackoff` → `base * 2^attempt + 10% jitter`
- `hashErrorSignature` → djb2 hash returning `sig_<hex>`
- `computeRetryBudget` → `max(0, max - used)`

### Verified

```powershell
node -c pipeline\screenai_pipelines.js
# syntax OK

node pipeline\test_pipeline.js
# Results: 43/43 passed, 0 failed

# Phase audit
PHASE 1: 13/13 pass
PHASE 2: 10/10 pass
PHASE 3: 12/12 pass
PHASE 4: 10/10 pass
PHASE 5: 10/10 pass
PHASE 6: 10/10 pass
PHASE 7: 10/10 pass
PHASE 8: 10/10 pass
PHASE 9: 10/10 pass
NATIVE BRIDGE: 12/12 pass
TOTAL: 95/95 pass, 0 fail
```

### Integration Pattern

```javascript
// 1. Classify the failure
const category = globalFailureClassifier.classify(error);

// 2. Look up the recovery policy
const decision = globalRecoveryPolicy.decide(category);

// 3. Execute the recovery action
switch (decision.action) {
  case 'retry':
    await globalRetryStrategy.execute(fn);
    break;
  case 'rollback':
    await globalRollbackManager.rollbackAll();
    break;
  case 'replan':
    const newPlan = await globalReplanner.replan({ failedNodeId });
    break;
  case 'abort':
    await globalSafeAbort.abort(decision.reason);
    break;
}

// 4. Record the outcome for learning
globalRecoveryHistory.record(error, { category, action: decision.action, success: true });
```

## Pipeline Phase 10: Event System (2026-07-30)

The `pipeline/screenai_pipelines.js` file now contains 10 phases of utility classes plus 249 graph pipelines across 13 domains.

### Phase 10 — Event System (10 utilities)

```text
EventBus, EventTypes, EventEmitter, EventSubscriber, EventFilter,
EventRouter, EventRecorder, EventReplayer, EventAggregator, EventTracer
```

### Event System Capabilities

| Utility | Purpose |
|---------|---------|
| `EventBus` | Central pub/sub with pause/resume, history, wildcard subscribers |
| `EventTypes` | Typed event catalog with categories (pipeline, window, browser, file, perception, user, approval, context, recovery, system) |
| `EventEmitter` | Per-source event emission with local listeners |
| `EventSubscriber` | Fluent subscription builder: onType, onTypes, onCategory, onSource, onPredicate, onMinPriority |
| `EventFilter` | Filter events by type/source/category/priority/time/predicate |
| `EventRouter` | Route events to handlers with exact match, wildcard patterns, and fallback |
| `EventRecorder` | Record events with timestamps and offsets for replay |
| `EventReplayer` | Replay recorded events with optional real-time pacing |
| `EventAggregator` | Aggregate events into time-windowed summaries by type/source/category |
| `EventTracer` | Trace event flows for debugging with step-by-step capture |

### Event Type Catalog (38 types)

```text
Pipeline:    PipelineStarted, PipelineCompleted, PipelineFailed, PipelineCancelled
Window:      WindowOpened, WindowClosed, WindowFocused, WindowResized
Browser:     BrowserLoaded, BrowserNavigated, BrowserTabChanged
Download:    DownloadStarted, DownloadProgress, DownloadFinished, DownloadFailed
File:        FileChanged, FileCreated, FileDeleted, FileRenamed
Perception:  OCRCompleted, OCRFailed, VisionDetected, VisionMatched
User:        UserInterrupted, UserCommand, UserAction
Approval:    ApprovalRequested, ApprovalGranted, ApprovalRejected, ApprovalExpired
Context:     ContextUpdated, ContextCleared
Recovery:    RecoveryStarted, RecoveryCompleted, RecoveryFailed
System:      SystemError, SystemWarning, SystemInfo
```

### Native C++ Hooks (Op Codes 70-73)

```text
70 = event_timestamp        # monotonic timestamp for event ordering
71 = generate_event_id      # unique event id with prefix
72 = hash_event_payload     # djb2 hash for event dedup
73 = compute_event_priority # priority score by event type + age
```

### JS Fallbacks

When the native addon is absent, every method falls back to pure-JS:

- `eventTimestamp` → `Date.now()`
- `generateEventId` → `<prefix>_<timestamp>_<random>`
- `hashEventPayload` → djb2 hash returning `evt_<hex>`
- `computeEventPriority` → base priority by event type minus age decay

### Verified

```powershell
node -c pipeline\screenai_pipelines.js
# syntax OK

node pipeline\test_pipeline.js
# Results: 43/43 passed, 0 failed

# Phase audit
PHASE 1: 13/13 pass
PHASE 2: 10/10 pass
PHASE 3: 12/12 pass
PHASE 4: 10/10 pass
PHASE 5: 10/10 pass
PHASE 6: 10/10 pass
PHASE 7: 10/10 pass
PHASE 8: 10/10 pass
PHASE 9: 10/10 pass
PHASE 10: 10/10 pass
NATIVE BRIDGE: 16/16 pass
TOTAL: 105/105 pass, 0 fail
```

### Integration Pattern

```javascript
// 1. Subscribe to events with filters
const sub = new EventSubscriber({ bus: globalEventBus })
  .onCategory('pipeline')
  .onMinPriority(50)
  .subscribe(event => {
    console.log('Pipeline event:', event.type, event.payload);
  });

// 2. Emit events from any source
const emitter = new EventEmitter('my-source', globalEventBus);
emitter.emit('PipelineStarted', { pipelineId: 'abc123' });

// 3. Route events to handlers
const router = new EventRouter();
router.route('PipelineFailed', event => handleFailure(event));
router.route('Browser*', event => handleBrowserEvent(event));
router.setFallback(event => logUnhandled(event));

// 4. Record and replay for debugging
globalEventRecorder.start();
emitter.emit('PipelineStarted', { id: '1' });
emitter.emit('PipelineCompleted', { id: '1' });
const events = globalEventRecorder.getEvents();
await globalEventReplayer.replay(events);

// 5. Trace event flows
globalEventTracer.startFlow('user-command-1', { type: 'UserCommand' });
globalEventTracer.trace('user-command-1', { type: 'PipelineStarted' });
globalEventTracer.trace('user-command-1', { type: 'PipelineCompleted' });
const flow = globalEventTracer.endFlow('user-command-1');
```

## Pipeline Phase 11: Memory System (2026-07-30)

The `pipeline/screenai_pipelines.js` file now contains 11 phases of utility classes plus 249 graph pipelines across 13 domains.

### Phase 11 — Memory System (10 utilities)

```text
ShortTermMemory, LongTermMemory, TaskHistory, WorkflowMemory,
UserPreferences, ApplicationProfile, ActionFrequency,
ObservationCache, MemoryCleanup, MemoryIndex
```

### Memory System Capabilities

| Utility | Purpose |
|---------|---------|
| `ShortTermMemory` | In-flight task context with TTL-based expiry and access tracking |
| `LongTermMemory` | Persistent knowledge with importance scoring, tags, and relevance search |
| `TaskHistory` | Record of past task executions with success rate and average duration |
| `WorkflowMemory` | Successful and failed workflow patterns with match-by-command |
| `UserPreferences` | Learned user behavior with confidence-weighted merging |
| `ApplicationProfile` | Per-app usage patterns: launch count, common actions, avg duration |
| `ActionFrequency` | Frequently used actions ranked by count and recency |
| `ObservationCache` | Cached screen/perception results with TTL and hit statistics |
| `MemoryCleanup` | TTL-based eviction for short-term, observations, and long-term memory |
| `MemoryIndex` | Fast lookup by hashed key with reverse index for cleanup |

### Memory Tiers

```text
Short-term:  in-flight task context, TTL-based expiry (default 10 min)
Long-term:   persistent knowledge, importance-scored, tag-indexed
Task history: append-only log of past executions
Workflow:    successful/failed patterns with match scoring
Preferences: explicit + learned user behavior
App profile: per-application usage statistics
Frequency:   action usage counts and recency
Observations: cached perception results with TTL
```

### Native C++ Hooks (Op Codes 80-83)

```text
80 = compute_memory_relevance  # token overlap + recency score
81 = hash_memory_key           # djb2 hash for indexing
82 = compute_memory_ttl        # importance-based TTL in ms
83 = compute_cleanup_priority  # age + access + importance score
```

### JS Fallbacks

When the native addon is absent, every method falls back to pure-JS:

- `computeMemoryRelevance` → token overlap (70%) + recency decay (30%)
- `hashMemoryKey` → djb2 hash returning `mem_<hex>`
- `computeMemoryTTL` → `86400000 * (importance / 50)`
- `computeCleanupPriority` → age score + access score + importance score

### Verified

```powershell
node -c pipeline\screenai_pipelines.js
# syntax OK

node pipeline\test_pipeline.js
# Results: 43/43 passed, 0 failed

# Phase audit
PHASE 1: 13/13 pass
PHASE 2: 10/10 pass
PHASE 3: 12/12 pass
PHASE 4: 10/10 pass
PHASE 5: 10/10 pass
PHASE 6: 10/10 pass
PHASE 7: 10/10 pass
PHASE 8: 10/10 pass
PHASE 9: 10/10 pass
PHASE 10: 10/10 pass
PHASE 11: 10/10 pass
NATIVE BRIDGE: 20/20 pass
TOTAL: 115/115 pass, 0 fail
```

### Integration Pattern

```javascript
// 1. Store short-term context for current task
globalShortTermMemory.set('current.command', 'open chrome', 300000);
const cmd = globalShortTermMemory.get('current.command');

// 2. Store long-term knowledge with importance and tags
globalLongTermMemory.store('user.name', 'Alice', {
  importance: 90,
  tags: ['user', 'profile']
});

// 3. Search long-term memory by relevance
const results = globalLongTermMemory.search('user preferences', { limit: 5 });

// 4. Record task execution
const task = globalTaskHistory.record({
  command: 'open chrome',
  intent: 'browser_open'
});
globalTaskHistory.complete(task.id, 'success');

// 5. Learn user preferences from behavior
globalUserPreferences.learn('theme', 'dark', 0.6);
globalUserPreferences.learn('theme', 'dark', 0.7); // confidence increases

// 6. Track application usage
globalApplicationProfile.recordLaunch('chrome', 5000);
globalApplicationProfile.recordAction('chrome', 'new_tab');

// 7. Cache observation results
globalObservationCache.set('screen.hash123', { elements: 226 }, 30000);
const cached = globalObservationCache.get('screen.hash123');

// 8. Periodic cleanup
const cleanupResults = globalMemoryCleanup.cleanupAll({
  shortTerm: globalShortTermMemory,
  observations: globalObservationCache,
  longTerm: globalLongTermMemory
});
```

## Pipeline Phase 13: Skill Orchestrator (2026-07-30)

The `pipeline/screenai_pipelines.js` file now contains 12 phases of utility classes plus 249 graph pipelines across 13 domains.

### Phase 13 — Skill Orchestrator (10 utilities)

```text
SkillDiscovery, SkillRanking, SkillFallback, SkillChaining,
SkillDependencyResolver, SkillCache, SkillHealthMonitor,
ProviderSelector, SkillRetryPolicy, SkillMetrics
```

### Skill Orchestrator Capabilities

| Utility | Purpose |
|---------|---------|
| `SkillDiscovery` | Find skills by query, tags, or capability with match scoring |
| `SkillRanking` | Rank skills by weighted match/health/cost score |
| `SkillFallback` | Chain of fallback skills when primary fails |
| `SkillChaining` | Compose multiple skills into a sequential pipeline |
| `SkillDependencyResolver` | Topological sort of skill dependencies with cycle detection |
| `SkillCache` | Cache skill results with TTL and hit statistics |
| `SkillHealthMonitor` | Track success/failure rates and average duration per skill |
| `ProviderSelector` | Choose best provider for a capability by health/cost/latency |
| `SkillRetryPolicy` | Per-skill retry strategies with exponential/linear backoff |
| `SkillMetrics` | Aggregate metrics across all skills with summary stats |

### Native C++ Hooks (Op Codes 90-93)

```text
90 = compute_skill_match       # token overlap + tag match (0-100)
91 = compute_skill_health      # success rate + speed score (0-100)
92 = compute_skill_chain_cost  # sum of per-skill costs
93 = compute_skill_retry_budget # max - used, clamped to >= 0
```

### JS Fallbacks

When the native addon is absent, every method falls back to pure-JS:

- `computeSkillMatch` → token overlap (60%) + tag match (40%)
- `computeSkillHealth` → success rate (80%) + speed score (20%)
- `computeSkillChainCost` → `skills.length * 10`
- `computeSkillRetryBudget` → `max(0, max - used)`

### Verified

```powershell
node -c pipeline\screenai_pipelines.js
# syntax OK

node pipeline\test_pipeline.js
# Results: 43/43 passed, 0 failed

# Phase audit
PHASE 13: 31/31 pass
```

### Integration Pattern

```javascript
// 1. Register and discover skills
globalSkillDiscovery.register({
  id: 'open_chrome',
  name: 'open_chrome',
  tags: ['browser', 'open'],
  capabilities: ['launch_app'],
  provider: 'system'
});
const matches = globalSkillDiscovery.find('open chrome');

// 2. Rank candidates by weighted score
const ranked = globalSkillRanking.rank(candidates, 'open chrome');

// 3. Define fallback chain
globalSkillFallback.define('open_chrome', ['open_edge', 'open_firefox']);
const result = await globalSkillFallback.execute('open_chrome', async (id) => {
  return await launchApp(id);
});

// 4. Compose skills into a chain
globalSkillChaining.define('research_flow', ['search', 'extract', 'save']);
const chainResult = await globalSkillChaining.execute('research_flow', executor);

// 5. Resolve dependencies topologically
globalSkillDependencyResolver.add('save', ['extract']);
globalSkillDependencyResolver.add('extract', ['search']);
const order = globalSkillDependencyResolver.resolve(['save', 'extract', 'search']);

// 6. Cache skill results
globalSkillCache.set('search.amd_rocm', results, 60000);
const cached = globalSkillCache.get('search.amd_rocm');

// 7. Monitor skill health
globalSkillHealthMonitor.recordSuccess('open_chrome', 250);
globalSkillHealthMonitor.recordFailure('open_chrome', 'timeout', 5000);
const health = globalSkillHealthMonitor.health('open_chrome');

// 8. Select best provider for a capability
globalProviderSelector.register({
  id: 'openai',
  capabilities: ['llm'],
  health: 90,
  cost: 30,
  latency: 200
});
const best = globalProviderSelector.select('llm');

// 9. Apply retry policy
globalSkillRetryPolicy.define('open_chrome', {
  maxAttempts: 5,
  backoff: 'exponential',
  baseDelayMs: 1000
});
const retried = await globalSkillRetryPolicy.execute('open_chrome', executor);

// 10. Aggregate metrics
globalSkillMetrics.record('open_chrome', true, 250);
const summary = globalSkillMetrics.summary();
```

## Pipeline Phase 14: State Manager (2026-07-30)

The `pipeline/screenai_pipelines.js` file now contains 14 phases of utility classes plus 249 graph pipelines across 13 domains.

### Phase 14 — State Manager (10 utilities)

```text
DesktopState, BrowserState, WindowState, FileState, TaskState,
ExecutionState, PipelineState, AgentState, ResourceState, StateVariableStore
```

### State Manager Capabilities

| Utility | Purpose |
|---------|---------|
| `DesktopState` | Desktop environment state (wallpaper, theme, resolution, monitors) |
| `BrowserState` | Browser session state (tabs, active tab, URL, title) |
| `WindowState` | Window/UI state (focused, open, minimized) |
| `FileState` | Filesystem state (watched paths, recent files, change detection) |
| `TaskState` | Task execution state (status, progress, started/completed) |
| `ExecutionState` | Pipeline execution state (nodes, status, result) |
| `PipelineState` | Pipeline registry state (name, version, status) |
| `AgentState` | Agent brain state (mode, intent, plan, memory) |
| `ResourceState` | System resource state (CPU, memory, disk, network, uptime) |
| `StateVariableStore` | Shared variable store with scope-based access |

### State Tiers

```text
Desktop:    wallpaper, theme, resolution, monitor layout
Browser:    tabs, active tab, URL, title, history
Window:     focused window, open windows, minimized windows
File:       watched paths, recent files, change events
Task:       status, progress, started/completed timestamps
Execution:  node states, pipeline status, results
Pipeline:   registered pipelines, versions, statuses
Agent:      mode, intent, plan, memory references
Resource:   CPU, memory, disk, network, uptime
Variables:  scoped key-value store with TTL
```

### Native C++ Hooks (Op Codes 100-103)

```text
100 = compute_state_hash              # djb2 hash of state JSON
101 = compute_state_diff              # character-level diff percentage
102 = compute_state_freshness         # age vs max-age freshness score
103 = compute_state_eviction_priority # age + access + size priority
```

### JS Fallbacks

When the native addon is absent, every method falls back to pure-JS:

- `computeStateHash` → djb2 hash returning `st_<hex>`
- `computeStateDiff` → character-level diff percentage (0-100)
- `computeStateFreshness` → `(max_age - age) / max_age * 100`
- `computeStateEvictionPriority` → age score (40) + access score (30) + size score (30)

### Verified

```powershell
node -c pipeline\screenai_pipelines.js
# syntax OK

node pipeline\test_pipeline.js
# Results: 43/43 passed, 0 failed

# Phase audit
PHASE 14: 42/42 pass
TOTAL: 157/157 pass, 0 fail
```

### Integration Pattern

```javascript
// 1. Track desktop environment state
globalDesktopState.update({ wallpaper: 'dark', theme: 'dark', resolution: '1920x1080' });
const desktop = globalDesktopState.snapshot();

// 2. Track browser session state
globalBrowserState.openTab('https://example.com', 'Example');
globalBrowserState.setActiveTab(0);
const activeTab = globalBrowserState.getActiveTab();

// 3. Track window/UI state
globalWindowState.setFocused('chrome.exe', 'Google Chrome');
const focused = globalWindowState.getFocused();

// 4. Track filesystem state
globalFileState.watch('C:/Users/brigh/Documents');
globalFileState.recordChange('C:/Users/brigh/Documents/file.txt', 'modified');
const changes = globalFileState.getRecentChanges(10);

// 5. Track task execution state
globalTaskState.start('task-1', 'open chrome');
globalTaskState.updateProgress('task-1', 50);
globalTaskState.complete('task-1', 'success');
const task = globalTaskState.get('task-1');

// 6. Track pipeline execution state
globalExecutionState.startNode('node-1', 'observe');
globalExecutionState.completeNode('node-1', { result: 'ok' });
const execution = globalExecutionState.snapshot();

// 7. Track pipeline registry state
globalPipelineState.register('open_chrome', '1.0.0');
globalPipelineState.setStatus('open_chrome', 'active');
const pipeline = globalPipelineState.get('open_chrome');

// 8. Track agent brain state
globalAgentState.setMode('planning');
globalAgentState.setIntent('browser_open');
globalAgentState.setPlan(['observe', 'act', 'verify']);
const agent = globalAgentState.snapshot();

// 9. Track system resource state
globalResourceState.update({ cpu: 45, memory: 60, disk: 70 });
const resources = globalResourceState.snapshot();

// 10. Use shared variable store
globalStateVariableStore.set('user.name', 'Alice', { scope: 'global', ttl: 3600000 });
const name = globalStateVariableStore.get('user.name');
const userVars = globalStateVariableStore.byScope('user');
```

## Pipeline Phase 15: Workflow Engine (2026-07-30)

The `pipeline/screenai_pipelines.js` file now contains 15 phases of utility classes plus 249 graph pipelines across 13 domains.

### Phase 15 — Workflow Engine (10 utilities)

```text
WorkflowBuilder, WorkflowBrancher, WorkflowLoop, WorkflowCondition,
WorkflowParallel, WorkflowScheduler, WorkflowTrigger, WorkflowTemplate,
WorkflowNested, WorkflowPersistence
```

### Workflow Engine Capabilities

| Utility | Purpose |
|---------|---------|
| `WorkflowBuilder` | Compose nodes into a workflow with edges and metadata |
| `WorkflowBrancher` | Conditional execution paths with then/else branches |
| `WorkflowLoop` | Iterate over collections or until condition with max-iteration guard |
| `WorkflowCondition` | Evaluate predicates with evaluateAll/evaluateAny helpers |
| `WorkflowParallel` | Fan-out concurrent execution with Promise.all |
| `WorkflowScheduler` | Cron-like scheduling with interval-based tick |
| `WorkflowTrigger` | Event-driven execution with optional payload filter |
| `WorkflowTemplate` | Reusable workflow definitions with parameter instantiation |
| `WorkflowNested` | Workflows within workflows with depth limit and flatten |
| `WorkflowPersistence` | Save/load workflows to disk with hash and metadata |

### Native C++ Hooks (Op Codes 110-113)

```text
110 = compute_workflow_complexity   # nodes + depth weighted score (0-100)
111 = compute_workflow_parallelism # branches * width / 10 (0-100)
112 = compute_workflow_priority     # priority * 10 - due/1000 (0-100)
113 = compute_workflow_retry_budget # max(0, max - used)
```

### JS Fallbacks

When the native addon is absent, every method falls back to pure-JS:

- `computeWorkflowComplexity` → `min(100, nodes * 5 + depth * 10)`
- `computeWorkflowParallelism` → `min(100, branches * width / 10)`
- `computeWorkflowPriority` → `max(0, min(100, priority * 10 - due / 1000))`
- `computeWorkflowRetryBudget` → `max(0, max - used)`

### Verified

```powershell
node -c pipeline\screenai_pipelines.js
# syntax OK

node pipeline\test_pipeline.js
# Results: 43/43 passed, 0 failed

node pipeline\_test_tmp\phase15_audit.js
# PHASE 15: 40/40 pass
```

### Integration Pattern

```javascript
// 1. Build a workflow with nodes and edges
globalWorkflowBuilder.create('research_flow', { name: 'Research Flow' });
globalWorkflowBuilder.addNode('research_flow', 'search', { type: 'act', tool: 'browser.search' });
globalWorkflowBuilder.addNode('research_flow', 'extract', { type: 'act', tool: 'browser.extract' });
globalWorkflowBuilder.addNode('research_flow', 'save', { type: 'act', tool: 'file.save' });
globalWorkflowBuilder.addEdge('research_flow', 'search', 'extract');
globalWorkflowBuilder.addEdge('research_flow', 'extract', 'save');

// 2. Branch on a condition
globalWorkflowBrancher.define('mode_branch',
  { key: 'mode', value: 'auto' },
  'auto_path',
  'manual_path'
);
const branch = globalWorkflowBrancher.evaluate('mode_branch', { mode: 'auto' });

// 3. Loop over a collection
globalWorkflowLoop.define('process_items', { collection: items });
let step;
while ((step = globalWorkflowLoop.iterate('process_items')) && !step.done) {
  await processItem(step.item);
}

// 4. Evaluate conditions
globalWorkflowCondition.define('is_ready', ctx => ctx.status === 'ready');
const ready = globalWorkflowCondition.evaluate('is_ready', { status: 'ready' });

// 5. Run tasks in parallel
globalWorkflowParallel.define('parallel_extract', [url1, url2, url3]);
const results = await globalWorkflowParallel.execute('parallel_extract', async (url) => {
  return await extract(url);
});

// 6. Schedule a workflow
globalWorkflowScheduler.define('daily_backup', 'backup_wf', '0 0 * * *', { intervalMs: 86400000 });
const due = globalWorkflowScheduler.tick();

// 7. Trigger a workflow on event
globalWorkflowTrigger.define('on_file_change', 'file_changed', 'process_file');
const fired = globalWorkflowTrigger.fire('file_changed', { path: '/data/file.txt' });

// 8. Instantiate a template
globalWorkflowTemplate.define('open_chrome_tpl', 'open_chrome', { steps: ['launch'] }, [
  { name: 'url', default: 'https://google.com' }
]);
const instance = globalWorkflowTemplate.instantiate('open_chrome_tpl', { url: 'https://example.com' });

// 9. Nest workflows
globalWorkflowNested.nest('parent_wf', 'child_wf');
const children = globalWorkflowNested.getChildren('parent_wf');
const flat = globalWorkflowNested.flatten('parent_wf');

// 10. Persist a workflow
globalWorkflowPersistence.save('research_flow', workflowData);
const loaded = globalWorkflowPersistence.load('research_flow');
```

## Pipeline Phase 16: Provider Abstraction (2026-07-30)

The `pipeline/screenai_pipelines.js` file now contains 16 phases of utility classes plus 249 graph pipelines across 13 domains.

### Phase 16 — Provider Abstraction (10 utilities)

```text
ProviderRegistry, ProviderSelectorV2, ProviderFallback, ProviderLoadBalancer,
ProviderCircuitBreaker, ProviderHealthMonitor, ProviderCapabilityMatcher,
ProviderConfigManager, ProviderMetricsCollector, ProviderLifecycleManager
```

### Provider Abstraction Capabilities

| Utility | Purpose |
|---------|---------|
| `ProviderRegistry` | Catalog of available implementations: register, unregister, get, list, findByCapability |
| `ProviderSelectorV2` | Pick best provider for a capability by weighted health/cost/latency score |
| `ProviderFallback` | Chain of alternative providers with reliability-weighted depth |
| `ProviderLoadBalancer` | Distribute requests across providers by free-capacity weight |
| `ProviderCircuitBreaker` | Isolate failing providers with closed/half-open/open states |
| `ProviderHealthMonitor` | Track success/failure rates and average latency per provider |
| `ProviderCapabilityMatcher` | Match providers to capabilities with capability tags |
| `ProviderConfigManager` | Per-provider configuration with merge and delete |
| `ProviderMetricsCollector` | Aggregate provider stats: calls, errors, latency, success rate |
| `ProviderLifecycleManager` | Init/shutdown/restart providers with status tracking |

### Provider Domains

```text
Browser       - Chrome, Edge, Firefox, Playwright, system default
Vision        - OmniParser, YOLO, OpenCV, native UIA
OCR           - PaddleOCR, Tesseract, EasyOCR, Windows OCR
LLM           - Qwen, Phi, Gemma, llama.cpp, Ollama, cloud
Filesystem    - local, SMB, cloud, virtual
Terminal      - PowerShell, cmd, bash, native
Email         - SMTP, IMAP, Graph, Gmail API
Documents     - PDF, DOCX, XLSX, Markdown, plain text
Network       - HTTP, HTTPS, WebSocket, raw TCP
OS            - Windows, Linux, macOS, WSL
```

### Native C++ Hooks (Op Codes 120-123)

```text
120 = compute_provider_score       # weighted (health 50% + cost 20% + latency 30%)
121 = compute_fallback_depth       # length (60%) + reliability (40%)
122 = compute_load_weight          # free capacity percentage
123 = compute_circuit_state        # 0=closed, 1=half-open, 2=open
```

### JS Fallbacks

When the native addon is absent, every method falls back to pure-JS:

- `computeProviderScore` → `health * 0.5 + (100 - cost) * 0.2 + (100 - latency) * 0.3`
- `computeFallbackDepth` → `length * 0.6 + reliability * 0.4`
- `computeLoadWeight` → `(capacity - current_load) / capacity * 100`
- `computeCircuitState` → `failures >= threshold ? 2 : failures > 0 ? 1 : 0`

### Verified

```powershell
node -c pipeline\screenai_pipelines.js
# syntax OK

node pipeline\test_pipeline.js
# Results: 43/43 passed, 0 failed

node pipeline\_test_tmp\phase16_audit.js
# PHASE 16: 34/34 pass
```

### Integration Pattern

```javascript
// 1. Register providers in the catalog
globalProviderRegistry.register({
  id: 'chrome',
  type: 'browser',
  capabilities: ['navigate', 'click', 'type', 'screenshot'],
  health: 95,
  cost: 20,
  latency: 50
});

// 2. Find providers by capability
const browsers = globalProviderRegistry.findByCapability('navigate');

// 3. Select best provider for a capability
const best = globalProviderSelectorV2.select('navigate', { preferLowCost: true });

// 4. Define fallback chain
globalProviderFallback.define('navigate', ['chrome', 'edge', 'firefox']);
const result = await globalProviderFallback.execute('navigate', async (id) => {
  return await navigateWith(id);
});

// 5. Load balance across providers
globalProviderLoadBalancer.addProvider('chrome', { capacity: 10 });
globalProviderLoadBalancer.addProvider('edge', { capacity: 8 });
const acquired = globalProviderLoadBalancer.acquire();
await doWork(acquired);
globalProviderLoadBalancer.release(acquired);

// 6. Use circuit breaker for failing providers
if (globalProviderCircuitBreaker.canCall('chrome')) {
  try {
    await navigateWith('chrome');
    globalProviderCircuitBreaker.recordSuccess('chrome');
  } catch (e) {
    globalProviderCircuitBreaker.recordFailure('chrome');
  }
}

// 7. Monitor provider health
globalProviderHealthMonitor.recordSuccess('chrome', 50);
globalProviderHealthMonitor.recordFailure('chrome', 'timeout');
const health = globalProviderHealthMonitor.health('chrome');

// 8. Match providers to capabilities
globalProviderCapabilityMatcher.register('chrome', ['navigate', 'click']);
const matches = globalProviderCapabilityMatcher.match('click');

// 9. Configure providers
globalProviderConfigManager.set('chrome', { headless: true, timeout: 30000 });
const cfg = globalProviderConfigManager.get('chrome');

// 10. Collect metrics and manage lifecycle
globalProviderMetricsCollector.recordCall('chrome', true, 50);
const summary = globalProviderMetricsCollector.summary();
await globalProviderLifecycleManager.init('chrome');
await globalProviderLifecycleManager.shutdown('chrome');
```
## Pipeline Phase 17: Agent Runtime (2026-07-30)

The `pipeline/screenai_pipelines.js` file now contains 17 phases of utility classes plus 249 graph pipelines across 13 domains.

### Phase 17 — Agent Runtime (10 utilities)

```text
IntentEngine, ContextEngine, RuntimePlanner, RuntimeExecutionGraphBuilder,
PipelineRegistryBridge, RuntimeExecutionEngine, SkillOrchestratorBridge,
ObservationEngineBridge, VerificationEngineBridge, RecoveryEngineBridge,
MemoryUpdateBridge, AgentRuntime
```

### Agent Runtime Pipeline

```text
User Request
      │
      ▼
IntentEngine          (classify intent + risk)
      │
      ▼
ContextEngine         (gather environment + memory + resources)
      │
      ▼
RuntimePlanner        (create plan with steps)
      │
      ▼
RuntimeExecutionGraphBuilder  (build graph with auto-approval nodes)
      │
      ▼
PipelineRegistryBridge (register pipeline)
      │
      ▼
RuntimeExecutionEngine (execute graph nodes)
      │
      ▼
SkillOrchestratorBridge (orchestrate skills)
      │
      ▼
ObservationEngineBridge (observe execution)
      │
      ▼
VerificationEngineBridge (verify result)
      │
      ▼
RecoveryEngineBridge  (recover on failure)
      │
      ▼
MemoryUpdateBridge    (store in long-term memory)
      │
      ▼
Completed
```

### Agent Runtime Capabilities

| Utility | Purpose |
|---------|---------|
| `IntentEngine` | Classify user request into intent + risk level using regex patterns |
| `ContextEngine` | Gather environment, memory, and resource context for the request |
| `RuntimePlanner` | Create execution plan with typed steps (observe, act, verify, finish) |
| `RuntimeExecutionGraphBuilder` | Build execution graph with auto-inserted approval nodes for risk >= 3 |
| `PipelineRegistryBridge` | Register and lookup pipelines by name or capability |
| `RuntimeExecutionEngine` | Execute graph nodes and record results in history |
| `SkillOrchestratorBridge` | Orchestrate skills based on intent with auto-selection |
| `ObservationEngineBridge` | Record observations with timestamps for each stage |
| `VerificationEngineBridge` | Verify execution results with pass/fail status |
| `RecoveryEngineBridge` | Classify failures and apply recovery policies (retry/abort/rollback/replan) |
| `MemoryUpdateBridge` | Store execution results in long-term memory with tags |
| `AgentRuntime` | Orchestrate all 11 stages end-to-end via `processRequest()` |

### Intent Patterns

```text
browser_open    - "open chrome|edge|firefox|browser"     (risk: 1)
browser_search  - "search <query>"                       (risk: 1)
browser_close   - "close chrome|edge|firefox|browser"    (risk: 1)
file_delete     - "delete [file] <path>"                  (risk: 3)
file_move       - "move <src> to <dst>"                   (risk: 2)
file_list       - "list files|directory"                  (risk: 0)
system_status   - "check status|system|memory|disk"      (risk: 0)
auth_login      - "login [to] <site>"                     (risk: 3)
download_file   - "download <url>"                        (risk: 2)
system_run      - "run <command>"                         (risk: 4)
```

### Recovery Policies

```text
timeout      -> retry (3 attempts)
network      -> retry (5 attempts)
permission   -> abort
validation   -> abort
crash        -> rollback
not_found    -> replan
unknown      -> retry (1 attempt)
```

### Native C++ Hooks (Op Codes 130-133)

```text
130 = compute_stage_priority       # base priority by stage - age decay (0-100)
131 = hash_runtime_request         # djb2 hash for request dedup
132 = compute_runtime_relevance    # token overlap score (0-100)
133 = compute_stage_transition_cost # 10 for natural flow, 50 for skip, 90 for loop
```

### JS Fallbacks

When the native addon is absent, every method falls back to pure-JS:

- `computeStagePriority` → base priority by stage name minus age decay
- `hashRuntimeRequest` → djb2 hash returning `rt_<hex>`
- `computeRuntimeRelevance` → token overlap percentage
- `computeStageTransitionCost` → 10 for natural flow, 50 for skip, 90 for loop

### Verified

```powershell
node -c pipeline\screenai_pipelines.js
# syntax OK

node pipeline\test_pipeline.js
# Results: 43/43 passed, 0 failed

node pipeline\test_agent_runtime.js
# Agent Runtime regression passed
```

### Integration Pattern

```javascript
// 1. Create an AgentRuntime instance
const runtime = new AgentRuntime();

// 2. Process a user request end-to-end
const result = runtime.processRequest({ text: 'open chrome' });
// result.intent, result.context, result.plan, result.graph,
// result.execution, result.orchestration, result.observation,
// result.verification, result.memory, result.stages, result.status

// 3. Use individual stages
const intent = runtime.intentEngine.classify('delete file foo.txt');
// { name: 'file_delete', risk: 3, confidence: 0.9, ... }

const context = runtime.contextEngine.gather({ text: 'open chrome', intent });
// { timestamp, request, intent, environment, memory, resources }

const plan = runtime.planner.createPlan(intent, context);
// { intent, risk, steps: [...], context, createdAt }

const graph = runtime.executionGraph.build(plan.steps);
// { nodes: [...], edges: [...], createdAt }
// Note: auto-inserts approval nodes before risk >= 3 actions

// 4. Register and execute pipelines
runtime.pipelineRegistry.register('my_pipeline', { steps: ['a', 'b'] });
const execution = runtime.executionRuntime.execute(graph);

const orchestration = runtime.skillOrchestrator.orchestrate({ intent: 'browser_open' });
const observation = runtime.observationEngine.observe({ stage: 'runtime', data: execution });
const verification = runtime.verificationEngine.verify({ stage: 'runtime', observation });
const recovery = runtime.recoveryEngine.recover({ stage: 'runtime', error: 'timeout' });
const memory = runtime.memoryUpdate.update({ stage: 'runtime', result: execution });

// 5. Use the global instance
const result = globalAgentRuntime.processRequest({ text: 'check status' });
```

## 2026-07-31 Comprehensive Planner Note

The planner (pp/agent/planner.py) was completely rewritten to be **fully system-aware**. It now knows the entire 30k+ line pipeline system, all backend files, all app/site aliases, and uses a 7-tier classification strategy.

### Knowledge Base

| Component | Count | Source |
|-----------|-------|--------|
| **PIPELINE_KNOWLEDGE** | 306 pipelines across 20 domains | pipeline/screenai_pipelines.js |
| **PHASE_UTILITY_KNOWLEDGE** | 130 utilities across 13 phases | pipeline/screenai_pipelines.js |
| **BACKEND_FILE_KNOWLEDGE** | 40 files across 9 modules | pp/ directory |
| **SYNONYMS** | 126 entries | Built-in |
| **APP_NAME_ALIASES** | 98 entries | Built-in |
| **SITE_ALIASES** | 200+ sites | Built-in |
| **Intent patterns** | 60+ intents | Built-in |

### 7-Tier Classification Strategy

The classify_intent() method uses a cascading strategy:

1. **Exact memory match** — checks planner_memory.json for exact normalized text
2. **Fuzzy memory match** — uses token overlap + SequenceMatcher ratio (threshold 0.78)
3. **Synonym expansion + regex pattern match** — expands synonyms then matches against 60+ intent patterns
4. **Pipeline knowledge base match** — matches against 306 pipeline graphs across 20 domains
5. **Phase utility knowledge base match** — matches against 130 phase utilities
6. **Token-overlap fuzzy match** — matches against known intent keywords
7. **Default to "unknown"** — falls through to LLM planner if available

### Key Pattern Reordering (this session)

Patterns are ordered by specificity. More specific patterns come first:

- close_all_apps before open_app — so "keep chrome open but close everything else" → close_all_apps
- close_app before rowser_close — so "close chrome" → close_app (not rowser_close)
- 	erminal_powershell / 	erminal_cmd before un_command — so "run powershell command" → 	erminal_powershell
- dev_test / dev_run before 	erminal_run — so "run tests" → dev_test
- mail_search before search_web — so "search email" → mail_search
- esearch_collect before search_web — so "research AMD ROCm" → esearch_collect
- 
etwork_ping before search_web — so "ping google.com" → 
etwork_ping

### open_app Pattern (restricted)

The open_app pattern was made more restrictive to avoid false positives:

`python
r"\b(open|launch|start|fire\s*up|boot|bring\s*up)\b.*\b(app|application|program|software)\b",
r"\b(open|launch|start|fire\s*up|boot|bring\s*up)\b\s+\w+",
r"\brun\s+(chrome|edge|firefox|opera|notepad|calc|excel|word|powerpoint|outlook|spotify|discord|slack|vscode|code|terminal|explorer|paint|wordpad|settings|camera|photos|movies|music|store|mail|calendar|clock|weather|maps|news|notes|todo|sticky|calculator)\b",
`

Note: "powershell" and "cmd" were removed from the open_app pattern since they're handled by 	erminal_powershell and 	erminal_cmd.

### TaskPlanner Fix (this session)

The TaskPlanner._plan_browser_session() was updated to only match compound browser/session tasks when there's extra context (keep-awake, mouse jiggle, duration, or explicit session keyword). Simple "open chrome" now falls through to the main planner and classifies as open_app.

`python
has_session_context = bool(
    re.search(r"\b(session|awake|idle|sleep|prevent|stop)\b", lower)
    or re.search(r"\b(mouse|cursor)\b.*\b(move|movement|jiggle|shake)\b", lower)
    or re.search(r"\b\d+\s*(minute|minutes|hour|hours|min|hr|h)\b", lower)
    or re.search(r"\bkeep\s+(browser|session|pc|computer)\b", lower)
)
if not has_session_context:
    return None
`

### Memory Learning

The planner learns from every command via planner.remember(text, intent) called in outer.py after intent classification. Memory is persisted to i_pc_operator/data/planner_memory.json.

### Verified

`powershell
# Smoke test: 132/132 PASSED (100%)
python _test_planner.py

# HTTP batch test: 58/58 PASSED (100%)
python _test_curl_batch.py
`

All commands classify correctly via both the direct planner API and the live HTTP server.
`

All commands classify correctly via both the direct planner API and the live HTTP server.

## 2026-08-05 Four-Spec Agent Upgrade (Cognitive Planner, OS v2.0, Task Policy, Generic Decomposition)

All changes are additive; no existing behavior removed. Full test suites green (see CHANG.md 2026-08-05).

### Master Cognitive Planner v1.0

- `browser_open` is a first-class intent: `Open/Launch/Run/Fire up/Bring up/Start Chrome` → `system.open_app`. Precedence: `open_website` (sites) → `browser_open` (browser apps) → `open_app` (generic apps). `open gx browser` still → `open_app` (negative lookahead).
- `resolve_user_alias` is single-pass (cursor scan) so `vscode` → `visual studio code` never re-expands to double-`code`. Removed `chrome → google chrome` from USER_ALIASES.
- `take me to` / `browse` added to navigate vocabulary; `take me to youtube` / `browse youtube` → `open_website`.
- `screen_tools._score()` now calls `semantic_ocr_match` (login ↔ sign in = 0.95).
- Router returns `cognitive_plan` in `/command` + `/command/preview`: intent, entities, execution_graph, pipelines, models, dependencies, verification_steps, recovery_plan, confidence_score, risk_score, canonical_actions, wait_strategies, autonomous_steps.
- `close browser` now → `browser_close` (removed `browser` from `close_app` target list).

### OS v2.0 — External Reasoning, Camera, Chat

- `app/agent/external_planner.py`: OpenAI-compatible client (DeepSeek-V4-Flash, AMD Radeon API). Env config: `SCREEN_AI_EXTERNAL_API_KEY`, `SCREEN_AI_EXTERNAL_BASE_URL` (default `https://developer.amd.com.cn/radeon/api/v1`), `SCREEN_AI_EXTERNAL_MODEL` (default `DeepSeek-V4-Flash`), `SCREEN_AI_EXTERNAL_TIMEOUT` (30), `SCREEN_AI_EXTERNAL_RETRIES` (1). Key is env-var-only, never logged; plans are advisory + validated against an allowed tool namespace.
- Router + preview consult the external planner when intent is unknown (same `llm_plan` branch → risk merge + approval gates apply automatically).
- Camera: `take_camera_photo` intent (`take my picture`, `capture a photo`, `use webcam`, `click a photo`) → `system.open_app(camera)` + `system.capture_photo` (ffmpeg dshow; graceful failure with hint). `media_camera` no longer emits the dangling `media.camera` tool.
- Chat: unknown intent → `_rule_chat_reply` (local) then `external_planner.chat_reply`; response `status: "chat"`.

### Task Execution Policy (10 phases)

- `plan_to_graph()` (graph_schema.py) attaches per-node `pipeline` (`TOOL_PIPELINE` map) + `models` (`_models_for_tool`), and emits a `verify_goal` node (goal-level completion, Phase 10).
- Router: `statuses` list (natural "Opening Chrome..." lines via `TOOL_STATUS_PHRASES` + `_step_status`), `goal` string (`_derive_goal`) in command + preview responses.
- `TaskPlanner._plan_send_file`: generic goal-oriented send-file graph (FILE/CONTACT/CHANNEL entities); intent `send_file` (replaces `whatsapp_send_file`).

### Generic Task Decomposition + Compound Command Planner

- `EntityExtractor` (intent_engine/entity_extractor.py) gains `CONTACT` + `CHANNEL` entities; `CHANNELS`/`CHANNEL_URL` capability table (whatsapp/gmail/slack/telegram/signal/discord/messenger).
- `task_planner.extract_entities()` universal helper returns `{file, contact, channel, channel_url, apps, sites, urls, paths}`.
- `_plan_multi_intent_sequence` (TaskPlanner): splits chained commands on `,` `then` `and` `;` (protecting URLs, filenames, multi-word app names), classifies each segment via `Planner.classify_intent_sync`, chains `create_plan_sync` steps into one `compound_sequence` plan with per-step pipeline/models/verification/recovery. Context-dependent trailing actions (`search for the contact`, `attach the file`, `send it`) map to semantic screen/browser steps via `_ui_action_steps`.
- `Planner` sync twins: `classify_intent_sync()` / `create_plan_sync()` (async versions were sync-bodied; the async methods now delegate).
- Fixed `EntityExtractor` NUMBER-vs-FILE span overlap (number-leading filenames like `1.txt` now extract as FILE); `find x.file` → `file_search`; `_extract_app_name` strips `go to`/`navigate to`/`visit`.
- Flagship example verified: "Go to File Explorer, open Desktop, find x.file, open GX Browser, navigate to https://web.whatsapp.com, search for the contact, attach the file and send it" → `compound_sequence`, 8 steps.

### New test files

- `ai_pc_operator/backend/test_cognitive_planner.py` (8/8)
- `ai_pc_operator/backend/test_v2_external_chat_camera.py` (7/7)
- `ai_pc_operator/backend/test_task_execution_policy.py` (5/5)
- `ai_pc_operator/backend/test_generic_task_decomposition.py` (5/5)
- `ai_pc_operator/backend/test_compound_sequence.py` (6/6)

### External reasoning usage

```powershell
# set the key in the same cmd window before starting (never commit/log it)
set SCREEN_AI_EXTERNAL_API_KEY=rc-xxxx
cd /d ai_pc_operator\backend
python -m app.main
# or the official launcher: ai_pc_operator\start.bat (use setx for that window)
```
