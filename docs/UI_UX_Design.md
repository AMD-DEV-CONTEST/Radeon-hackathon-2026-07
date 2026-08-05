# THEMIS — UI/UX Design Document
## Version 1.0 | AMD AI DevMaster Hackathon | July 20, 2026

---

## 1. Design Philosophy

THEMIS's UI must accomplish two things simultaneously:
1. **Function:** A developer must be able to submit a PR and read a report efficiently
2. **Impress:** A hackathon judge watching a 5-minute demo must be wowed in the first 30 seconds

### Design Principles

**1. Tribunal Aesthetic** — Dark, authoritative, precise. THEMIS is a judge, not a chatbot. The visual language should feel like a courtroom crossed with a mission control room.

**2. Live Intelligence** — The UI is never static. Agent activity pulses, streams, and animates in real time. Idle states are minimized.

**3. Evidence-Based** — Every finding on screen has a citation badge. Nothing appears without authority.

**4. GPU Visibility** — AMD hardware performance is always one click away. The benchmark panel is a first-class citizen, not an afterthought.

---

## 2. Design System

### Color Palette

```css
:root {
  /* Background hierarchy */
  --bg-void:       #080B0F;   /* Page background — near-black */
  --bg-surface:    #0D1117;   /* Card / panel surfaces */
  --bg-elevated:   #161B22;   /* Elevated surfaces, modals */
  --bg-hover:      #1C2333;   /* Hover states */

  /* AMD Brand — Primary accent */
  --amd-red:       #ED1C24;   /* AMD logo red — use sparingly */
  --amd-glow:      rgba(237, 28, 36, 0.15);  /* Red glow for active states */

  /* Themis accent — Justice gold */
  --gold-primary:  #D4A017;   /* Primary accent — Themis gold */
  --gold-muted:    #8A6914;   /* Muted gold — secondary UI */
  --gold-glow:     rgba(212, 160, 23, 0.12); /* Gold ambient glow */

  /* Agent status colors */
  --agent-idle:    #30363D;   /* Inactive agent */
  --agent-active:  #1F6FEB;   /* Processing — electric blue */
  --agent-done:    #238636;   /* Complete — confident green */
  --agent-error:   #DA3633;   /* Error — alert red */

  /* Finding severity */
  --sev-critical:  #FF3B30;
  --sev-high:      #FF9500;
  --sev-medium:    #FFD60A;
  --sev-low:       #30D158;
  --sev-info:      #636E7B;

  /* Text */
  --text-primary:  #E6EDF3;
  --text-secondary:#8B949E;
  --text-muted:    #484F58;
  --text-code:     #79C0FF;   /* Inline code text */

  /* Borders */
  --border-default: #30363D;
  --border-muted:   #21262D;
  --border-active:  #D4A017;  /* Gold border for selected/active */
}
```

### Typography

```css
/* Import from Google Fonts */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --font-sans: 'Inter', -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;

  /* Scale */
  --text-xs:   0.75rem;   /* 12px — metadata, badges */
  --text-sm:   0.875rem;  /* 14px — body, labels */
  --text-base: 1rem;      /* 16px — default */
  --text-lg:   1.125rem;  /* 18px — section headers */
  --text-xl:   1.25rem;   /* 20px — card titles */
  --text-2xl:  1.5rem;    /* 24px — page section headers */
  --text-3xl:  1.875rem;  /* 30px — page title */
  --text-4xl:  2.25rem;   /* 36px — hero */
}
```

### Spacing & Radius

```css
:root {
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;
  --space-12: 48px;

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
  --radius-full: 9999px;
}
```

### Glassmorphism Tokens

```css
.glass-panel {
  background: rgba(13, 17, 23, 0.80);
  backdrop-filter: blur(12px) saturate(1.2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
}

.glass-panel--active {
  border-color: var(--border-active);
  box-shadow: 0 0 20px var(--gold-glow), 0 0 40px rgba(212, 160, 23, 0.05);
}
```

---

## 3. Navigation Structure

