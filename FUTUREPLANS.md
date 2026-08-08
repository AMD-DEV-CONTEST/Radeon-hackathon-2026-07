# Screen-AI Future Plans

This document outlines the long-term vision, roadmap, and future enhancements for Screen-AI.

## Vision Statement

Screen-AI will become the **leading local-first AI PC operator** that gives users complete control over their computer through natural language commands, with mobile-based approval for sensitive actions. No cloud dependency for sensitive operations. Full transparency. Full user control.

## Long-Term Goals

### Year 1: Foundation (Current)

- [x] Screen scanning with UIA + OpenCV
- [x] Click-by-text execution
- [ ] FastAPI PC agent server
- [ ] Mobile web remote
- [ ] Pairing system
- [ ] File tools with quarantine
- [ ] System status tools
- [ ] Browser tools with Playwright
- [ ] Password vault with encryption
- [ ] Passkey flow controller
- [ ] Local LLM routing

### Year 2: Expansion

- [ ] Native mobile apps (Flutter/React Native)
- [ ] Multi-device support (multiple phones paired)
- [ ] Voice command support
- [ ] Multi-language support
- [ ] Plugin system for custom tools
- [ ] Cloud sync (optional, encrypted)
- [ ] Team/family sharing features
- [ ] Advanced automation workflows

### Year 3: Intelligence

- [ ] Learning from user patterns
- [ ] Predictive suggestions
- [ ] Anomaly detection
- [ ] Self-healing automation
- [ ] Cross-platform support (macOS, Linux)
- [ ] Advanced vision models (Florence-2, OmniParser)
- [ ] Multi-modal input (voice + text + image)

## Roadmap by Phase

### Phase 1: Local Server (Weeks 1-2)

**Goal**: Phone can send text command to PC.

**Deliverables**:
- FastAPI server with WebSocket support
- SQLite database with all tables
- Basic command/response flow
- Health check endpoint
- Logging system

**Success Criteria**:
- Phone can connect to PC
- Phone can send "check status" command
- PC responds with system info
- All commands logged

### Phase 2: Mobile Web Remote (Weeks 3-4)

**Goal**: Phone controls PC locally.

**Deliverables**:
- React/Vue mobile web app
- Command input interface
- Response display
- Approval panel
- Emergency stop button
- Command history view

**Success Criteria**:
- Phone UI is responsive and intuitive
- Commands execute within 2 seconds
- Emergency stop works instantly
- History is searchable

### Phase 3: Pairing System (Weeks 5-6)

**Goal**: No random device on Wi-Fi can control it.

**Deliverables**:
- 6-digit pairing code generation
- QR code for easy pairing
- Token-based authentication
- Device management UI
- Revoke device capability

**Success Criteria**:
- Pairing takes < 30 seconds
- Unpaired devices get 401
- Tokens are encrypted at rest
- User can revoke any device

### Phase 4: File Tools (Weeks 7-8)

**Goal**: Delete requires approval and is reversible.

**Deliverables**:
- file.list, file.scan, file.read
- file.move, file.copy
- file.quarantine, file.restore
- file.delete_permanent (with special approval)
- Protected folder enforcement
- Bulk operation approval

**Success Criteria**:
- All deletes go to quarantine by default
- Restore works perfectly
- Protected folders require explicit approval
- Bulk operations show impact before approval

### Phase 5: System Tools (Weeks 9-10)

**Goal**: "Check my PC" works.

**Deliverables**:
- system.status (CPU, RAM, disk, battery)
- system.disk_usage
- system.ram_usage
- system.processes
- system.open_app
- system.kill_process (with approval)
- system.network_status

**Success Criteria**:
- Status returns within 1 second
- App opening works reliably
- Kill process requires approval
- Network status is accurate

### Phase 6: Browser Tools (Weeks 11-12)

**Goal**: "Search and download X" works.

**Deliverables**:
- browser.open (Playwright)
- browser.search
- browser.click, browser.type
- browser.read (DOM extraction)
- download.file (with approval for executables)
- Human visual mode (OCR + mouse/keyboard)

**Success Criteria**:
- Can open any URL
- Can fill forms reliably
- Downloads go to AI_Downloads folder
- Executables require approval before running

### Phase 7: Password Vault (Weeks 13-14)

**Goal**: "Login to xyz.com" works using saved password.

**Deliverables**:
- AES-256-GCM encryption
- Argon2id key derivation
- Vault unlock from phone
- Autofill login forms
- Log redaction
- Session expiry

**Success Criteria**:
- Passwords never stored in plain text
- Unlock requires master key
- Passwords redacted from logs
- Session expires after 5 minutes

