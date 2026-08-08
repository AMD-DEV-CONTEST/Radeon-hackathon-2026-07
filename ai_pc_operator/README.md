# Screen-AI: Local AI PC Operator

**Fully local/offline PC operator AI with full system access, controlled by your PC and phone.**

## Features

- 📱 **Mobile Remote**: Control your PC from your phone
- 🔐 **Secure Pairing**: 6-digit code device pairing
- ✅ **Approval System**: Mobile approval for critical actions
- 🗑️ **Quarantine Delete**: Reversible file deletion
- 🔑 **Password Vault**: Encrypted credential storage
- 🌐 **Browser Automation**: Playwright-based web control
- 📊 **System Monitoring**: CPU, RAM, disk, processes
- 🛑 **Emergency Stop**: Instant halt of all operations
- 🧠 **Cognitive Planner**: Natural-language intent understanding with semantic matching
- 🌐 **External Reasoning**: DeepSeek-V4-Flash via AMD Radeon API (env-var key, advisory)
- 📷 **Camera Capture**: Take-my-picture → launch camera → capture → verify
- 💬 **Chat Mode**: Conversational replies when intent is unknown
- 🧩 **Compound Commands**: Chained multi-action commands → one execution graph
- 📦 **Generic Decomposition**: Entity-driven planning, no hardcoded app workflows

## Quick Start

### 1. Install Dependencies

```bash
cd ai_pc_operator/backend
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Start Server

```bash
python -m app.main
```

Server runs on `http://localhost:8000`

### 3. Pair Mobile Device

1. Open browser on phone to `http://<pc-ip>:8000`
2. Get pairing code from server console
3. Enter code on phone
4. Start sending commands!

## Architecture

```
Mobile Remote (Phone)
    ↓ WebSocket + REST
Local PC Agent (FastAPI)
    ↓ Agent Pipeline
Tools (File, Browser, System, Auth)
    ↓
Windows PC
```

See [docs/architecture.md](docs/architecture.md) for details.

## Usage Examples

### System Commands

```
"Check my storage"
"How much RAM am I using?"
"Show running processes"
```

### File Operations

```
"List files in Downloads"
"Delete files in Downloads"  (requires approval)
"Restore quarantined files"
```

### Browser Automation

```
"Open github.com"
"Search for python tutorials"
"Download VLC"
```

### Authentication

```
"Login to github.com"  (requires vault unlock)
"Save password for gmail.com"
```

## Security

- **Pairing**: 6-digit code, device tokens
- **Encryption**: AES-256-GCM for vault
- **Key Derivation**: Argon2id
- **Audit**: All actions logged
- **Redaction**: Secrets removed from logs
- **Emergency Stop**: Always available

See [docs/permissions.md](docs/permissions.md) for access levels.

## Development

### Project Structure

```
ai_pc_operator/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI entry point
│   │   ├── agent/            # Agent brain
│   │   ├── security/         # Risk, permissions, vault
│   │   ├── tools/            # File, browser, system, auth
│   │   ├── approvals/        # Approval manager
│   │   ├── db/               # Database
│   │   └── logs/             # Log redaction
│   └── requirements.txt
├── frontend/
│   ├── index.html            # Mobile web app
│   ├── styles.css
│   └── app.js
├── data/
│   ├── datasets/             # Training data
│   ├── quarantine/           # Quarantined files
│   └── downloads/            # Downloaded files
└── docs/
    ├── architecture.md
    ├── permissions.md
    ├── vault.md
    └── roadmap.md
```

### Adding New Tools

1. Create tool in `backend/app/tools/`
2. Register in `agent/router.py`
3. Add to planner patterns
4. Update documentation

### Adding New Intents

1. Add patterns to `agent/planner.py`
2. Add examples to `data/datasets/intent_dataset.jsonl`
3. Test with sample commands

## Roadmap

- ✅ Phase 1-7: Core system, mobile remote, file tools, system tools, browser tools, password vault
- 🚧 Phase 8: Passkey flow
- 📋 Phase 9: Local LLM integration
- 📋 Phase 10-12: OCR, YOLO, AMD cloud training

See [docs/roadmap.md](docs/roadmap.md) for full roadmap.

## Requirements

- **OS**: Windows 10/11
- **Python**: 3.10+
- **RAM**: 4GB minimum (8GB recommended)
- **Browser**: Chrome/Edge (for mobile remote)

## License

TBD

## Contributing

See [AGENTS.md](../AGENTS.md) for development guidelines.