```
THEMIS
├── / (Dashboard)           — Input: GitHub PR URL or file upload
├── /tribunal               — Live 5-agent trace view
├── /report/:jobId          — Structured findings report
└── /benchmark              — ROCm performance panel
```

**Nav bar (always visible):**
- Left: THEMIS logo (Θ glyph) + wordmark
- Center: Tab navigation (Dashboard | Benchmark)
- Right: GPU status pill (always shows VRAM usage + tok/s live)

---

## 4. Page Designs

---

### Page 1 — Dashboard (`/`)

**Purpose:** Primary entry point. Submit a PR or upload files.

```
┌────────────────────────────────────────────────────────────────┐
│ THEMIS                [Dashboard] [Benchmark]   [●GPU 40.1GB ▲47t/s] │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│         ┌──────────────────────────────────────────┐          │
│         │   Θ  THEMIS                              │          │
│         │   The AI Code Review Tribunal            │          │
│         │   Powered by AMD Radeon PRO W7900D        │          │
│         └──────────────────────────────────────────┘          │
│                                                                │
│   ┌──── Mode Toggle ──────────────────────────────────────┐   │
│   │  [ GitHub PR ▼ ]    [ File Upload ]                   │   │
│   └───────────────────────────────────────────────────────┘   │
│                                                                │
│   ── GitHub PR Mode ──────────────────────────────────────    │
│   ┌───────────────────────────────────────────────────────┐   │
│   │  🔗  https://github.com/owner/repo/pull/42            │   │
│   └───────────────────────────────────────────────────────┘   │
│                                                                │
│   ── Analysis Scope (checkboxes) ─────────────────────────    │
│   [✓] Security Analysis    [✓] Style Review    [✓] Auto-Fix   │
│                                                                │
│   ┌─────────────────────────────────────────────────────┐     │
│   │     ⚖  CONVENE THE TRIBUNAL  →                     │     │
│   └─────────────────────────────────────────────────────┘     │
│         (AMD red gradient button, pulsing on hover)            │
│                                                                │
│   ── Recent Reviews ───────────────────────────────────────   │
│   ┌─────────────────────────────────────────────────────┐     │
│   │ owner/repo #38  │ 2 Critical 3 High  │ 87s │ View → │     │
│   │ owner/repo #35  │ 0 Critical 1 High  │ 43s │ View → │     │
│   └─────────────────────────────────────────────────────┘     │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Key interactions:**
- URL input: real-time repo validity check (green ring when valid GitHub PR URL detected)
- Mode toggle: slides between GitHub PR and File Upload with smooth spring animation
- File Upload mode: large drag-and-drop zone with file type icons (.py, .js, .ts, .go, .java)
- "Convene Tribunal" button: AMD-red gradient, shimmer animation on hover, pressing it navigates to `/tribunal`
- GPU pill in nav: live updates every 2 seconds via polling the `/health` endpoint

---

### Page 2 — Tribunal View (`/tribunal`)

**Purpose:** Real-time visualization of the 5-agent pipeline. This is the 30-second hook.

```
┌────────────────────────────────────────────────────────────────┐
│ THEMIS                [Dashboard] [Benchmark]   [●GPU 40.1GB ▲47t/s] │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  PR: owner/repo #42  — "Add user authentication module"        │
│  38 files changed   +1,247 / -89 lines                        │
│                                                                │
│  ┌──────────────────── TRIBUNAL PANEL ────────────────────┐   │
│  │                                                        │   │
│  │  ① TRIAGE          ▓▓▓▓▓▓▓▓▓▓░░░░░░░░░  COMPLETE  ✓  │   │
│  │    "Identified 38 files — 12 high-risk"               │   │
│  │                                                        │   │
│  │  ② SECURITY        ▓▓▓▓▓▓▓▓░░░░░░░░░░  ANALYZING ●  │   │
│  │    "Running Semgrep on auth.py..."                     │   │
│  │    ↳ Tool: semgrep p/owasp-top-ten [running]          │   │
│  │                                                        │   │
│  │  ③ STYLE           ░░░░░░░░░░░░░░░░░░  WAITING    ○  │   │
│  │                                                        │   │
│  │  ④ VERIFIER        ░░░░░░░░░░░░░░░░░░  WAITING    ○  │   │
│  │                                                        │   │
│  │  ⑤ FIX             ░░░░░░░░░░░░░░░░░░  WAITING    ○  │   │
│  │                                                        │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌──────────── LIVE REASONING STREAM ───────────────────┐     │
│  │                                              [CLEAR]  │     │
│  │  12:14:07  [TRIAGE]    Parsing diff structure...      │     │
│  │  12:14:08  [TRIAGE]    Detected: Python (24), JS (8)  │     │
│  │  12:14:09  [TRIAGE]    High-risk: auth.py, jwt_util.py│     │
│  │  12:14:10  [SECURITY]  Launching Semgrep container... │     │
│  │  12:14:12  [SECURITY]  Semgrep: 3 findings in auth.py │     │
│  │  ▌                                                    │     │
│  └──────────────────────────────────────────────────────┘     │
│                                                                │
│  ┌── Stats ──────┐  ┌── Findings So Far ─────────────────┐    │
│  │  Time: 0:47   │  │  🔴 Critical: 2  🟠 High: 1        │    │
│  │  Tokens: 4820 │  │  🟡 Medium: 0   🟢 Low: 0          │    │
│  │  Tok/s: 48.2  │  │  [View Report →]                   │    │
│  └───────────────┘  └─────────────────────────────────────┘   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Key interactions:**
- Agent cards: animated progress bars, status pill (WAITING / ANALYZING / COMPLETE / ERROR)
- Active agent: glows with AMD-red pulsing border + the agent name vibrates subtly (framer-motion)
- Parallel agents (Security + Style): both animate simultaneously
- Live reasoning stream: monospace font, auto-scroll, timestamps
- Stats: real-time updates via WebSocket
- Finding counters: increment with pop animation when new findings arrive
- When pipeline completes: dramatic fade from tribunal panel → "VERDICT READY" with gavel animation → redirect to Report View after 2s

