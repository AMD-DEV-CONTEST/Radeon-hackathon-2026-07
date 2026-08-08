# Screen-AI Architecture

## Overview

Screen-AI is a **fully local/offline PC operator AI** with full system access, controlled by your PC and phone. The phone serves as the command, approval, and unlock device.

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Mobile Remote (Phone)                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ Command  │  │ Approval │  │  Vault   │  │  Stop  │ │
│  │   Page   │  │   Page   │  │   Page   │  │ Button │ │
│  └────┬─────┘  └─────┬────┘  └─────┬────┘  └───┬────┘ │
└───────┼──────────────┼─────────────┼───────────┼──────┘
        │              │             │           │
        │   WebSocket + REST API      │           │
        └──────────────┴─────────────┴───────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Local PC Agent Server (FastAPI)            │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Agent Router (Pipeline)             │  │
│  │  Intent → Risk → Permission → Plan → Execute    │  │
│  └──────────────────────────────────────────────────┘  │
│                       │                                 │
│  ┌────────┬───────────┼───────────┬──────────┐         │
│  │  Risk  │ Permission│  Planner  │  Memory  │         │
│  │ Engine │  Engine   │           │          │         │
│  └────────┴───────────┴───────────┴──────────┘         │
│                       │                                 │
│  ┌────────┬───────────┼───────────┬──────────┐         │
│  │  File  │  Browser  │  System   │   Auth   │         │
│  │ Tools  │   Tools   │   Tools   │   Tools  │         │
│  └────────┴───────────┴───────────┴──────────┘         │
│                       │                                 │
│  ┌────────┬───────────┼───────────┬──────────┐         │
│  │  UIA   │  OpenCV   │  Paddle   │  YOLO    │         │
│  │ Scanner│  Vision   │   OCR     │  ONNX    │         │
│  └────────┴───────────┴───────────┴──────────┘         │
└─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                    Windows PC System                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │  Files   │  │ Browser  │  │   Apps   │  │ System │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘ │
└─────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Mobile Remote (Frontend)

**Technology**: HTML/CSS/JavaScript (mobile web app)

**Responsibilities**:
- Send text commands to PC
- Approve/reject critical actions
- Unlock password vault
- View action history
- Emergency stop

**Pages**:
- Pairing Screen (6-digit code entry)
- Command Page (text input + response)
- Approval Page (pending approvals)
- History Page (command history)
- Settings Page (device info)

### 2. PC Agent Server (Backend)

**Technology**: Python + FastAPI + WebSocket

**Responsibilities**:
- Receive commands from phone
- Process through agent pipeline
- Execute tools
- Manage approvals
- Log actions
- Enforce permissions

**Endpoints**:
- `POST /pair` - Pair device with code
- `POST /command` - Submit text command
- `GET /approvals/pending` - List pending approvals
- `POST /approvals/resolve` - Approve/reject action
- `POST /emergency/stop` - Halt all operations
- `GET /history` - View command history
- `WS /ws` - Real-time updates

### 3. Agent Router (Pipeline)

**Flow**:
```
User Command
    ↓
Intent Classification (planner.py)
    ↓
Risk Assessment (risk.py)
    ↓
Permission Check (permissions.py)
    ↓
Approval Request (if needed)
    ↓
Plan Creation (planner.py)
    ↓
Tool Execution (tools/*.py)
    ↓
Verification
    ↓
Result Logging
    ↓
User Response
```

### 4. Tool Executor

**Available Tools**:

| Tool | Purpose | Risk |
|------|---------|------|
| `system.status` | System info | 0 |
| `system.disk_usage` | Disk space | 0 |
| `system.ram_usage` | Memory usage | 0 |
| `system.open_app` | Launch app | 1 |
| `system.run_command` | Execute command | 3 |
| `file.list` | List directory | 0 |
| `file.read` | Read file | 0 |
| `file.move` | Move file | 2 |
| `file.quarantine` | Quarantine file | 4 |
| `file.restore` | Restore from quarantine | 2 |
| `browser.open` | Open URL | 1 |
| `browser.search` | Web search | 0 |
| `browser.click` | Click element | 1 |
| `browser.type` | Type text | 1 |
| `browser.download` | Download file | 2 |
| `auth.password_login` | Login with password | 3 |
| `auth.passkey_login` | Login with passkey | 3 |
| `download.file` | Download file | 2 |

### 5. Permission Engine

**Access Levels**:

| Level | Actions | Approval |
|-------|---------|----------|
| 0 | Read-only operations | None |
| 1 | Open apps/sites | None |
| 2 | File operations | Maybe |
| 3 | Login, email, install | Mobile required |
| 4 | Delete, bulk ops, admin | Mobile required |
| 5 | Permanent delete, financial | Special mode |

### 6. Password Vault

**Security**:
- AES-256-GCM encryption
- Argon2id key derivation
- 5-minute session expiry
- Memory wiping on lock
- Log redaction

**Flow**:
```
User: "Login to xyz.com"
    ↓
AI detects login page
    ↓
Requests vault unlock on phone
    ↓
User enters master key
    ↓
Vault decrypts password
    ↓
Automation fills credentials
    ↓
Password wiped from memory
```

### 7. Screen Scanner (Tier 0)

**Technology**: Windows UI Automation + OpenCV

**Always Resident**:
- UIA element map
- OpenCV visual candidates
- Screenshot capture
- Click executor

**Priority**:
1. UIA exact label match
2. OCR text match
3. YOLO UI detector
4. OpenCV visual candidates
5. Ask user if confidence low

## Data Flow

### Command Flow

```
1. User types command on phone
2. Phone sends POST /command
3. Server receives command
4. Agent Router processes:
   a. Classify intent
   b. Assess risk
   c. Check permissions
   d. If approval needed → create approval request
   e. If approved → execute tools
   f. Log action
   g. Return result
5. Phone displays result
```

### Approval Flow

```
1. Critical action detected
2. Server creates approval request
3. Phone receives notification (WebSocket)
4. User reviews impact summary
5. User approves/rejects
6. Server resolves approval
7. If approved → continue execution
8. If rejected → cancel and log
```

## Database Schema

**SQLite Tables**:
- `commands` - All user commands
- `approvals` - Pending/resolved approvals
- `actions` - Executed tool actions
- `devices` - Paired devices
- `vault_entries` - Encrypted credentials
- `quarantine` - Quarantined files
- `sessions` - Active sessions
- `settings` - System settings
- `pairing_codes` - Active pairing codes

## Security Model

**Layers**:
1. **Pairing**: 6-digit code, device token
2. **Authentication**: Bearer token per device
3. **Authorization**: Risk-based approval
4. **Encryption**: AES-256-GCM for vault
5. **Audit**: All actions logged
6. **Redaction**: Secrets removed from logs

## Performance

**Target**: 4GB RAM laptops

**Strategy**:
- Tiered model loading (resident → warm → cold)
- Lazy loading of heavy modules
- SQLite for fast queries
- Async I/O throughout
- Cached frequent commands

## Deployment

**Local PC**:
```bash
cd ai_pc_operator/backend
pip install -r requirements.txt
python -m playwright install chromium
python -m app.main
```

**Mobile**:
- Open browser to `http://<pc-ip>:8000`
- Enter pairing code
- Start sending commands

## Future Enhancements

- Local LLM integration (Qwen2.5 1.5B)
- YOLO UI detector (INT8 ONNX)
- AMD ROCm cloud training
- Multi-device support
- Voice commands
- Screenshot analysis