### Phase 8: Passkey Flow (Weeks 15-16)

**Goal**: "Login with passkey" works through normal OS/browser approval.

**Deliverables**:
- Detect passkey prompts
- Request phone approval
- Wait for OS/browser auth
- Continue after login
- Support Windows Hello, Edge, phone passkeys

**Success Criteria**:
- Detects passkey prompts reliably
- User approval flow is smooth
- Works with Windows Hello
- Works with Edge passkeys

### Phase 9: Local Model (Weeks 17-20)

**Goal**: Natural language commands become tool plans offline.

**Deliverables**:
- Local LLM integration (llama.cpp/Ollama)
- Intent classifier
- Risk classifier
- Tool planner
- Model routing
- Quantized model support (Q4)

**Success Criteria**:
- Intent classification accuracy > 90%
- Risk classification accuracy > 95%
- Plans execute correctly > 85%
- Runs on 4GB RAM laptop

## Future Enhancements

### Advanced Vision

- **Florence-2 integration** for screen understanding
- **OmniParser v2** for complex UI parsing
- **Custom YOLO models** trained on user screens
- **Visual grounding** for natural language element references

### Multi-Modal Input

- **Voice commands** via Whisper.cpp
- **Image commands** (point at screen element)
- **Gesture commands** (touchpad gestures)
- **Eye tracking** for accessibility

### Intelligence Layer

- **Pattern learning** from user behavior
- **Predictive suggestions** based on context
- **Anomaly detection** for unusual commands
- **Self-healing** when actions fail
- **Workflow templates** for common tasks

### Platform Expansion

- **macOS support** via AppleScript + Accessibility API
- **Linux support** via AT-SPI
- **Android control** via ADB
- **iOS control** via shortcuts
- **Cross-device workflows**

### Enterprise Features

- **Team management** for shared computers
- **Audit logs** for compliance
- **Role-based access** for different users
- **SSO integration** for enterprise login
- **Policy engine** for organizational rules

### Community & Ecosystem

- **Plugin marketplace** for custom tools
- **Workflow sharing** between users
- **Dataset contributions** for training
- **Model fine-tuning** for specific use cases
- **API for third-party integration**

## Research Directions

### Model Compression

- Investigate 2-bit quantization for ultra-low RAM
- Explore mixture-of-experts for selective loading
- Test pruning techniques for YOLO models
- Benchmark SSD vs RAM model loading

### Privacy & Security

- Zero-knowledge encryption for vault
- Homomorphic encryption for cloud sync
- Differential privacy for usage analytics
- Secure enclaves for credential storage

### Performance

- GPU acceleration for vision models
- NPU support for modern laptops
- WebGPU for browser-based inference
- Edge computing for distributed tasks

## Success Metrics

### Technical Metrics

- **Latency**: < 2s for simple commands, < 10s for complex
- **Accuracy**: > 90% intent classification, > 95% risk classification
- **Reliability**: > 99% uptime, < 1% action failures
- **Resource usage**: < 2GB RAM for core, < 4GB with all features

### User Metrics

- **Adoption**: 10K active users by Year 1
- **Retention**: > 70% monthly active users
- **Satisfaction**: > 4.5/5 user rating
- **Commands/day**: Average 50+ commands per active user

### Business Metrics

- **Open source**: 5K GitHub stars by Year 1
- **Community**: 100+ contributors
- **Plugins**: 50+ community plugins
- **Integrations**: 20+ third-party integrations

## Open Questions

1. **Cloud sync**: Should we offer optional encrypted cloud sync?
2. **Multi-user**: How to handle multiple users on same PC?
3. **Voice**: When to add voice support?
4. **Mobile apps**: Native vs PWA?
5. **Monetization**: Open source only or premium features?
6. **Enterprise**: B2B vs B2C focus?
7. **AI training**: Use user data for training (opt-in)?
8. **Privacy**: How to balance intelligence vs privacy?

## Contributing

We welcome contributions in:

- **Code**: New tools, bug fixes, optimizations
- **Datasets**: Screen captures, intent examples
- **Documentation**: Guides, tutorials, API docs
- **Testing**: QA, performance testing, security audit
- **Design**: UI/UX improvements, icons, branding

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

Screen-AI is licensed under MIT License. See [LICENSE](LICENSE) for details.

## Contact

- **GitHub**: https://github.com/madhavabrightly/Screen-AI
- **Discord**: https://discord.gg/screen-ai
- **Email**: screen-ai@example.com
- **Twitter**: @ScreenAI

---

**Last Updated**: 2026-07-23
**Version**: 1.0.0
**Status**: Active Development