---

### Page 3 — Report View (`/report/:jobId`)

**Purpose:** Display structured findings. The deliverable a developer acts on.

```
┌────────────────────────────────────────────────────────────────┐
│ THEMIS  ◄ Back          [Dashboard] [Benchmark]  [●GPU 40.1GB] │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  📋  VERDICT: owner/repo #42                    [⬇ Export PDF] │
│  Completed in 87.3s  │  38 files  │  Tokens: 14,820           │
│                                                                │
│  ┌──── Summary Bar ─────────────────────────────────────────┐  │
│  │  🔴 2 Critical   🟠 4 High   🟡 3 Medium   🟢 1 Low      │  │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │  │
│  │  Confidence filter: 3 low-confidence findings hidden      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── Filters ──────────────────────────────────────────────┐   │
│  │  [All] [Security] [Style]  │  [Critical] [High] [All]   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌── Finding Card ─────────────────────────────────────────┐   │
│  │  🔴 CRITICAL    SQL Injection Risk          [CWE-89]    │   │
│  │                                          [OWASP A03]    │   │
│  │  📄 auth/db.py : Lines 47–52             Confidence 0.94 │   │
│  │  ─────────────────────────────────────────────────────  │   │
│  │  "Unsanitized user input directly interpolated into SQL  │   │
│  │  query string. Attacker can exfiltrate entire database   │   │
│  │  via UNION injection."                                   │   │
│  │                                                          │   │
│  │  ┌── Code Diff ──────────────────────────────────────┐  │   │
│  │  │ - query = f"SELECT * FROM users WHERE id={user_id}" │  │   │
│  │  │ + query = "SELECT * FROM users WHERE id = %s"       │  │   │
│  │  │ + cursor.execute(query, (user_id,))                  │  │   │
│  │  └────────────────────────────────────────────────────┘  │   │
│  │                                                          │   │
│  │  📚 RAG Citation: CWE-89 — "SQL injection is one of..."  │   │
│  │                                                          │   │
│  │  Source: Semgrep (p/owasp-top-ten)                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                │
│  [... more finding cards ...]                                  │
│                                                                │
│  ┌── Human Approval Gate ──────────────────────────────────┐   │
│  │  ⚠️  Review the findings above before Themis opens      │   │
│  │  a fix pull request. This action cannot be undone.      │   │
│  │                                                          │   │
│  │  [✗ Report Only]    [⚖ APPROVE & OPEN FIX PR →]         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Key interactions:**
- Finding cards: expandable/collapsible (click to show/hide code diff)
- Severity badges: color-coded with solid fill
- CWE/OWASP badges: clickable → open CWE link in new tab
- Confidence score: subtle progress bar beneath each card
- Code diff: react-diff-view with syntax highlighting
- RAG citation: collapsible "📚 Sources" section at bottom of each card
- Low-confidence toggle: "Show 3 filtered findings" expander at bottom
- Export PDF: Triggered via browser print CSS (printer-friendly layout)
- Human approval gate: prominent card at bottom, "Approve" button requires explicit click (no accidental activation)

---

### Page 4 — Benchmark Panel (`/benchmark`)

**Purpose:** Prove AMD ROCm performance. Critical for 40pts.

```
┌────────────────────────────────────────────────────────────────┐
│ THEMIS                [Dashboard] [Benchmark]   [●GPU 40.1GB ▲47t/s] │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ⚡ ROCM PERFORMANCE — AMD Radeon PRO W7900D                   │
│  Model: Qwen2.5-Coder-32B-Instruct (FP16)                     │
│                                                                │
│  ┌── Run Benchmark ─────────────────────────────────────────┐  │
│  │  [▶ RUN FULL BENCHMARK SUITE]  (takes ~3 minutes)       │  │
│  │  Last run: 2026-07-20 13:45:22                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── Throughput ────────────────────────────────────────────┐  │
│  │  Tokens/Second vs Batch Size                             │  │
│  │                                                          │  │
│  │  140 ┤                              ■ FP16               │  │
│  │  120 ┤                     ▲       □ INT4               │  │
│  │  100 ┤               ▲    ▲□                             │  │
│  │   80 ┤          ▲   ▲□  ▲□                              │  │
│  │   60 ┤     ■   ■□ ■□  ■□                               │  │
│  │   48 ┤ ■  ■□                                            │  │
│  │    0 └──────────────────────────────                    │  │
│  │       B1   B2   B4   B8  B16                            │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── Speculative Decoding ──────────────────────────────────┐  │
│  │                                                          │  │
│  │  WITHOUT spec decoding:  25.7 tok/s  ████████░░░░░       │  │
│  │  WITH spec decoding:     48.2 tok/s  ████████████████    │  │
│  │  Speedup: 1.87×  🚀                                      │  │
│  │                                                          │  │
│  │  Draft model: Qwen2.5-Coder-1.5B                        │  │
│  │  Speculative tokens: 5 per pass                         │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── Time to First Token (TTFT) ─────────────┐ ┌── Model ──┐  │
│  │  4K context:   1.24s  ████░░░░░░          │ │ FP16 37GB │  │
│  │  16K context:  3.10s  ██████████░░░       │ │ INT4 12GB │  │
│  │  32K context:  5.80s  █████████████░░░░   │ │ Delta +48%│  │
│  └────────────────────────────────────────────┘ └───────────┘  │
│                                                                │
│  ┌── Hardware Info ─────────────────────────────────────────┐  │
│  │  GPU: AMD Radeon PRO W7900D   VRAM: 48GB GDDR6           │  │
│  │  ROCm: 6.x   vLLM: 0.6.6.post1   Attention: AITER_FA    │  │
│  │  VRAM used: 40.1GB / 48.0GB (83.5%)                     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Key interactions:**
- "Run Benchmark" button: triggers `/api/benchmark`, shows spinner, live-updates charts as results stream in
- Charts: Recharts LineChart/BarChart with AMD-red + gold color scheme
- Throughput chart: FP16 vs INT4 overlaid lines
- Speculative decoding: horizontal bar comparison with speedup multiplier badge
- TTFT: animated bar fill when results arrive
- Hardware info: live data from `/health` endpoint

