# AI Desktop Agent Pipeline Master Specification

Version: 0.2
Date: 2026-07-30
Owner: brightly
Status: Draft master plan

---

## 1. Product Requirements Document

### 1.1 Product Name

Working name: **Desktop AI Agent Platform**

### 1.2 Product Vision

Build a powerful desktop AI assistant that can understand natural language, perceive the screen, operate applications, manage files, automate workflows, coordinate tools, and recover from errors through verification and self-correction.

The product should feel like an intelligent operator for the whole computer, not a chatbot bolted onto the side. Enterprise tools are fragmented across browser apps, local apps, files, chats, and calendars; the agent unifies them under one verified execution layer.

### 1.3 Target Users

- **Developers and technical founders** who want an autonomous software assistant.
- **Knowledge workers** who need file, browser, email, calendar, and document automation.
- **Operations teams** that need repeatable desktop workflows across enterprise systems.
- **Power users** who want natural-language control over local apps.
- **AI researchers and builders** who need an extensible agent runtime.

### 1.4 Core User Problems

- Desktop workflows require many tiny repetitive actions across apps.
- Existing automation tools are brittle because they rely on exact selectors or scripts.
- Most AI assistants cannot see, verify, or recover from actual UI state.
- Work is scattered across browser apps, local apps, files, chats, and calendars.
- Users need trustworthy automation with permissions, logs, and rollback.

### 1.5 Product Goals

- Accept high-level natural-language tasks and convert them into executable task graphs.
- Use screen perception, accessibility APIs, OS APIs, browser automation, and application-specific integrations.
- Verify every meaningful action through visual, DOM, file, process, or API state.
- Maintain a large skill registry of reusable atomic and compound capabilities.
- Provide safe automation with permissions, audit logs, sandboxing, and emergency stop.
- Support local-first execution while integrating with cloud and enterprise systems.

### 1.6 Non-Goals For The First Release

- Fully autonomous operation without user permission for sensitive actions.
- Replacing full RPA platforms on day one.
- Supporting every desktop app equally in the MVP.
- Training custom vision models before simpler OCR/accessibility/DOM pipelines are exhausted.
- Building a general AGI system. The target is reliable task automation.

### 1.7 Primary Use Cases

- "Organize my Downloads folder, rename invoices, and move them into finance folders."
- "Open Chrome, download this report, summarize it, and email the summary."
- "Fix this failing test in VS Code and commit the change."
- "Join my meeting, take notes, and create action items."
- "Extract data from this PDF table and add it to a spreadsheet."
- "Monitor this app install, handle prompts, and verify it launches."
- "Compare these two dashboards and flag anomalies."

### 1.8 User Experience Principles

- User states intent; agent shows plan; agent asks only when risk or ambiguity requires it.
- Agent operates with visible progress and concise status.
- Agent can explain what it did and prove it with logs, screenshots, and artifacts.
- Sensitive actions require explicit approval.
- Failures are recoverable, inspectable, and resumable.

### 1.9 Functional Requirements

- Natural-language task intake.
- Intent classification and entity extraction.
- Task decomposition into executable graphs.
- Skill selection from registry.
- Screen capture and perception pipeline.
- Accessibility tree reading.
- Browser DOM automation.
- OS-level input simulation.
- File system operations.
- Application-specific adapters.
- Verification and retry loop.
- Permission policy enforcement.
- Audit logging.
- Human-in-the-loop approval.
- Memory and workflow learning.
- Scheduling and background jobs.
- Multi-agent delegation for complex work.

### 1.10 Non-Functional Requirements

- **Reliability**: actions must be verified before progressing.
- **Safety**: no irreversible sensitive action without confirmation.
- **Latency**: common single-step actions should start within 1–3 seconds.
- **Observability**: every step should have logs, state, and outcome.
- **Extensibility**: skills must be installable and versioned.
- **Privacy**: local data stays local unless user approves external transfer.
- **Portability**: architecture should support Windows first, then macOS/Linux.

### 1.11 Success Metrics

- Task completion rate.
- Recovery rate after UI mismatch or failed step.
- User intervention rate.
- Average steps per successful task.
- Time saved per workflow.
- Skill reuse rate.
- False positive sensitive-action attempts.
- Number of supported apps and workflows.

### 1.12 Permission Model

Permission levels:

| Level | Scope | Examples |
|-------|-------|----------|
| 0 | Read-only local inspection | list files, read screen, query status |
| 1 | Local reversible actions | open app, rename file, fill form |
| 2 | Local destructive or privileged actions | delete file, install app, change settings |
| 3 | External communication or publishing | send email, post message, upload |
| 4 | Financial, legal, credential, security, or irreversible actions | payment, credential export, bulk delete |

Default policy:

- Level 0 and most Level 1 actions can run automatically.
- Level 2 requires confirmation unless pre-approved by policy.
- Level 3 and Level 4 always require explicit user approval.

---

## 2. Full 1000+ Skill Taxonomy

