# Screen-AI: Complete Relation Map

> Auto-generated analysis of all files, functions, modules, and their relationships.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [System Architecture Diagram](#system-architecture-diagram)
3. [File Tree](#file-tree)
4. [Module Dependency Graph](#module-dependency-graph)
5. [Module-by-Module Analysis](#module-by-module-analysis)
6. [Data Flow: Command Lifecycle](#data-flow-command-lifecycle)
7. [Data Flow: Device Pairing](#data-flow-device-pairing)
8. [Data Flow: Screen Perception](#data-flow-screen-perception)
9. [Data Flow: Runtime Engine](#data-flow-runtime-engine)
10. [External Dependencies Map](#external-dependencies-map)
11. [Database Schema & Access Patterns](#database-schema--access-patterns)
12. [File Data Flow (I/O Paths)](#file-data-flow-io-paths)
13. [Cross-Cutting Concerns](#cross-cutting-concerns)
14. [Test Coverage Map](#test-coverage-map)
15. [API Endpoint Map](#api-endpoint-map)

---

## 1. Project Overview

Screen-AI is a **fully local/offline PC operator AI** with full system access, controlled by phone and PC. The phone is the command + approval + unlock device.

**Architecture pattern**: FastAPI server → Agent Router → Tool Execution → Result

**Key subsystems**:
- **Agent Brain** (intent classification, risk assessment, planning, execution)
- **Tool Layer** (system, file, browser, screen, auth, download)
- **Security Layer** (risk, permissions, vault, pairing)
- **Runtime Engine** (RAM-aware model loading, strategy, telemetry)
- **Frontend** (PWA remote control, offline-capable)
- **Screen Scanner** (UIA + OpenCV perception)
- **Native C Core** (high-performance fuzzy matching, hashing)

---

## 2. System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MOBILE / PC BROWSER                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │ index.html│  │ app.js   │  │ worker.js│  │ sw.js (PWA/offline)│  │
│  └────┬─────┘  └────┬─────┘  └──────────┘  └────────────────────┘  │
│       │  HTTP/WS    │                                               │
└───────┼─────────────┼───────────────────────────────────────────────┘
        │             │
┌───────▼─────────────▼───────────────────────────────────────────────┐
│                     FastAPI SERVER (main.py)                        │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    AGENT LAYER                              │    │
│  │  router.py → planner.py → task_planner.py → llm_planner.py │    │
│  │       │                                    (prompts.py)     │    │
│  │       ▼                                                    │    │
│  │  memory.py (short-term + long-term)                        │    │
│  └───────┬────────────────────────────────────────────────────┘    │
│          │                                                         │
│  ┌───────▼─────────────────────────────────────────────────────┐    │
│  │                  SECURITY LAYER                             │    │
│  │  risk.py → permissions.py → approval/manager.py             │    │
│  │  vault.py (AES-256-GCM + Argon2id)                         │    │
│  │  pairing.py / pairing_v2.py (QR + trust + rotation)        │    │
│  └───────┬────────────────────────────────────────────────────┘    │
│          │                                                         │
│  ┌───────▼─────────────────────────────────────────────────────┐    │
│  │                    TOOL LAYER                               │    │
│  │  system_tools.py  file_tools.py  browser_tools.py          │    │
│  │  screen_tools.py  auth_tools.py   download_tools.py        │    │
│  └───────┬────────────────────────────────────────────────────┘    │
│          │                                                         │
│  ┌───────▼─────────────────────────────────────────────────────┐    │
│  │                  RUNTIME ENGINE                             │    │
│  │  strategy.py → telemetry.py                                │    │
│  │  resource_budget.py → tier_manager.py → ssd_tier.py        │    │
│  │  model_registry.py → model_loaders.py → artifact_store.py  │    │
│  │  native_bridge.py → screenai_core.c (native)               │    │
│  │  heatmap.py  screen_cache.py  io_pool.py                   │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │                  DATA LAYER                                │     │
│  │  database.py (SQLite)  models.py (Pydantic)               │     │
│  │  redactor.py (log sanitization)                           │     │
│  └────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
        │
┌───────▼───────────────────────────────────────────────────────────┐
│              SCREEN ELEMENT SCANNER (external)                    │
│  scan_screen.py → uia_scan.ps1 (PowerShell UIA)                  │
│  scan_screen.py → OpenCV (visual box detection)                  │
│  scan_screen.py → pyautogui (screenshot + click)                 │
└───────────────────────────────────────────────────────────────────┘
```

---

## 3. File Tree

```
Screen-AI/
├── ai_pc_operator/
│   ├── README.md                          # Project documentation
│   ├── PROJECT_SUMMARY.md                 # Build summary
│   ├── start.bat / start.sh              # Launch scripts
│   ├── build.bat                          # Native C build (Windows)
│   ├── build_unix.sh.cmd                  # Native C build (Linux/Mac)
│   ├── requirements.txt                   # Python dependencies
│   │
│   ├── backend/
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   ├── main.py                    # FastAPI entry point + REST endpoints
│   │   │   │
│   │   │   ├── agent/                     # ── AGENT BRAIN ──
│   │   │   │   ├── __init__.py
│   │   │   │   ├── router.py              # Core command pipeline (classify→risk→plan→execute)
│   │   │   │   ├── planner.py             # Rule-based intent classification + action planning
│   │   │   │   ├── llm_planner.py         # LLM-assisted planning (uses prompts.py)
│   │   │   │   ├── task_planner.py        # Multi-step desktop task decomposition
│   │   │   │   ├── memory.py              # Short-term (last 100) + long-term (SQLite) memory
│   │   │   │   └── prompts.py             # System + user prompt templates for LLM
│   │   │   │
│   │   │   ├── approvals/                 # ── APPROVAL SYSTEM ──
│   │   │   │   ├── __init__.py
│   │   │   │   └── manager.py             # Approval requests, polls, approve/reject
│   │   │   │
│   │   │   ├── db/                        # ── DATA LAYER ──
│   │   │   │   ├── __init__.py
│   │   │   │   ├── database.py            # SQLite setup, migrations, connection pool
│   │   │   │   └── models.py              # Pydantic models (Command, Approval, Action, Device, etc.)
│   │   │   │
│   │   │   ├── logs/                      # ── LOGGING ──
│   │   │   │   ├── __init__.py
│   │   │   │   └── redactor.py            # Regex-based PII/secret redaction
│   │   │   │
│   │   │   ├── runtime/                   # ── RUNTIME ENGINE ──
│   │   │   │   ├── __init__.py
│   │   │   │   ├── strategy.py            # CircuitBreaker + IntentMemory + AdaptiveRetry + Prefetch
│   │   │   │   ├── telemetry.py           # Per-command tracing, tool latency, live dashboard
│   │   │   │   ├── resource_budget.py     # RAM measurement → tier mode decision
│   │   │   │   ├── tier_manager.py        # Intent + RAM → allowed models + prefetch list
│   │   │   │   ├── ssd_tier.py            # Model placement across RAM/SSD tiers
│   │   │   │   ├── model_registry.py      # Lazy model loading with TTL + prefetch
│   │   │   │   ├── model_loaders.py       # OCR, detector, nexa, vault, browser loaders
│   │   │   │   ├── artifact_store.py      # File-system model artifact discovery
│   │   │   │   ├── native_bridge.py       # ctypes bridge → screenai_core.c
│   │   │   │   ├── heatmap.py             # Intent→tool frequency learning
│   │   │   │   ├── screen_cache.py        # JSON cache for UI maps, OCR, detector results
│   │   │   │   └── io_pool.py             # ThreadPoolExecutor for blocking I/O
│   │   │   │
│   │   │   ├── security/                  # ── SECURITY ──
│   │   │   │   ├── __init__.py
│   │   │   │   ├── risk.py                # Regex-based risk classifier (0-5 scale)
│   │   │   │   ├── permissions.py         # Per-intent risk→approval mapping
│   │   │   │   ├── vault.py               # AES-256-GCM + Argon2id password vault
│   │   │   │   ├── pairing.py             # 6-digit code device pairing
│   │   │   │   └── pairing_v2.py          # QR + X25519 + trust + rotation + biometric
│   │   │   │
│   │   │   └── tools/                     # ── TOOL LAYER ──
│   │   │       ├── __init__.py
│   │   │       ├── system_tools.py        # Status, disk, RAM, processes, open_app, keep_awake
│   │   │       ├── file_tools.py          # List, scan, read, move, copy, quarantine, restore
│   │   │       ├── browser_tools.py       # Playwright: open, search, click, type, download, research
│   │   │       ├── screen_tools.py        # UIA+OpenCV scan, click_text (uses scan_screen.py)
│   │   │       ├── auth_tools.py          # Vault unlock, password_login, passkey_login
│   │   │       └── download_tools.py      # Safe download with hash + danger check
│   │   │
│   │   ├── native/                        # ── NATIVE C CORE ──
│   │   │   ├── screenai_core.c            # Levenshtein, fuzzy_score, xxHash64, validate_bounds
│   │   │   └── screenai_core.h            # C API header
│   │   │
│   │   ├── scripts/                       # ── SCRIPTS ──
│   │   │   ├── download_models.py
│   │   │   ├── start.py
│   │   │   ├── start_https.py
│   │   │   └── setup.py
│   │   │
│   │   ├── test_basic.py                  # Core functionality tests
│   │   ├── test_login_v2.py               # Pairing V2 + vault tests
│   │   └── test_strategy.py               # Strategy engine tests
│   │
│   ├── frontend/                          # ── MOBILE REMOTE UI ──
│   │   ├── index.html                     # Main control panel
│   │   ├── app.js                         # Frontend logic + PWA registration
│   │   ├── styles.css                     # Styles
│   │   ├── sw.js                          # Service Worker (offline + background sync)
│   │   ├── worker.js                      # Web Worker (fuzzy search, crypto, IndexedDB)
│   │   ├── login.html                     # Device login page
│   │   ├── pair.html                      # Device pairing page
│   │   ├── offline.html                   # Offline fallback page
│   │   └── manifest.json                  # PWA manifest
│   │
│   └── data/                              # ── PERSISTENT DATA ──
│       ├── memory/                        # strategy_state.json, tool_heatmap.json, etc.
│       ├── models/                        # ONNX/GGUF model artifacts
│       ├── quarantine/                    # Reversible file quarantine
│       ├── downloads/                     # Downloaded files
│       ├── research/                      # Research reports
│       ├── telemetry.db                   # Telemetry SQLite
│       └── agent.log                      # Application log
│
├── screen_element_scanner/                # ── SCREEN PERCEPTION (external) ──
│   ├── scan_screen.py                     # Core: capture_screen, run_uia_scan, detect_visual_boxes
│   └── uia_scan.ps1                       # PowerShell UIA Automation tree scanner
│
└── hackathon_ui_operator_distill/         # ── MODEL TRAINING PIPELINE (separate) ──
    └── data/                              # Trained artifacts consumed by artifact_store
```

---

## 4. Module Dependency Graph

### Import Relationships (A → B means A imports B)

```
main.py
  → agent.router.Router
  → approvals.manager.ApprovalManager
  → security.pairing.PairingManager
  → security.pairing_v2.PairingManagerV2
  → db.database.init_db, db_session
  → logs.redactor.LogRedactor
  → runtime.strategy.StrategyRouter
  → runtime.telemetry.Telemetry
  → runtime.model_registry.ModelRegistry
  → runtime.artifact_store.ArtifactStore
  → runtime.model_loaders (all loader functions)
  → runtime.resource_budget.ResourceBudget
  → runtime.io_pool.IOPool
  → runtime.ssd_tier.SSDTierManager
  → runtime.heatmap.ToolHeatMap
  → runtime.screen_cache.ScreenCache
  → runtime.tier_manager.AgentTierManager

agent/router.py
  → agent.planner.Planner
  → agent.task_planner.TaskPlanner
  → agent.llm_planner.llm_plan
  → agent.memory.Memory
  → security.risk.RiskClassifier
  → security.permissions.PermissionEngine
  → approvals.manager.ApprovalManager
  → tools.system_tools.SystemTools
  → tools.file_tools.FileTools
  → tools.browser_tools.BrowserTools
  → tools.screen_tools.ScreenTools
  → tools.auth_tools.AuthTools
  → tools.download_tools.DownloadTools
  → runtime.strategy.StrategyRouter
  → runtime.telemetry.Telemetry
  → logs.redactor.LogRedactor

agent/llm_planner.py
  → agent.prompts.SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

agent/task_planner.py
  (standalone — regex-based decomposition)

agent/memory.py
  → db.database.db_session

agent/planner.py
  (standalone — regex-based intent classification)

security/risk.py
  (standalone — regex pattern matching)

security/permissions.py
  (standalone — dict-based mapping)

security/vault.py
  → db.database.db_session
  → cryptography (AES-256-GCM, Argon2id/PBKDF2)

security/pairing.py
  → db.database.db_session

security/pairing_v2.py
  → db.database.db_session
  → cryptography (X25519, AESGCM)

approvals/manager.py
  → db.database.db_session

tools/file_tools.py
  → db.database.db_session

tools/screen_tools.py
  → screen_element_scanner.scan_screen (external module)
  → pyautogui

tools/browser_tools.py
  → playwright (optional)
  → webbrowser (fallback)

tools/auth_tools.py
  → security.vault.PasswordVault
  → tools.browser_tools.BrowserTools (lazy import)

tools/download_tools.py
  (standalone — urllib.request)

tools/system_tools.py
  → psutil
  → ctypes (Windows keep_awake)

db/database.py
  → aiosqlite

runtime/native_bridge.py
  → ctypes → native/screenai_core.c (.dll/.so/.dylib)
  (pure-Python fallbacks when C unavailable)

runtime/model_registry.py
  → runtime.io_pool.IOPool
  → runtime.resource_budget.ResourceBudget
  → runtime.ssd_tier.SSDTierManager

runtime/model_loaders.py
  → runtime.artifact_store.ArtifactStore

runtime/ssd_tier.py
  → runtime.artifact_store.ArtifactStore
  → runtime.resource_budget.RuntimeBudget

runtime/tier_manager.py
  → runtime.resource_budget.RuntimeBudget

runtime/strategy.py
  (self-contained — CircuitBreaker, IntentMemory, Prefetcher, AdaptiveRetry)

runtime/telemetry.py
  (self-contained — writes to telemetry.db + telemetry_live.json)

runtime/heatmap.py
  (self-contained — reads/writes tool_heatmap.json)

runtime/screen_cache.py
  (self-contained — JSON file cache)

runtime/io_pool.py
  (self-contained — ThreadPoolExecutor)

runtime/artifact_store.py
  (self-contained — filesystem scanner)

runtime/resource_budget.py
  → psutil (optional)

logs/redactor.py
  (self-contained — regex patterns)

frontend/app.js
  → frontend/worker.js (Web Worker)
  → frontend/sw.js (Service Worker registration)

frontend/sw.js
  → frontend/offline.html (fallback)
```

---

## 5. Module-by-Module Analysis

### 5.1 AGENT BRAIN

| File | Class/Functions | Purpose | Key Dependencies |
|------|----------------|---------|------------------|
| `router.py` | `Router` | Core pipeline: classify→risk→plan→approve→execute→respond | All tools, planner, risk, permissions, approvals, memory, strategy, telemetry |
| `planner.py` | `Planner` | Rule-based intent classification (regex patterns → intent + risk + tool plan) | None (standalone) |
| `llm_planner.py` | `llm_plan()` | LLM-assisted planning using prompt templates | `prompts.py` |
| `task_planner.py` | `TaskPlanner` | Multi-step desktop command decomposition (regex) | None (standalone) |
| `memory.py` | `Memory` | Short-term (list, last 100) + long-term (SQLite) command memory | `db.database` |
| `prompts.py` | `SYSTEM_PROMPT`, `USER_PROMPT_TEMPLATE` | LLM prompt templates | None (constants) |

**Router class methods**: `process_command()`, `preview_plan()`, `_execute_tool()`, `_write_plan_cache()`, `_prefetch_hot_tools()`

### 5.2 TOOL LAYER

| File | Class | Methods | External Deps |
|------|-------|---------|---------------|
| `system_tools.py` | `SystemTools` | `status()`, `disk_usage()`, `ram_usage()`, `processes()`, `open_app()`, `kill_process()`, `network_status()`, `open_settings()`, `keep_awake()`, `run_command()` | `psutil`, `ctypes.windll` |
| `file_tools.py` | `FileTools` | `list()`, `scan()`, `read()`, `move()`, `copy()`, `quarantine()`, `restore()`, `delete_permanent()`, `list_quarantine()` | `db.database` (quarantine) |
| `browser_tools.py` | `BrowserTools` | `open()`, `search()`, `click()`, `type()`, `read()`, `download()`, `research_collect()`, `close()`, `prepare()` | `playwright` (optional), `webbrowser` (fallback) |
| `screen_tools.py` | `ScreenTools` | `scan()`, `click_text()` | `scan_screen` (external), `pyautogui` |
| `auth_tools.py` | `AuthTools` | `vault_unlock()`, `vault_lock()`, `vault_add()`, `vault_get()`, `vault_list()`, `password_login()`, `passkey_login()` | `security.vault`, `browser_tools` (lazy) |
| `download_tools.py` | `DownloadTools` | `download_file()`, `list_downloads()` | `urllib.request` |

### 5.3 SECURITY LAYER

| File | Class | Purpose | Methods |
|------|-------|---------|---------|
| `risk.py` | `RiskClassifier` | Regex-based risk scoring (0-5) from command text | `classify(text) → (risk_level, matched_keywords)` |
| `permissions.py` | `PermissionEngine` | Maps intent+risk → approval requirement | `needs_approval(intent, risk_level) → bool` |
| `vault.py` | `PasswordVault` | AES-256-GCM encrypted credential storage with Argon2id KDF | `unlock()`, `lock()`, `add_credential()`, `get_credential()`, `list_sites()` |
| `pairing.py` | `PairingManager` | 6-digit code device pairing + token management | `generate_code()`, `pair_device()`, `verify_device()`, `revoke_device()` |
| `pairing_v2.py` | `PairingManagerV2` | QR + X25519 key exchange + device trust + token rotation + biometric challenge | `create_qr_pairing()`, `complete_qr_pairing()`, `trust_device()`, `auto_repair_trusted()`, `rotate_token()`, `create_biometric_challenge()` |

### 5.4 RUNTIME ENGINE

| File | Class/Functions | Purpose | Persistence |
|------|----------------|---------|-------------|
| `strategy.py` | `CircuitBreaker`, `IntentMemory`, `SpeculativePrefetcher`, `AdaptiveRetry`, `StrategyRouter` | Adaptive command routing with learning | `strategy_state.json` |
| `telemetry.py` | `Telemetry`, `CommandTrace`, `StepTrace` | Per-command tracing, tool latency, live dashboard | `telemetry.db` + `telemetry_live.json` |
| `resource_budget.py` | `ResourceBudget`, `RuntimeBudget`, `MemorySnapshot` | RAM measurement → tier mode (balanced/perception-only/ocr-only/tier0) | None (runtime) |
| `tier_manager.py` | `AgentTierManager`, `TierDecision` | Intent + RAM budget → allowed models + prefetch list | None (runtime) |
| `ssd_tier.py` | `SSDTierManager`, `SSDTierPlan`, `ModelPlacement` | Model placement across RAM/SSD tiers | `model_usage.json` |
| `model_registry.py` | `ModelRegistry`, `ModelSpec`, `LoadedModel` | Lazy model loading with TTL + prefetch | None (runtime) |
| `model_loaders.py` | `ocr_mobile_loader()`, `ui_detector_loader()`, `qwen_gguf_loader()`, `vault_crypto_loader()`, `browser_warmup_loader()` | Factory functions for model loading | None |
| `artifact_store.py` | `ArtifactStore`, `Artifact` | Filesystem model artifact discovery | None (filesystem scan) |
| `native_bridge.py` | `levenshtein()`, `fuzzy_score()`, `xxhash64()`, `rolling_hash()`, `validate_bounds()`, `rank_elements()` | ctypes bridge to C core with pure-Python fallbacks | `native/screenai_core.c` |
| `heatmap.py` | `ToolHeatMap` | Intent→tool frequency learning | `tool_heatmap.json` |
| `screen_cache.py` | `ScreenCache` | JSON cache for UI maps, OCR, detector results | `.screen_ai_cache/` directory |
| `io_pool.py` | `IOPool` | Shared ThreadPoolExecutor for blocking I/O | None |

### 5.5 DATA LAYER

| File | Class/Functions | Purpose |
|------|----------------|---------|
| `database.py` | `init_db()`, `db_session()` | SQLite setup, async connection pool, schema migrations |
| `models.py` | `Command`, `Approval`, `Action`, `Device`, `VaultEntry`, `QuarantineEntry` | Pydantic models for DB entities |
| `redactor.py` | `LogRedactor` | Regex-based PII/secret redaction (passwords, tokens, CC, SSN) |

### 5.6 NATIVE C CORE

| File | Functions | Purpose |
|------|-----------|---------|
| `screenai_core.h` | Header declarations | C API for all native functions |
| `screenai_core.c` | `screenai_levenshtein()`, `screenai_fuzzy_score()`, `screenai_strcasestr()`, `screenai_rank_elements()`, `screenai_keyword_prefilter()`, `screenai_xxhash64()`, `screenai_rolling_hash()`, `screenai_validate_bounds()` | Zero-allocation hot-path algorithms |

### 5.7 SCREEN SCANNER (External)

| File | Functions | Purpose |
|------|-----------|---------|
| `scan_screen.py` | `capture_screen()`, `run_uia_scan()`, `detect_visual_boxes()`, `actionable_elements()`, `valid_bounds()`, `draw_overlay()`, `short_action_report()` | UIA + OpenCV screen perception |
| `uia_scan.ps1` | PowerShell script | Windows UIA Automation tree walker |

### 5.8 FRONTEND

| File | Purpose |
|------|---------|
| `index.html` | Main remote control UI (command input, approval cards, status dashboard) |
| `app.js` | Frontend logic: WebSocket/HTTP communication, PWA registration, IndexedDB, offline queuing |
| `styles.css` | UI styles |
| `sw.js` | Service Worker: network-first for API, cache-first for assets, background sync |
| `worker.js` | Web Worker: fuzzy search, history filtering, crypto (PBKDF2, AES-GCM, SHA-256), IndexedDB |
| `login.html` | Device login page |
| `pair.html` | Device pairing page |
| `offline.html` | Offline fallback page |
| `manifest.json` | PWA manifest |

---

## 6. Data Flow: Command Lifecycle

```
User types command on phone/PC
         │
         ▼
┌─ main.py: POST /command ─────────────────────────────────┐
│  1. Store command in DB (pending)                         │
│  2. redactor.redact() → sanitize input for logging       │
│  3. router.process_command(text, device_id)              │
│     │                                                     │
│     ├─ Step 1: _classify_intent(text)                     │
│     │   ├─ Try task_planner.decompose() for multi-step   │
│     │   ├─ Try planner.classify(text) for rule-based     │
│     │   └─ Fallback: llm_planner.llm_plan(text) if LLM   │
│     │                                                     │
│     ├─ Step 2: _assess_risk(intent, text)                 │
│     │   ├─ risk.classify(text) → risk_level              │
│     │   └─ permissions.needs_approval(intent, risk)      │
│     │                                                     │
│     ├─ Step 3: _plan_actions(intent, text)                │
│     │   ├─ planner.plan(intent, text) → tool_steps       │
│     │   ├─ heatmap.hot_tools(intent) → prefer known paths│
│     │   └─ strategy.get_prefetch_list(intent) → warm up  │
│     │                                                     │
│     ├─ Step 4: If needs_approval:                         │
│     │   ├─ approval_manager.create_approval_request()     │
│     │   ├─ Wait for phone approval (poll WebSocket)       │
│     │   └─ If rejected → return rejection                 │
│     │                                                     │
│     ├─ Step 5: _execute_plan(steps)                       │
│     │   ├─ For each step: strategy.execute_with_strategy()│
│     │   │   ├─ CircuitBreaker.is_available(tool)          │
│     │   │   ├─ execute_fn(tool_name, args)                │
│     │   │   │   └─ Dispatch to system/file/browser/      │
│     │   │   │      screen/auth/download tool              │
│     │   │   ├─ Record success/failure                     │
│     │   │   └─ AdaptiveRetry on transient failures        │
│     │   └─ telemetry.record_tool_call() for each          │
│     │                                                     │
│     └─ Step 6: Return result                              │
│         ├─ memory.add_to_history()                        │
│         ├─ telemetry._record_completion()                 │
│         └─ Update DB status (completed/error)             │
│                                                             │
└───────────────────────────────────────────────────────────┘
         │
         ▼
   Response → phone/PC frontend
```

---

## 7. Data Flow: Device Pairing

```
Phone opens /pair page
         │
         ▼
┌─ Pairing V2 Flow (primary) ──────────────────────────────┐
│  1. Phone → GET /pair/qr/create                          │
│     └─ pairing_v2.create_qr_pairing()                    │
│        ├─ Generate X25519 keypair                        │
│        ├─ Build QR payload (pairing_id, public_key, sig) │
│        └─ Store in DB + memory                           │
│                                                             │
│  2. Phone scans QR → sends POST /pair/qr/complete        │
│     └─ pairing_v2.complete_qr_pairing()                  │
│        ├─ Verify pairing session (not expired, not used) │
│        ├─ Derive X25519 shared secret                    │
│        ├─ AES-GCM encrypt session token                  │
│        ├─ Store device in DB (token_hash, trust_until)   │
│        └─ Return {device_id, encrypted_token, token}     │
│                                                             │
│  3. Trusted device re-pairing (optional):                 │
│     └─ POST /pair/trust/auto-repair                      │
│        └─ pairing_v2.auto_repair_trusted()               │
│           ├─ Verify device_public_key matches            │
│           ├─ Generate new session token                  │
│           └─ Return new encrypted token                  │
│                                                             │
│  4. Token rotation (security):                            │
│     └─ POST /pair/token/rotate                           │
│        └─ pairing_v2.rotate_token()                      │
│                                                             │
│  5. Biometric challenge (vault unlock):                   │
│     └─ POST /pair/biometric/challenge                    │
│        └─ pairing_v2.create_biometric_challenge()        │
└───────────────────────────────────────────────────────────┘

┌─ Pairing V1 Fallback ────────────────────────────────────┐
│  1. pairing.generate_code() → 6-digit code               │
│  2. pairing.pair_device(code, device_name) → {token}     │
│  3. pairing.verify_device(device_id, token)              │
└───────────────────────────────────────────────────────────┘
```

---

## 8. Data Flow: Screen Perception

```
screen_tools.scan() / screen_tools.click_text()
         │
         ▼
┌─ scan_screen.py ─────────────────────────────────────────┐
│  1. capture_screen() → PIL Image (pyautogui.screenshot)  │
│                                                             │
│  2. run_uia_scan(max_depth, max_elements)                 │
│     └─ subprocess: powershell uia_scan.ps1                │
│        └─ Returns JSON list of UIA elements               │
│           (role, label, bounds, automation_id, process_id)│
│                                                             │
│  3. detect_visual_boxes(screenshot, limit)                │
│     └─ OpenCV: Canny edge → morphology → contours         │
│        └─ Returns visual candidate bounding boxes         │
│                                                             │
│  4. Merge + filter: valid_bounds()                        │
│                                                             │
│  5. actionable_elements() → filter to UIA actionable roles│
│     (button, edit, hyperlink, checkbox, combobox, etc.)   │
└───────────────────────────────────────────────────────────┘
         │
         ▼
screen_tools._click_text_sync(text)
         │
         ▼
┌─ Element Matching ───────────────────────────────────────┐
│  1. _scan_sync() → get all elements                      │
│  2. _find_best(elements, text)                           │
│     ├─ For each element:                                 │
│     │   ├─ _score(query, label) → text_score             │
│     │   │   (exact > contains > all-words > SequenceMatcher)│
│     │   └─ _endpoint_score(element, text_score)          │
│     │       (text*0.62 + confidence*0.22 + size*0.04     │
│     │        + source_bonus*0.12)                        │
│     └─ Return best match above min_score                 │
│                                                             │
│  3. pyautogui.click(x, y) → execute click                │
└───────────────────────────────────────────────────────────┘
```

---

## 9. Data Flow: Runtime Engine

```
┌─ Startup ────────────────────────────────────────────────┐
│  main.py startup:                                        │
│  1. ResourceBudget.measure() → RuntimeBudget             │
│     (available_mb, model_budget_mb, mode)                │
│                                                             │
│  2. ArtifactStore.inventory() → find all model artifacts │
│     (ocr-mobile, ui-detector-int8, nexa-1.5b-q4, etc.) │
│                                                             │
│  3. SSDTierManager.plan(budget, artifacts, reserve)      │
│     → SSDTierPlan with placements per model              │
│     (resident / warm / ssd-cold / ssd-off)              │
│                                                             │
│  4. ModelRegistry.register(spec) for each model          │
│                                                             │
│  5. AgentTierManager.decide(intent, budget, hot_models)  │
│     → TierDecision (tier0 / tier1, allowed_models)       │
│                                                             │
│  6. model_registry.prefetch(names) → load hot models     │
└───────────────────────────────────────────────────────────┘

┌─ Per-Command ────────────────────────────────────────────┐
│  1. Telemetry.trace_command() → start trace              │
│                                                             │
│  2. StrategyRouter.execute_with_strategy()               │
│     ├─ CircuitBreaker.is_available(tool)?                │
│     ├─ execute_fn(tool, args)                            │
│     ├─ Classify failure → AdaptiveRetry                  │
│     ├─ IntentMemory.record_success/failure()             │
│     └─ SpeculativePrefetcher.record_cooccurrence()      │
│                                                             │
│  3. Telemetry.record_tool_call(tool, latency, success)   │
│                                                             │
│  4. ToolHeatMap.record_plan(intent, steps)               │
│                                                             │
│  5. Telemetry._record_completion() → write JSON          │
└───────────────────────────────────────────────────────────┘

┌─ Native Bridge (optional acceleration) ─────────────────┐
│  native_bridge.py:                                       │
│  ├─ Try loading screenai_core.dll/.so/.dylib            │
│  ├─ If C available: use C functions via ctypes          │
│  └─ If C unavailable: use pure-Python fallbacks         │
│                                                             │
│  Functions: levenshtein, fuzzy_score, xxhash64,          │
│             rolling_hash, validate_bounds, rank_elements │
└─────────────────────────────────────────────────────────┘
```

---

## 10. External Dependencies Map

### Python Packages

| Package | Used By | Purpose |
|---------|---------|---------|
| `fastapi` | `main.py` | HTTP framework |
| `uvicorn` | `main.py` | ASGI server |
| `aiosqlite` | `db/database.py` | Async SQLite |
| `pydantic` | `db/models.py`, `main.py` | Data validation |
| `psutil` | `system_tools.py`, `resource_budget.py` | System metrics |
| `pyautogui` | `screen_tools.py`, `scan_screen.py` | Screenshot + mouse control |
| `Pillow` | `scan_screen.py` | Image processing |
| `opencv-python` | `scan_screen.py` | Visual box detection |
| `playwright` | `browser_tools.py` (optional) | Browser automation |
| `cryptography` | `vault.py`, `pairing_v2.py` | AES-256-GCM, Argon2id, X25519 |
| `onnxruntime` | `model_loaders.py` (optional) | OCR + detector inference |
| `paddleocr` | `model_loaders.py` (optional) | OCR fallback |
| `llama-cpp-python` | `model_loaders.py` (optional) | nexa GGUF inference |
| `ctypes` (stdlib) | `native_bridge.py`, `system_tools.py` | C interop |

### System Dependencies

| Tool | Used By | Purpose |
|------|---------|---------|
| PowerShell | `uia_scan.ps1` (via `scan_screen.py`) | Windows UIA Automation tree |
| GCC | `build.bat` / `build_unix.sh.cmd` | Compile `screenai_core.c` → DLL/SO |
| Chromium | `playwright` (via `browser_tools.py`) | Headless browser |

---

## 11. Database Schema & Access Patterns

### Tables (defined in `database.py`)

| Table | Columns | Accessed By |
|-------|---------|-------------|
| `commands` | id, source, device_id, input_text, intent, risk_level, status, result, error, created_at, completed_at | `router.py`, `memory.py`, `main.py` |
| `approvals` | id, command_id, risk_level, action_type, target, description, impact_summary, status, created_at, resolved_at, expires_at | `approvals/manager.py` |
| `actions` | id, command_id, approval_id, tool, input_json, output_json, risk_level, status, error, created_at | `router.py` |
| `devices` | id, name, token_hash, paired_at, last_seen, active, trust_until, device_public_key | `pairing.py`, `pairing_v2.py` |
| `pairing_codes` | id, code, expires_at, used | `pairing.py` |
| `pairing_sessions` | id, public_key, expires_at, used | `pairing_v2.py` |
| `vault_entries` | id, site, username, encrypted_password, created_at, last_used | `vault.py` |
| `quarantine` | id, original_path, quarantine_path, command_id, file_size, created_at, restored_at, deleted_at | `file_tools.py` |
| `biometric_challenges` | id, device_id, challenge, expires_at, used | `pairing_v2.py` |
| `token_rotations` | id, device_id, reason, created_at | `pairing_v2.py` |

### Access Pattern Summary

```
router.py ──────→ commands, actions
memory.py ──────→ commands
approvals/manager.py → approvals
pairing.py ─────→ pairing_codes, devices
pairing_v2.py ──→ pairing_sessions, devices, biometric_challenges, token_rotations
vault.py ───────→ vault_entries
file_tools.py ──→ quarantine
main.py ────────→ commands, approvals (status endpoints)
```

---

## 12. File Data Flow (I/O Paths)

### Persistent State Files

| File Path | Written By | Read By |
|-----------|-----------|---------|
| `data/memory/strategy_state.json` | `strategy.py` (IntentMemory) | `strategy.py` (IntentMemory) |
| `data/memory/tool_heatmap.json` | `heatmap.py` (ToolHeatMap) | `heatmap.py` (ToolHeatMap) |
| `data/memory/model_usage.json` | `ssd_tier.py` (SSDTierManager) | `ssd_tier.py` (SSDTierManager) |
| `data/memory/telemetry_live.json` | `telemetry.py` (Telemetry) | Frontend dashboard |
| `data/telemetry.db` | `telemetry.py` | Analytics queries |
| `data/agent.log` | `main.py` (logging) | Debugging |
| `data/.screen_ai_cache/` | `screen_cache.py` | `screen_cache.py` |
| `data/quarantine/` | `file_tools.py` | `file_tools.py` |
| `data/downloads/` | `browser_tools.py`, `download_tools.py` | User |
| `data/research/` | `browser_tools.py` | User |
| `data/models/` | `download_models.py` | `artifact_store.py` → `model_loaders.py` |

### Native Build Artifacts

| File | Built By | Used By |
|------|----------|---------|
| `native/screenai_core.dll` | `build.bat` | `native_bridge.py` (Windows) |
| `native/screenai_core.so` | `build_unix.sh.cmd` | `native_bridge.py` (Linux) |
| `native/screenai_core.dylib` | `build_unix.sh.cmd` | `native_bridge.py` (macOS) |

---

## 13. Cross-Cutting Concerns

### Security

- **Risk Classification**: `risk.py` classifies commands on a 0-5 scale
- **Approval Gate**: `permissions.py` decides if approval needed; `approvals/manager.py` manages the approval lifecycle
- **Vault Encryption**: `vault.py` uses AES-256-GCM with Argon2id key derivation
- **Device Pairing**: `pairing.py` (basic) + `pairing_v2.py` (QR/X25519/trust/rotation/biometric)
- **Log Redaction**: `redactor.py` strips passwords, tokens, CC numbers, SSNs from logs
- **Protected Paths**: `file_tools.py` blocks operations on `C:\Windows`, `Program Files`, `.ssh`, `.env`
- **Dangerous Downloads**: `browser_tools.py` and `download_tools.py` block `.exe`, `.msi`, `.bat`, `.ps1`, etc.
- **Frontend Crypto**: `worker.js` uses WebCrypto for PBKDF2, AES-GCM, SHA-256

### Offline / Low-Resource

- **PWA**: `sw.js` provides offline caching; `app.js` registers Service Worker
- **Offline Drafts**: `sw.js` caches the shell and saves offline commands as drafts only; commands are never replayed automatically
- **IndexedDB**: `worker.js` caches data locally
- **RAM-Aware Loading**: `resource_budget.py` → `tier_manager.py` → `ssd_tier.py` → `model_registry.py`
- **Idle Cleanup**: `browser_tools.py` closes Chromium after 120s idle; `model_registry.py` unloads idle models
- **Bounded Scanning**: `file_tools.py` limits scan to 5000 files, depth 3, 10s timeout
- **Native Acceleration**: `native_bridge.py` → `screenai_core.c` for hot-path algorithms (with Python fallback)

### Observability

- **Telemetry**: `telemetry.py` traces every command through the pipeline with per-step timing
- **Strategy State**: `strategy.py` persists circuit breaker + intent memory across restarts
- **Tool Heatmap**: `heatmap.py` learns which tools follow which intents
- **Live Dashboard**: `telemetry.get_live_dashboard()` → served at `/runtime` endpoint

---

## 14. Test Coverage Map

| Test File | Tests | Modules Covered |
|-----------|-------|-----------------|
| `test_basic.py` | Core functionality | `risk.py`, `permissions.py`, `file_tools.py`, `system_tools.py`, `download_tools.py`, `browser_tools.py`, `planner.py`, `router.py`, `vault.py`, `pairing.py`, `telemetry.py`, `strategy.py`, `model_registry.py`, `ssd_tier.py`, `heatmap.py`, `resource_budget.py`, `tier_manager.py`, `io_pool.py`, `screen_cache.py`, `native_bridge.py`, `artifact_store.py`, `redactor.py`, `task_planner.py` |
| `test_login_v2.py` | Pairing V2 + vault | `pairing_v2.py`, `vault.py` |
| `test_strategy.py` | Strategy engine | `strategy.py` (CircuitBreaker, IntentMemory, AdaptiveRetry) |

**Total**: 59 tests, all passing (3.66s)

---

## 15. API Endpoint Map

| Method | Endpoint | Handler | Auth | Risk |
|--------|----------|---------|------|------|
| POST | `/command` | `main.py` → `router.process_command()` | Device token | 0-5 |
| POST | `/command/preview` | `main.py` → `router.preview_plan()` | Device token | 0-5 |
| GET | `/status` | `main.py` → system status | Device token | 0 |
| GET | `/history` | `main.py` → command history | Device token | 0 |
| GET | `/runtime` | `main.py` → telemetry dashboard | Device token | 0 |
| POST | `/approvals/{id}/approve` | `main.py` → `approval_manager.approve()` | Device token | 0 |
| POST | `/approvals/{id}/reject` | `main.py` → `approval_manager.reject()` | Device token | 0 |
| GET | `/approvals/pending` | `main.py` → pending approvals | Device token | 0 |
| POST | `/emergency/stop` | `main.py` → emergency halt | Device token | 0 |
| POST | `/pair/code/create` | `main.py` → `pairing.generate_code()` | None | 0 |
| POST | `/pair/device` | `main.py` → `pairing.pair_device()` | Pairing code | 0 |
| GET | `/pair/qr/create` | `main.py` → `pairing_v2.create_qr_pairing()` | None | 0 |
| POST | `/pair/qr/complete` | `main.py` → `pairing_v2.complete_qr_pairing()` | QR session | 0 |
| POST | `/pair/trust/auto-repair` | `main.py` → `pairing_v2.auto_repair_trusted()` | Device trust | 0 |
| POST | `/pair/token/rotate` | `main.py` → `pairing_v2.rotate_token()` | Device token | 0 |
| POST | `/pair/biometric/challenge` | `main.py` → `pairing_v2.create_biometric_challenge()` | Device token | 0 |
| POST | `/auth/vault/unlock` | `main.py` → `auth_tools.vault_unlock()` | Device token | 3 |
| POST | `/auth/vault/lock` | `main.py` → `auth_tools.vault_lock()` | Device token | 3 |
| GET | `/auth/vault/list` | `main.py` → `auth_tools.vault_list()` | Device token | 3 |
| GET | `/remote/*` | Static files (frontend) | None | 0 |

---

*This document maps the complete Screen-AI codebase as of the latest session. Update when new modules are added.*