---

## 5. Component Library

### AgentCard

```tsx
interface AgentCardProps {
  number: number;          // 1–5
  name: string;            // "Triage" | "Security" | etc.
  status: AgentStatus;     // "idle" | "active" | "complete" | "error"
  currentAction: string;   // "Running Semgrep..."
  progress: number;        // 0–100
}

// Visual states:
// idle:     dim background, muted text, no animation
// active:   AMD-red pulsing border, progress bar animation, text shimmer
// complete: green checkmark, solid border, locked state
// error:    red border, error icon, error message
```

### FindingCard

```tsx
interface FindingCardProps {
  finding: Finding;
  expanded: boolean;
  onToggle: () => void;
}

// Always shows: severity badge, title, file:line, confidence bar
// Expanded shows: description, code diff, CWE badge, RAG citations, tool source
```

### SeverityBadge

```tsx
// Critical: bg-red-600, white text, "CRITICAL"
// High:     bg-orange-500, white text, "HIGH"
// Medium:   bg-yellow-400, black text, "MEDIUM"
// Low:      bg-green-600, white text, "LOW"
// All with 6px border-radius, uppercase, font-weight 600
```

### GPUStatusPill (nav bar)

```tsx
// Format: [● GPU 40.1GB ▲ 48.2 t/s]
// Green dot = healthy, Red = OOM risk, Amber = warning
// Updates every 2s via polling /health
// Clicking opens GPU detail tooltip
```