### 2.1 Taxonomy Format

Each skill should have:

- `skill_id`
- `name`
- `domain`
- `category`
- `description`
- `inputs`
- `outputs`
- `risk_level`
- `verification_method`
- `platforms`
- `dependencies`
- `version`

The taxonomy below defines 1,080 planned skills across 12 major domains. Each numbered item is a skill family containing concrete leaf skills. For implementation, each family expands into platform-specific and app-specific leaf skills.

### 2.2 Domain Summary

| Domain | Skills | Focus |
|--------|-------:|-------|
| D01 Vision & Perception | 90 | OCR, UI detection, accessibility fusion, charts, QR |
| D02 Mouse Engine | 70 | Click, drag, scroll, gesture, hover |
| D03 Keyboard Engine | 80 | Type, hotkey, clipboard, IME, macros |
| D04 Window Management | 90 | Lifecycle, focus, layout, multi-monitor |
| D05 File System | 150 | CRUD, search, archive, sync, encryption |
| D06 Browser Automation | 120 | Navigation, forms, DOM, downloads, recovery |
| D07 Application Skills | 150 | VS Code, Office, PDF, design, IDEs |
| D08 Developer Skills | 120 | Git, build, test, Docker, K8s, APIs |
| D09 Communication | 80 | Email, chat, calendar, meetings, voice |
| D10 AI Planning | 100 | Intent, planning, memory, retry, multi-agent |
| D11 Security | 80 | Permissions, secrets, audit, rollback, sandbox |
| D12 Enterprise | 150 | M365, Google, Atlassian, CRM, ERP, BI |
| **Total** | **1,280** | expanded by platform/app variants |

### D01 Vision & Perception (90 skills)

Families:

1. **OCR**: plain text, dense text, small text, rotated text, multilingual text, handwriting, code text, terminal text, form fields, receipts.
2. **UI detection**: buttons, inputs, menus, dropdowns, tabs, modals, sidebars, toolbars, dialogs, toasts.
3. **Accessibility fusion**: node matching, label extraction, role inference, bounds reconciliation, focus state, hidden node filtering.
4. **Icon recognition**: common OS icons, browser icons, editor icons, file type icons, status icons, app-specific icons.
5. **Window detection**: active window, background windows, title bars, resize handles, monitor bounds, z-order.
6. **Cursor tracking**: pointer position, hover target, drag path, cursor shape, selection handles.
7. **Document structure**: headings, paragraphs, lists, tables, footnotes, headers, footers, page numbers.
8. **Table recognition**: grid detection, cell segmentation, merged cells, row/column headers, sortable columns, numeric tables.
9. **Chart recognition**: line, bar, pie, scatter, area, gauge, timeline, heatmap, legend extraction.
10. **QR/barcode detection**: QR, Code128, EAN, UPC, DataMatrix, PDF417, damaged code recovery.
11. **Object and scene understanding**: desktop objects, app surfaces, media content, diagrams, whiteboards.
12. **Notification detection**: OS notifications, browser notifications, app banners, unread badges, warning states.
13. **Error detection**: crash dialogs, validation errors, permission prompts, connection errors, build errors.
14. **Multi-monitor mapping**: monitor topology, DPI scaling, coordinate transforms, window-to-monitor mapping.
15. **Screenshot analysis**: visual diff, target localization, anomaly detection, before/after verification.
16. **Video frame analysis**: frame sampling, motion detection, progress indicators, meeting UI state.
17. **Signature and form detection**: signature blocks, required fields, checkboxes, radio groups, date fields.
18. **Translation**: image text translation, UI translation, document translation, mixed-language detection.

### D02 Mouse Engine (70 skills)

Families:

1. **Basic clicking**: left, right, middle, double, triple, click-and-hold.
2. **Precision targeting**: center target, edge target, text caret target, icon target, fallback coordinate target.
3. **Movement**: absolute move, relative move, smooth move, human-like move, constrained move.
4. **Drag operations**: drag file, drag selection, drag slider, drag window, drag canvas object.
5. **Drop operations**: drop on folder, drop on app, drop on browser upload zone, drop in editor.
6. **Scrolling**: vertical, horizontal, page scroll, inertial scroll, nested container scroll.
7. **Hovering**: reveal tooltip, open menu, trigger preview, verify hover state.
8. **Selection**: lasso, text selection, table cell selection, multi-select with modifier.
9. **Gestures**: pinch, zoom, rotate, swipe, trackpad-style gesture abstraction.
10. **Verification**: click landed, state changed, target disabled, retry with offset, scroll-to-target.

### D03 Keyboard Engine (80 skills)

Families:

