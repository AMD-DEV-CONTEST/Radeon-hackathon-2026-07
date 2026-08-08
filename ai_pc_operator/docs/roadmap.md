# Screen-AI Roadmap

## Phase 1: Local Server (✅ Complete)

**Goal**: Phone can send text commands to PC

**Deliverables**:
- ✅ FastAPI server with WebSocket
- ✅ SQLite database with full schema
- ✅ Command/approval/history endpoints
- ✅ Emergency stop
- ✅ Basic agent router

## Phase 2: Mobile Web Remote (✅ Complete)

**Goal**: Phone controls PC locally

**Deliverables**:
- ✅ Pairing screen with 6-digit code
- ✅ Command input page
- ✅ Approval panel
- ✅ History view
- ✅ Settings page
- ✅ Emergency stop button

## Phase 3: Pairing System (✅ Complete)

**Goal**: No random device on Wi-Fi can control it

**Deliverables**:
- ✅ 6-digit pairing code generation
- ✅ Device token storage
- ✅ Token verification
- ✅ Device revocation

## Phase 4: File Tools (✅ Complete)

**Goal**: Delete requires approval and is reversible

**Deliverables**:
- ✅ List/scan/read files
- ✅ Quarantine delete (reversible)
- ✅ Restore from quarantine
- ✅ Protected path checking
- ✅ Bulk operation support

## Phase 5: System Tools (✅ Complete)

**Goal**: "Check my PC" works

**Deliverables**:
- ✅ System status
- ✅ Disk usage
- ✅ RAM usage
- ✅ Process list
- ✅ Open application
- ✅ Network status

## Phase 6: Browser Tools (✅ Complete)

**Goal**: "Search and download X" works

**Deliverables**:
- ✅ Open URL
- ✅ Web search
- ✅ Click/type with Playwright
- ✅ Download file
- ✅ Read page content

## Phase 7: Password Vault (✅ Complete)

**Goal**: "Login to xyz.com" works using saved password

**Deliverables**:
- ✅ AES-256-GCM encryption
- ✅ Argon2id key derivation
- ✅ Add/list/delete credentials
- ✅ Unlock from phone
- ✅ Auto-fill login
- ✅ Log redaction

## Phase 8: Passkey Flow (🚧 In Progress)

**Goal**: "Login with passkey" works through normal OS/browser approval

**Deliverables**:
- ✅ Detect passkey prompt
- 🚧 Request phone approval
- 🚧 Wait for Windows/browser auth
- 🚧 Continue after login

## Phase 9: Local Model (📋 Planned)

**Goal**: Natural language commands become tool plans offline

**Deliverables**:
- 📋 Qwen2.5 1.5B integration
- 📋 Intent classifier
- 📋 Tool planner
- 📋 Risk classifier
- 📋 Model routing

## Phase 10: OCR Fallback (📋 Planned)

**Goal**: Add OCR to existing scanner

**Deliverables**:
- 📋 PaddleOCR PP-OCRv4 Mobile
- 📋 Lazy loading
- 📋 Text matching
- 📋 Confidence scoring

## Phase 11: YOLO UI Detector (📋 Planned)

**Goal**: Add tiny YOLO ONNX local inference

**Deliverables**:
- 📋 YOLOv8n INT8 ONNX
- 📋 UI element detection
- 📋 Confidence scoring
- 📋 Integration with scanner

## Phase 12: AMD Cloud Training (📋 Planned)

**Goal**: AMD ROCm benchmark demo

**Deliverables**:
- 📋 OmniParser teacher labeling
- 📋 YOLO student training
- 📋 INT8 ONNX export
- 📋 ROCm benchmarks

## Phase 13: Advanced Features (📋 Future)

**Deliverables**:
- 📋 Voice commands
- 📋 Screenshot analysis
- 📋 Multi-device support
- 📋 Cloud sync (optional)
- 📋 Mobile native app

## Success Metrics

### Performance

- Command response time: < 2 seconds
- Approval notification: < 1 second
- Screen scan time: < 500ms
- Memory usage: < 500MB resident

### Reliability

- Uptime: 99% (local network)
- Approval success rate: > 95%
- Quarantine restore success: 100%
- Emergency stop response: < 100ms

### Security

- Zero password leaks in logs
- Zero unauthorized approvals
- 100% critical actions approved
- 100% destructive actions reversible

### Usability

- Pairing time: < 30 seconds
- Command to result: < 5 seconds
- Approval decision: < 10 seconds
- Learning curve: < 1 hour

## Open Questions

1. **Multi-user support**: How to handle multiple users on same PC?
2. **Cloud sync**: Should vault sync across devices?
3. **Voice input**: When to add voice commands?
4. **Mobile app**: Native vs web app?
5. **Enterprise features**: SSO, audit logs, compliance?

## Contributing

See [AGENTS.md](../AGENTS.md) for development guidelines.

## License

TBD