### HumanApprovalGate

```tsx
// Displayed at bottom of Report View only when findings exist
// Warning background (amber-900 @ 30% opacity)
// "Approve & Open Fix PR" button — AMD red, requires confirmation modal
// Confirmation modal: "This will open a new branch and PR on GitHub. Proceed?"
// [Cancel] [Confirm]
```

---

## 6. Animation Patterns

### Agent Activation (framer-motion)

```tsx
// When an agent goes from idle → active:
const agentActivateVariants = {
  idle: { borderColor: '#30363D', boxShadow: 'none' },
  active: {
    borderColor: ['#30363D', '#ED1C24', '#D4A017', '#ED1C24'],
    boxShadow: ['none', '0 0 20px rgba(237,28,36,0.3)', '0 0 20px rgba(212,160,23,0.3)'],
    transition: { duration: 1.5, repeat: Infinity, ease: 'easeInOut' }
  }
}
```

### Finding Pop (new finding appears)

```tsx
const findingVariants = {
  hidden: { opacity: 0, y: -8, scale: 0.97 },
  visible: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.25, ease: 'easeOut' } }
}
```

### Verdict Transition (pipeline complete)

```tsx
// Tribunal panel fades out
// "⚖ VERDICT READY" appears in gold with scale animation
// After 2 seconds: navigate to /report/:jobId with fade transition
```

### Live Counter (finding count increments)

```tsx
// Number springs from old → new value using framer-motion useMotionValue
// Brief gold flash on increment
```

---

## 7. Responsive Design

**Primary target:** 1440px desktop (hackathon demo on a monitor)

**Minimum supported:** 1280px wide (prevents dashboard from breaking)

**Not required:** Mobile / tablet (out of scope for V1 hackathon submission)

```css
/* Breakpoints */
--bp-lg: 1280px;
--bp-xl: 1440px;
--bp-2xl: 1920px;
```

---

## 8. Accessibility

| Requirement | Implementation |
|---|---|
| Color contrast | All text meets WCAG AA (4.5:1 minimum) |
| Keyboard navigation | All interactive elements focusable |
| ARIA labels | All icon-only buttons have `aria-label` |
| Status announcements | Agent status changes announced via `aria-live="polite"` |
| Focus visible | Custom focus ring using `--gold-primary` color |
| Reduced motion | `prefers-reduced-motion` disables animations |

---

## 9. Dark Mode

Dark mode is the **only** mode. THEMIS does not have a light theme. The dark judicial aesthetic is part of the brand identity and is non-negotiable for the hackathon demo.