1. **Text entry**: plain text, formatted text, multiline text, code text, Unicode text.
2. **Secure typing**: password fields, OTP codes, protected clipboard, masked input.
3. **Hotkeys**: OS hotkeys, app hotkeys, browser hotkeys, editor hotkeys, custom shortcuts.
4. **Navigation**: tab order, arrow navigation, page up/down, home/end, focus cycling.
5. **Editing**: copy, paste, cut, undo, redo, select all, find, replace.
6. **Clipboard**: read, write, sanitize, history, rich text, image clipboard, file clipboard.
7. **IME and language**: switch language, compose accents, transliteration, emoji input.
8. **Macros**: record keystrokes, replay macro, parameterized macro, timed macro.
9. **Voice-to-text insertion**: dictated input, punctuation correction, field-aware insertion.
10. **Verification**: typed text match, field value readback, focus validation, undo fallback.

### D04 Window Management (90 skills)

Families:

1. **Window lifecycle**: open, close, quit, force quit, relaunch, restart crashed app.
2. **Focus**: activate app, focus window, focus control, resolve focus stealing.
3. **Layout**: minimize, maximize, restore, snap, tile, cascade, resize.
4. **Positioning**: move window, move to monitor, center, align, remember position.
5. **Virtual desktops**: create, switch, move window, detect current desktop.
6. **Multi-monitor**: detect displays, DPI scaling, primary monitor, app placement.
7. **State detection**: frozen app, busy app, loading app, hidden app, modal blocking.
8. **Presentation control**: full screen, always on top, transparency, dark/light mode.
9. **App discovery**: installed apps, running apps, process mapping, window-to-process.
10. **Verification**: window visible, app ready, title match, bounds match, process healthy.

### D05 File System (150 skills)

Families:

1. **Basic operations**: create, copy, move, rename, delete-to-trash, restore.
2. **Search**: name search, content search, metadata search, fuzzy search, duplicate detection.
3. **Organization**: sort by type, date, project, sender, content, semantic topic.
4. **Archives**: zip, unzip, tar, rar, 7z, password archives, validate archive.
5. **Metadata**: timestamps, ownership, permissions, tags, comments, EXIF, document properties.
6. **Sync**: local sync, cloud sync, folder mirror, conflict detection, offline queue.
7. **Backup**: snapshot, incremental backup, restore point, verify backup integrity.
8. **Encryption**: encrypt file, decrypt file, secure archive, keychain integration.
9. **File conversion**: PDF, images, docs, spreadsheets, audio, video, Markdown.
10. **Disk analysis**: size report, temp cleanup, large files, old files, unused installers.
11. **Document extraction**: PDF text, tables, forms, images, annotations, signatures.
12. **Naming systems**: invoice naming, project naming, date normalization, slug generation.
13. **Watchers**: folder watch, auto-classify, trigger workflow, debounce changes.
14. **Safety**: collision handling, dry run, rollback manifest, checksum verification.
15. **Sharing**: local share links, cloud links, permission checks, expiry settings.

### D06 Browser Automation (120 skills)

Families:

1. **Navigation**: open URL, back, forward, reload, wait for load, detect redirects.
2. **Tabs**: new tab, close tab, switch tab, group tabs, search tabs, restore tab.
3. **Forms**: fill text, choose select, checkbox, radio, date picker, file upload.
4. **Authentication**: login flow, logout, MFA prompt detection, session check.
5. **DOM extraction**: text, tables, links, images, forms, ARIA tree, structured data.
6. **Downloads**: start download, monitor download, verify file, rename download.
7. **Uploads**: file picker, drag upload, multi-file upload, progress verification.
8. **Cookies/cache**: inspect cookies, clear cache, profile isolation, permission reset.
9. **Bookmarks/history**: create bookmark, search history, export bookmark, folder organize.
10. **Screenshots/PDF**: viewport screenshot, full-page screenshot, save as PDF.
11. **JavaScript execution**: read state, trigger events, extract app data, test selectors.
12. **Browser recovery**: stale DOM, blocked popups, consent dialogs, captcha detection.

### D07 Application Skills (150 skills)

Families:

1. **VS Code**: open project, edit file, terminal command, extensions, debugger, search.
2. **Office documents**: Word docs, Excel sheets, PowerPoint decks, comments, export.
3. **PDF tools**: annotate, sign, split, merge, compress, OCR, redact.
4. **Design tools**: Figma inspect/export, Adobe basics, image editors, asset export.
5. **CAD and technical tools**: file open, export, layer visibility, measurement.
6. **Media editors**: import, cut, export, caption, compress, format conversion.
7. **Database clients**: connect, query, export, schema inspect, migration run.
8. **IDEs**: JetBrains, Visual Studio, Android Studio, Xcode, project build.
9. **App install/update/remove**: package managers, installers, uninstallers, version checks.
10. **Health monitoring**: app CPU/memory, logs, crash reports, update state.
11. **Notes and knowledge apps**: Obsidian, Notion, OneNote, local Markdown vaults.
12. **Terminal apps**: shells, multiplexers, SSH sessions, command history.
13. **Messaging apps**: WhatsApp Desktop, Slack, Teams, Discord, Telegram.
14. **Finance/admin apps**: invoice tools, banking portals, tax tools, ERP clients.
15. **App-specific macro packs**: repeatable sequences for known UI workflows.

### D08 Developer Skills (120 skills)

Families:

1. **Git**: status, diff, branch, commit, merge, rebase, stash, tag, blame.
2. **GitHub/GitLab**: issues, PRs, reviews, Actions, releases, project boards.
3. **Package managers**: npm, pnpm, yarn, pip, poetry, uv, cargo, go, maven, gradle.
4. **Build systems**: Make, CMake, Vite, Webpack, Turborepo, Nx, Bazel.
5. **Testing**: unit, integration, e2e, snapshot, coverage, flaky test triage.
6. **Docker**: build, run, compose, logs, exec, inspect, prune, registry.
7. **Kubernetes**: pods, deployments, services, logs, port-forward, rollout.
8. **SSH/remote**: connect, copy files, run commands, tunnel, key management.
9. **Databases**: SQL query, migrations, backups, restores, performance explain.
10. **APIs**: HTTP requests, OpenAPI, auth, webhook testing, payload validation.
11. **Observability**: logs, traces, metrics, alerts, dashboards, error reports.
12. **Code intelligence**: search, refactor, dependency graph, code review, docs.

### D09 Communication (80 skills)

Families:

1. **Email**: read, draft, summarize, label, search, attachments, send approval.
2. **Chat**: read, reply, summarize, thread handling, reactions, mention tracking.
3. **Calendar**: create, update, RSVP, schedule, availability, reminders.
4. **Contacts**: lookup, dedupe, enrich, group, relationship notes.
5. **Meetings**: join, mute, screen share, notes, transcription, action items.
6. **Notifications**: triage, silence, priority detection, digest creation.
7. **Voice**: dictation, TTS, call assistant, voicemail summary.
8. **Collaboration docs**: comments, suggestions, change summaries, approvals.

### D10 AI Planning (100 skills)

Families:

1. **Intent parsing**: classify goal, extract entities, detect constraints, infer context.
2. **Planning**: task graph, dependency graph, milestones, fallback branches.
3. **Skill routing**: registry search, capability match, cost/risk scoring.
4. **Execution control**: step runner, pause, resume, cancel, checkpoint.
5. **Reflection**: assess progress, compare plan vs result, identify failure.
6. **Memory**: user preferences, workflow memory, project memory, episodic notes.
7. **Retry**: alternate selector, alternate app path, backoff, rollback.
8. **Verification**: visual, DOM, API, file, process, test, user confirmation.
9. **Cost estimation**: time, tokens, API calls, risk, compute, network usage.
10. **Multi-agent**: delegate, coordinate, merge results, resolve conflicts.

### D11 Security (80 skills)

Families:

1. **Permissions**: prompt, policy, scope, duration, revocation, pre-approval.
2. **Secrets**: detect secrets, mask secrets, keychain, env vars, vault integration.
3. **Audit**: action log, screenshot evidence, command log, approval log.
4. **Rollback**: file rollback, settings rollback, task checkpoint restore.
5. **Sandboxing**: process sandbox, browser profile isolation, temp workspace.
6. **Risk detection**: destructive action, financial action, external send, credential entry.
7. **Privacy**: PII detection, local-only mode, redact before model call.
8. **Emergency controls**: stop button, kill task, revoke tokens, freeze automation.

### D12 Enterprise (150 skills)

Families:

1. **Microsoft 365**: Outlook, Teams, SharePoint, OneDrive, Excel, Word, PowerPoint.
2. **Google Workspace**: Gmail, Calendar, Drive, Docs, Sheets, Slides, Meet.
3. **Atlassian**: Jira, Confluence, Bitbucket, Rovo, sprint reports.
4. **CRM**: Salesforce, HubSpot, Zoho, lead update, opportunity reports.
5. **ITSM**: ServiceNow, Zendesk, Freshservice, ticket triage, SLA checks.
6. **ERP**: SAP, Oracle, NetSuite, approvals, exports, reconciliation.
7. **BI/reporting**: Power BI, Tableau, Looker, dashboard extraction, alerts.
8. **Compliance**: access review, evidence collection, policy checks, audit exports.
9. **Approval workflows**: request approval, track state, escalate, record decision.
10. **Identity/admin**: Okta, Entra ID, user provisioning, group membership.
11. **Finance ops**: invoices, purchase orders, expenses, payment status.
12. **HR ops**: onboarding, offboarding, leave, payroll exports.
13. **Procurement**: vendor data, contracts, renewals, quote comparison.
14. **Customer support**: ticket summarization, reply drafts, sentiment, routing.
15. **Enterprise search**: cross-app search, permission-aware retrieval, source citation.

---

## 3. Modular System Architecture

### 3.1 High-Level Pipeline

```text
Natural Language Input
  -> Intent Parser
  -> Planner
  -> Task Graph
  -> Policy & Permission Gate
  -> Skill Registry
  -> Execution Engine
  -> OS APIs / UI Automation / Browser / App Connectors
  -> Vision Verification
  -> Self-Correction Loop
  -> Audit Log / Memory / User Feedback
```

### 3.2 Core Modules

#### 3.2.1 Interaction Layer

**Responsibilities**

- Accept chat, voice, hotkey, command palette, and scheduled triggers.
- Display task plan, progress, approvals, and results.
- Support pause/resume/cancel.

**Interfaces**

- `POST /tasks`
- `GET /tasks/:id`
- `POST /tasks/:id/approve`
- `POST /tasks/:id/cancel`

#### 3.2.2 Intent Parser

**Responsibilities**

- Convert natural language into structured intent.
- Extract target apps, files, people, dates, constraints, risk level.
- Detect ambiguity.

**Output**

```json
{
  "intent": "organize_files",
  "entities": {
    "source_folder": "Downloads",
    "file_types": ["pdf", "docx"],
    "strategy": "semantic"
  },
  "constraints": {
    "ask_before_delete": true
  },
  "risk_level": 1
}
```

#### 3.2.3 Planner

**Responsibilities**

- Convert intent into task graph.
- Choose skill candidates.
- Add verification nodes.
- Add rollback/checkpoint nodes for risky steps.

#### 3.2.4 Task Graph Engine

**Responsibilities**

- Execute DAG nodes.
- Track state.
- Retry failed nodes.
- Resume from checkpoint.
- Support parallel execution when safe.

**Node types**

- `observe`
- `decide`
- `act`
- `verify`
- `rollback`
- `ask_user`
- `summarize`

#### 3.2.5 Skill Registry

**Responsibilities**

- Store skill metadata.
- Version skills.
- Match capabilities to tasks.
- Track reliability and risk.
- Support install/update/remove.

#### 3.2.6 Perception Engine

**Responsibilities**

- Capture screen.
- Parse OCR.
- Read accessibility tree.
- Detect UI elements.
- Merge visual and accessibility signals.
- Produce actionable UI state.

#### 3.2.7 Action Engine

**Responsibilities**

- Mouse operations.
- Keyboard operations.
- OS APIs.
- Browser protocol operations.
- App connector operations.
- File system operations.

#### 3.2.8 Verification Engine

**Responsibilities**

- Confirm each action had intended effect.
- Compare before/after state.
- Detect errors and unexpected UI.
- Trigger retry or planner correction.

#### 3.2.9 Policy Engine

**Responsibilities**

- Evaluate permissions.
- Detect sensitive actions.
- Require approval.
- Enforce app/file/domain boundaries.
- Log all decisions.

#### 3.2.10 Memory Engine

**Responsibilities**

- Store user preferences.
- Remember repeat workflows.
- Maintain app-specific learned procedures.
- Track failed attempts and successful patterns.

#### 3.2.11 Connector Layer

**Connector types**

- OS connector.
- Browser connector.
- Files connector.
- App connector.
- Cloud SaaS connector.
- Enterprise connector.
- Developer tool connector.

#### 3.2.12 Observability Layer

**Responsibilities**

- Structured logs.
- Screenshots at key states.
- Action replay trace.
- Metrics.
- Error reports.
- User-visible task report.

---

## 4. MVP Roadmap

### Phase 0: Foundation (2–3 weeks)

**Goals**

- Build local agent shell.
- Define task model.
- Implement permission model.
- Implement basic logging.
- Build skill registry schema.

**Deliverables**

- Desktop tray or command palette.
- Natural-language task intake.
- Task graph executor.
- Local SQLite/Postgres database.
- Basic audit log.

### Phase 1: Local Desktop Automation (4–6 weeks)

**Goals**

- Control mouse and keyboard.
- Read screenshots and accessibility tree.
- Manage windows.
- Perform file operations safely.

**Deliverables**

- Screenshot capture.
- OCR integration.
- Accessibility parser.
- Mouse/keyboard automation.
- File organizer workflows.
- Visual verification loop.

**MVP demos**

- Organize Downloads.
- Rename files from content.
- Extract table from screenshot/PDF.
- Open app and perform simple UI flow.

### Phase 2: Browser Automation (4–6 weeks)

**Goals**

- Automate browser workflows reliably.
- Use DOM plus vision fallback.
- Support downloads, uploads, and forms.

**Deliverables**

- Playwright/CDP integration.
- Browser profile management.
- Form filling.
- DOM extraction.
- Download verification.
- Login-state detection.

**MVP demos**

- Download report from website.
- Fill web form.
- Extract dashboard table.
- Save webpage as PDF.

### Phase 3: Developer Assistant (4–8 weeks)

**Goals**

- Support coding workflows.
- Integrate with Git, VS Code, terminal, tests.

**Deliverables**

- Repo inspection.
- Code edit pipeline.
- Test runner.
- Git operations.
- Commit creation.
- PR summary generation.

**MVP demos**

- Fix failing test.
- Add feature in existing repo.
- Review diff.
- Generate docs.

### Phase 4: Communication & Scheduling (4–6 weeks)

**Goals**

- Support email, chat, and calendar with approval gates.

**Deliverables**

- Email read/summarize/draft.
- Calendar lookup and scheduling.
- Meeting notes workflow.
- Chat summarization.

**MVP demos**

- Summarize unread important emails.
- Draft reply for approval.
- Create calendar event.
- Summarize meeting transcript.

### Phase 5: Enterprise & Skill Marketplace (8–12 weeks)

**Goals**

- Add enterprise integrations and reusable skill packs.

**Deliverables**

- Skill package format.
- Connector marketplace.
- Admin policy controls.
- Enterprise audit exports.
- Role-based permissions.

**MVP demos**

- Jira ticket triage.
- Salesforce update draft.
- ServiceNow ticket summary.
- Compliance evidence collection.

---

## 5. Technical Implementation Plan

### 5.1 Recommended Stack

**Frontend**

- Tauri, Electron, or native Windows UI.
- React for task panel and command center.

**Backend**

- TypeScript/Node.js for orchestration and connectors.
- Python for OCR/CV/ML-heavy perception modules if needed.
- Rust or native modules for low-level OS integration if performance requires it.

**Database**

- SQLite for local MVP.
- Postgres for team/enterprise edition.
- Vector index for semantic skill and memory search.

**Automation**

- Windows UI Automation API.
- Playwright or Chrome DevTools Protocol.
- OS input APIs.
- Filesystem APIs.

**AI**

- LLM for intent parsing, planning, summarization, code tasks.
- OCR engine for visual text.
- Vision model for screenshot understanding.
- Embeddings for semantic retrieval.

### 5.2 Repository Structure

```text
desktop-agent/
  apps/
    desktop-client/
    agent-service/
  packages/
    core/
    planner/
    task-graph/
    skill-registry/
    perception/
    action-engine/
    verification/
    policy/
    memory/
    connectors/
    ui-automation/
    browser-automation/
    filesystem/
    devtools/
  skills/
    vision/
    mouse/
    keyboard/
    windows/
    files/
    browser/
    developer/
    communication/
    enterprise/
  docs/
    architecture.md
    skill-format.md
    security.md
```

### 5.3 Execution Flow

1. User submits task.
2. Intent parser returns structured intent.
3. Planner creates task graph.
4. Policy engine evaluates risk.
5. User approves risky actions.
6. Executor runs graph nodes.
7. Perception engine observes current state.
8. Skill runs action.
9. Verification engine confirms outcome.
10. On failure, planner retries or asks user.
11. Final report is generated.
12. Useful workflow patterns are saved to memory.

### 5.4 Task Graph Example

```json
{
  "task_id": "task_001",
  "goal": "Organize Downloads folder",
  "nodes": [
    { "id": "n1", "type": "observe", "skill": "filesystem.list_folder" },
    { "id": "n2", "type": "decide", "skill": "files.classify_by_content" },
    { "id": "n3", "type": "act", "skill": "filesystem.create_folders" },
    { "id": "n4", "type": "act", "skill": "filesystem.move_files" },
    { "id": "n5", "type": "verify", "skill": "filesystem.verify_manifest" },
    { "id": "n6", "type": "summarize", "skill": "report.task_summary" }
  ]
}
```

### 5.5 Skill Runtime Contract

```ts
type SkillInput = {
  taskId: string;
  parameters: Record<string, unknown>;
  context: AgentContext;
  permissions: PermissionGrant[];
};

type SkillResult = {
  status: "success" | "failed" | "needs_user" | "blocked";
  output?: Record<string, unknown>;
  evidence?: Evidence[];
  error?: {
    code: string;
    message: string;
    recoverable: boolean;
  };
};
```

### 5.6 Verification Strategy

Use layered verification:

- **File operations**: path exists, checksum, manifest.
- **Browser actions**: DOM state, URL, network state, screenshot.
- **UI actions**: accessibility state, screenshot diff, OCR text.
- **Developer tasks**: tests pass, lint passes, git diff matches goal.
- **Communication**: draft exists, recipient matches, approval captured before send.

### 5.7 Safety Strategy

- Dry-run mode for file and enterprise workflows.
- Trash instead of permanent delete.
- Approval gates for external sends and destructive actions.
- Screenshot evidence for high-risk actions.
- Rollback manifests for local changes.
- Redaction before external model calls.
- Emergency stop hotkey.

### 5.8 Model Strategy

- Small fast model for intent classification and routing.
- Strong reasoning model for planning and code changes.
- Vision model for screenshots.
- Embedding model for memory and skill retrieval.
- Optional local models for privacy-sensitive OCR/classification.

### 5.9 Testing Strategy

- Unit tests for skill inputs/outputs.
- Golden tests for intent parsing.
- Simulated UI tests for mouse/keyboard/window skills.
- Browser e2e tests with Playwright.
- File operation tests in sandbox folders.
- Regression test corpus for screenshots.
- Security tests for policy enforcement.

---

## 6. Database Schema For Skill Registry

### 6.1 Core Tables

```sql
CREATE TABLE skills (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  domain TEXT NOT NULL,
  category TEXT NOT NULL,
  description TEXT NOT NULL,
  version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  risk_level INTEGER NOT NULL DEFAULT 0,
  platforms TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE skill_inputs (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL REFERENCES skills(id),
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  required INTEGER NOT NULL DEFAULT 0,
  description TEXT,
  default_value TEXT
);

CREATE TABLE skill_outputs (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL REFERENCES skills(id),
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  description TEXT
);

CREATE TABLE skill_dependencies (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL REFERENCES skills(id),
  dependency_type TEXT NOT NULL,
  dependency_name TEXT NOT NULL,
  version_constraint TEXT
);

CREATE TABLE skill_verification_methods (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL REFERENCES skills(id),
  method_type TEXT NOT NULL,
  method_config TEXT NOT NULL
);

CREATE TABLE skill_permissions (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL REFERENCES skills(id),
  permission_scope TEXT NOT NULL,
  permission_level INTEGER NOT NULL,
  approval_required INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE skill_runs (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL REFERENCES skills(id),
  task_id TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  input_json TEXT NOT NULL,
  output_json TEXT,
  error_json TEXT
);

CREATE TABLE skill_metrics (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL REFERENCES skills(id),
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  average_duration_ms INTEGER,
  last_success_at TEXT,
  last_failure_at TEXT
);
```

### 6.2 Task Tables

```sql
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  user_goal TEXT NOT NULL,
  status TEXT NOT NULL,
  risk_level INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE task_nodes (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  node_type TEXT NOT NULL,
  skill_id TEXT REFERENCES skills(id),
  status TEXT NOT NULL,
  depends_on TEXT,
  input_json TEXT,
  output_json TEXT,
  error_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE approvals (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  node_id TEXT REFERENCES task_nodes(id),
  permission_scope TEXT NOT NULL,
  prompt TEXT NOT NULL,
  decision TEXT,
  decided_at TEXT,
  evidence_json TEXT
);

CREATE TABLE evidence (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  node_id TEXT REFERENCES task_nodes(id),
  evidence_type TEXT NOT NULL,
  uri TEXT,
  content_hash TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);
```

### 6.3 Memory Tables

```sql
CREATE TABLE memories (
  id TEXT PRIMARY KEY,
  memory_type TEXT NOT NULL,
  scope TEXT NOT NULL,
  content TEXT NOT NULL,
  embedding_id TEXT,
  confidence REAL NOT NULL DEFAULT 1.0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  expires_at TEXT
);

CREATE TABLE workflow_templates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  trigger_pattern TEXT,
  task_graph_json TEXT NOT NULL,
  usage_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 6.4 Example Skill Record

```json
{
  "id": "browser.form.fill_text",
  "name": "Fill Browser Text Field",
  "domain": "browser_automation",
  "category": "forms",
  "description": "Find and fill a text input in a browser page using DOM selectors with visual fallback.",
  "version": "1.0.0",
  "risk_level": 1,
  "platforms": ["windows", "macos", "linux"],
  "inputs": [
    { "name": "field_hint", "type": "string", "required": true },
    { "name": "value", "type": "string", "required": true }
  ],
  "outputs": [
    { "name": "filled", "type": "boolean" },
    { "name": "field_identifier", "type": "string" }
  ],
  "verification": ["dom_value_match", "screenshot_ocr_optional"]
}
```

---

## 7. Investor-Style Vision Document

### 7.1 One-Liner

A local-first AI operator that can understand, control, and verify work across the entire desktop.

### 7.2 Problem

Modern work is fragmented across browser tabs, desktop apps, files, messages, meetings, dashboards, and developer tools. People waste hours on repetitive coordination: moving data, renaming files, filling forms, checking dashboards, updating tickets, and switching contexts.

Current AI assistants can answer questions, but most cannot reliably operate the actual computer. Traditional RPA can automate repetitive workflows, but it is brittle, expensive, and hard to adapt.

### 7.3 Solution

Desktop AI Agent Platform combines natural-language planning, screen perception, OS automation, browser control, app connectors, and verification into one agent runtime.

Users give goals. The agent decomposes them into task graphs, selects skills from a growing registry, acts through the safest available interface, verifies results, and asks for approval when needed.

### 7.4 Why Now

- Vision-language models can understand UI screenshots.
- Browser automation and accessibility APIs are mature.
- Developers and enterprises are actively adopting AI agents.
- Knowledge work is increasingly app-fragmented.
- Local-first privacy is becoming a competitive advantage.

### 7.5 Market

**Initial wedge**

- Developers and AI builders.
- Technical operators.
- Founder-led teams.
- Power users.

**Expansion**

- SMB automation.
- Enterprise RPA replacement.
- IT operations.
- Finance/admin operations.
- Customer support operations.

### 7.6 Differentiation

- Works across the actual desktop, not only inside one SaaS app.
- Combines APIs, DOM, accessibility, vision, and OS input.
- Verification-first architecture.
- Skill registry scales from atomic actions to complex workflows.
- Local-first security posture.
- Human approval built into sensitive operations.

### 7.7 Moat

- Growing skill registry.
- Real-world workflow traces.
- App-specific recovery patterns.
- Permission and safety framework.
- Enterprise connector ecosystem.
- User-specific workflow memory.

### 7.8 Business Model

Possible pricing:

- Free local developer edition.
- Pro subscription for power users.
- Team plan with shared skill packs.
- Enterprise plan with admin controls, audit logs, and private deployment.
- Marketplace revenue share for premium skills/connectors.

### 7.9 12-Month Milestones

**Months 1–3**

- MVP desktop agent.
- File, browser, and developer workflows.
- 100 high-quality skills.

**Months 4–6**

- Communication workflows.
- Skill marketplace alpha.
- Team workspace support.
- 300+ skills.

**Months 7–9**

- Enterprise connectors.
- Admin policy engine.
- Workflow analytics.
- 700+ skills.

**Months 10–12**

- Enterprise pilot customers.
- 1,000+ skills.
- App-specific workflow packs.
- Private deployment option.

### 7.10 Strategic Narrative

The next interface for computers is not another dashboard. It is an operator layer: an AI system that can see the state of work, choose the right tool, perform the action, verify the result, and learn the workflow.

Desktop AI Agent Platform turns the computer itself into the execution environment for AI.

---

## 8. Recommended Immediate Build Order

1. Define skill schema and task graph schema.
2. Build local task executor.
3. Add file system skills with dry-run and rollback.
4. Add screenshot capture and OCR.
5. Add accessibility tree parsing.
6. Add mouse/keyboard/window automation.
7. Add browser automation through Playwright/CDP.
8. Add verification engine.
9. Add permission prompts and audit logs.
10. Package first 50 MVP workflows.

---

## 9. MVP Skill Pack

Start with these 50 skills:

| # | Skill ID | Domain |
|--:|----------|--------|
| 1 | `task.create` | Task control |
| 2 | `task.pause` | Task control |
| 3 | `task.resume` | Task control |
| 4 | `task.cancel` | Task control |
| 5 | `policy.request_approval` | Policy |
| 6 | `policy.check_risk` | Policy |
| 7 | `screen.capture` | Vision |
| 8 | `screen.ocr` | Vision |
| 9 | `screen.find_text` | Vision |
| 10 | `screen.find_button` | Vision |
| 11 | `accessibility.read_tree` | Vision |
| 12 | `accessibility.find_node` | Vision |
| 13 | `mouse.click` | Mouse |
| 14 | `mouse.double_click` | Mouse |
| 15 | `mouse.drag` | Mouse |
| 16 | `mouse.scroll` | Mouse |
| 17 | `keyboard.type_text` | Keyboard |
| 18 | `keyboard.hotkey` | Keyboard |
| 19 | `keyboard.copy` | Keyboard |
| 20 | `keyboard.paste` | Keyboard |
| 21 | `window.list` | Window |
| 22 | `window.focus` | Window |
| 23 | `window.move` | Window |
| 24 | `window.resize` | Window |
| 25 | `window.close` | Window |
| 26 | `filesystem.list_folder` | Files |
| 27 | `filesystem.create_folder` | Files |
| 28 | `filesystem.move_file` | Files |
| 29 | `filesystem.copy_file` | Files |
| 30 | `filesystem.trash_file` | Files |
| 31 | `filesystem.rename_file` | Files |
| 32 | `filesystem.search` | Files |
| 33 | `filesystem.checksum` | Files |
| 34 | `filesystem.create_manifest` | Files |
| 35 | `filesystem.rollback_manifest` | Files |
| 36 | `browser.open` | Browser |
| 37 | `browser.navigate` | Browser |
| 38 | `browser.extract_dom` | Browser |
| 39 | `browser.fill_form` | Browser |
| 40 | `browser.click_selector` | Browser |
| 41 | `browser.download_file` | Browser |
| 42 | `browser.upload_file` | Browser |
| 43 | `browser.screenshot` | Browser |
| 44 | `dev.git_status` | Developer |
| 45 | `dev.git_diff` | Developer |
| 46 | `dev.run_tests` | Developer |
| 47 | `dev.edit_file` | Developer |
| 48 | `dev.commit` | Developer |
| 49 | `verify.file_exists` | Verification |
| 50 | `report.task_summary` | Reporting |

---

## 10. Summary

This product should be built as a verified execution platform, not a simple chatbot or macro recorder. The core bet is that a skill registry plus perception plus permissioned task execution can make desktop automation reliable enough for real work.

The best MVP is narrow but deep:

- Files.
- Browser.
- Developer workflows.
- Screenshot/accessibility perception.
- Verification.
- Safety.

After that, the system can expand into communication, enterprise workflows, and a marketplace of reusable skills.
