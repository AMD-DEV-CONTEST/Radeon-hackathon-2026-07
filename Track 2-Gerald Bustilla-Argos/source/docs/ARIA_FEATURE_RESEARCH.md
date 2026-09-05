# Aria Feature Research — Solving User Struggles

Research compiled from analysis of user pain points, competitor features
(Microsoft Copilot, Gemini Spark, Anthropic Computer Use, Perked, Dr. Vibe,
Mark-XLIX, Everywhere, AirJelly, BreathePulse), and technical feasibility
for our C++ OpenGL cross-platform robot.

---

## The Problem: What Users Actually Struggle With

Research from 2025-2026 surveys reveals the real pain points:

| Struggle | Stat | Source |
|---|---|---|
| Tech-related slowdowns daily | 85% of desk workers, 3+ times/day for 29% | Standley Systems 2026 |
| Time lost to tech issues | 7 hours/week per employee | Freshworks Cost of Complexity |
| "Meta-work" (navigating systems) | 68% spend 10%+ of day on it, 18% spend 40%+ | Atera Research |
| Avoid asking IT | 76% avoid IT because it's "more effort than worth" | Standley Systems |
| Focus recovery after interruption | 23 min 15 sec average | UC Irvine study |
| Tab switching tax | 2+ hours/day lost to 5-tab problem | Agentic Workflow |
| Software complexity driving turnover | 38% cite it as reason to leave | Freshworks |

**Core insight:** Users don't need another tool. They need something that
*reduces* tools, reduces switching, and handles the repetitive "meta-work"
that eats their day.

---

## Feature Categories for Aria

### 1. VOICE INTERACTION (High Impact, High Feasibility)

**The struggle:** Typing is slow. Switching to an AI tab to ask a question
breaks focus. Users want to just *talk* to their computer.

**What competitors do:**
- Microsoft "Hey Copilot" wake word — voice as "third input mechanism"
- Mark-XLIX: Real-time voice via Gemini Live API, zero-latency conversation
- Beacon: Offline wake word via Vosk + Whisper.cpp transcription
- Desktop Pet: "Hey Pet" wake word, voice commands for weather/timers

**What Aria can integrate:**

| Feature | Library | Effort | Impact |
|---|---|---|---|
| **Wake word detection** ("Hey Aria") | Vosk (offline) or openWakeWord | Medium | High |
| **Speech-to-text** | whisper.cpp (C/C++, runs offline, 75MB model) | Medium | High |
| **Text-to-speech** (Aria talks back) | Piper TTS (neural, natural voices, ONNX) | Medium | High |
| **Voice commands** | whisper.cpp + intent parsing | Low | High |
| **Dictation mode** (speak → type at cursor) | whisper.cpp + SendInput | Low | Medium |

**Why it fits Aria:** Aria is already a character with a "face." Voice
makes her feel alive. The pipeline: `mic → whisper.cpp → LLM → Piper TTS →
speaker` is battle-tested (Jarvis, Christopher-AI, Beacon all use it).
whisper.cpp is pure C/C++ — integrates directly into our C++ codebase.

**Estimated pipeline latency:** 1-2 seconds on GPU, 3-5 seconds on CPU.
Fast enough for natural conversation.

---

### 2. SCREEN VISION & CONTEXT AWARENESS (High Impact, Medium Feasibility)

**The struggle:** Users see an error message, don't know what it means.
They're in a complex app, don't know where to click. They have to describe
their screen to an AI in another tab.

**What competitors do:**
- Microsoft Copilot Vision: "share your screen, Copilot understands
  everything in milliseconds"
- Everywhere: "instantly perceives anything on your screen, no
  screenshots needed, press shortcut to get help right where you are"
- AskEase (Microsoft): AI screen reader for visually impaired — captures
  screen, provides descriptions and operation guidance
- AirJelly: "watches your workflow, remembers everything across apps,
  proactively acts before you ask"

**What Aria can integrate:**

| Feature | Implementation | Effort | Impact |
|---|---|---|---|
| **Screenshot capture** | Win32 BitBlt / X11 XGetImage / macOS CGDisplayCreateImage | Low | High |
| **Screen understanding** | Send screenshot to vision LLM (GPT-4o, Gemini) | Medium | High |
| **"What am I looking at?"** | Hotkey → capture → AI describes screen | Low | High |
| **Error explanation** | Detect error dialogs → AI explains + suggests fix | Medium | High |
| **Step-by-step guidance** | AI watches screen, tells you where to click | High | High |
| **Context-aware chat** | AI knows what app/window you're in, gives relevant answers | Medium | High |

**Why it fits Aria:** Aria already has the `ariatask` computer-use system
that scans UI elements via UI Automation. Adding screenshot + vision LLM
makes her understand *anything* on screen, not just accessible UI elements.
The robot's head can physically turn to look at the area of the screen
being discussed (we already built `SetLookTarget`).

---

### 3. COMPUTER USE & TASK AUTOMATION (Already Built, Can Extend)

**The struggle:** Repetitive tasks — data entry, clicking through portals,
copy-pasting between systems, filling forms. "Easy to describe, hard to
automate" (withpace.com research).

**What we already have:**
- `ComputerUse::RunTask()` — 20-step AI orchestration loop
- `ui_scanner.cpp` — Windows UI Automation tree walker
- `input_simulator.cpp` — SendInput mouse/keyboard control
- `ariatask` command in speech bubble

**What competitors do that we could add:**

| Feature | Competitor | Effort | Impact |
|---|---|---|---|
| **Multi-step task recording** | AirJelly records user actions | Medium | High |
| **Task replay** | Run recorded sequences on demand | Medium | High |
| **Cross-app workflows** | Arahi AI: email → CRM → calendar | High | High |
| **Form auto-fill** | Computer use detects forms, fills from profile | Medium | High |
| **Batch file operations** | "Organize my downloads folder" | Low | Medium |
| **Web automation** | Browser control via accessibility/CDP | High | High |
| **Verification loops** | withpace.com: "click then verify element appeared" | Low | High |

**Why it fits Aria:** We already have the foundation. The key improvement
is adding *verification* (did the action work?) and *task recording*
(watch user do something once, replay it).

---

### 4. PROACTIVE ASSISTANCE (High Impact, Medium Feasibility)

**The struggle:** Users forget to follow up. They don't know what they
committed to in meetings. They lose track of time. They need reminders
that are *context-aware*, not just time-based.

**What competitors do:**
- AirJelly: "proactively acts before you ask" — monitors Enter key,
  captures tasks/commitments automatically
- Mark-L: "speaks first when it has something worth saying" — proactive
  check-ins after 15 min of silence
- Gemini Spark: "Every Monday at 9 AM, scan my inbox and review emails"
- Prio: "looks 1-30 days ahead — board prep, contract renewals, key
  meetings — starts the work before you ask"

**What Aria can integrate:**

| Feature | Implementation | Effort | Impact |
|---|---|---|---|
| **Smart break reminders** | Timer + activity detection → Aria nudges you | Low | High |
| **Hydration/posture alerts** | Time-based + escalating animation | Low | Medium |
| **Pomodoro timer** | Focus blocks with Aria animation states | Low | Medium |
| **Meeting prep briefings** | Calendar integration + AI summary | High | High |
| **Follow-up tracking** | Scan outgoing messages for commitments | High | High |
| **Morning briefing** | "Here's your day: 3 meetings, 5 priority emails" | Medium | High |
| **Proactive error detection** | Monitor for crash dialogs, offer help | Medium | High |
| **Idle detection** | Aria reacts when you've been away | Low | Low |

**Why it fits Aria:** Aria is a *character* — proactive reminders feel
natural when delivered by a robot with personality. Instead of a
notification popup, Aria could physically walk to the center of the
screen, wave, and show a speech bubble. The `TaskRunning` state we built
(dashing + blinking) could be repurposed for "excited to tell you
something" animations.

---

### 5. WELLNESS & EMOTIONAL SUPPORT (Medium Impact, High Feasibility)

**The struggle:** Sedentary work causes eye strain, back pain, dehydration.
Burnout is endemic. Loneliness in remote work. Users want something that
*cares* about them, not just productivity.

**What competitors do:**
- Perked: "pesters you to drink water, dances to your Spotify" —
  escalating grumpiness if you ignore reminders ("holds up increasingly
  large BREAK sign")
- Dr. Vibe: "hydration reminders, eye strain breaks (20-20-20 rule),
  posture checks, overwork prevention"
- BreathePulse: webcam CV detects stress/eye strain → suggests 60-sec
  mindful pause (breathing, posture, mini-puzzle)
- Demal Companion: "gentle wellbeing prompts for eyes, posture, movement"

**What Aria can integrate:**

| Feature | Implementation | Effort | Impact |
|---|---|---|---|
| **20-20-20 eye breaks** | Every 20 min, look at 20ft for 20 sec | Low | Medium |
| **Posture checks** | Periodic reminders + Aria demonstrates stretch | Low | Medium |
| **Hydration reminders** | Escalating animation (Aria gets worried) | Low | Medium |
| **Walk breaks** | After 2 hours, Aria blocks screen until you stand | Low | High |
| **Mood tracking** | "How are you feeling?" → Aria adapts personality | Medium | Medium |
| **Stress detection** | Webcam CV for facial expressions (optional) | High | Medium |
| **Breathing exercises** | Aria guides breathing with animation sync | Low | Medium |
| **Celebrate wins** | Task complete → Aria celebrates (existing state!) | Low | High |

**Why it fits Aria:** Aria already has `Celebrating` and `Sleeping`
states. Wellness features are mostly *timer logic + animation triggers* —
very low engineering cost. The emotional connection of a robot companion
makes wellness reminders feel less nagging than notification popups.

---

### 6. CLIPBOARD & TEXT INTELLIGENCE (Medium Impact, Low Effort)

**The struggle:** Users copy-paste constantly. They lose clipboard
history. They need to reformat text, translate, summarize, extract data
from copied content.

**What competitors do:**
- Clippy-AI: "semantic clipboard search, natural language queries,
  image analysis & OCR"
- Everywhere: "no need for screenshots, copying, or switching apps"

**What Aria can integrate:**

| Feature | Implementation | Effort | Impact |
|---|---|---|---|
| **Clipboard history** | Monitor clipboard, store last N items | Low | Medium |
| **Smart paste** | AI reformats/summarizes/translates clipboard | Low | High |
| **Clipboard search** | Search past clipboard items semantically | Medium | Medium |
| **OCR from screenshot** | Capture region → OCR → text to clipboard | Medium | High |
| **Auto-categorize** | Detect URLs/emails/code/phone numbers in clipboard | Low | Medium |

**Why it fits Aria:** Clipboard monitoring is trivial on all platforms
(`AddClipboardFormatListener` on Windows, `xclip`/`xsel` on Linux,
`NSPasteboard` on macOS). Aria can pop up a small bubble when you copy
something: "I noticed you copied a tracking number — want me to look it
up?"

---

### 7. SYSTEM MONITORING & SMART ALERTS (Low Impact, Low Effort)

**The struggle:** Users don't notice high CPU/RAM, disk filling up, battery
dying, network issues until it's too late.

**What competitors do:**
- Mark-XLIX: "continuous CPU, RAM, GPU and temperature telemetry with
  localized voice alerts"
- Mark-L: same + "alerts naturally"

**What Aria can integrate:**

| Feature | Implementation | Effort | Impact |
|---|---|---|---|
| **CPU/RAM alerts** | Periodic check, Aria warns if >90% | Low | Low |
| **Disk space warnings** | Check free space, warn if <10GB | Low | Low |
| **Battery alerts** | Low battery → Aria looks worried | Low | Medium |
| **Network status** | Detect disconnection, Aria shows confused state | Low | Low |
| **Temperature** | CPU temp monitoring (OpenHardwareMonitor API) | Medium | Low |

**Why it fits Aria:** Aria's expression system can reflect system health —
worried eyes when CPU is high, sleeping when idle, alert when battery low.

---

### 8. PERSISTENT MEMORY & LEARNING (High Impact, High Effort)

**The struggle:** Every conversation with AI starts from scratch. Users
repeat themselves. The AI doesn't know their preferences, projects, or
context.

**What competitors do:**
- Mark-L: "deeply remembers projects, preferences, and personal context
  across sessions"
- AirJelly: "dual-layer memory — static context (who you are) vs dynamic
  events (tasks, commitments), vector search + time-decay weighting"
- Gemini Spark: "read through my last 50 emails and turn it into a style
  guide — call that skill ghostwriter"

**What Aria can integrate:**

| Feature | Implementation | Effort | Impact |
|---|---|---|---|
| **Conversation memory** | SQLite/JSON store of past chats | Medium | High |
| **User preferences** | "I prefer dark mode, I use VS Code, I'm a dev" | Medium | High |
| **Project context** | Remember what you're working on | Medium | High |
| **Vector search** | Embed past conversations, semantic recall | High | High |
| **Habit learning** | "You always open email at 9 AM — I'll prep it" | High | Medium |
| **Relationship stage** | Aria's personality evolves over time | Medium | Medium |

**Why it fits Aria:** Memory transforms Aria from a tool into a companion.
The robot can reference past conversations: "Last week you said you were
stressed about the deadline — how did that go?"

---

### 9. CROSS-APP WORKFLOW ORCHESTRATION (High Impact, Very High Effort)

**The struggle:** "These workflows run across systems with no APIs, mix
repetitive data entry with real judgment" (withpace.com). Users manually
shuttle data between email, CRM, calendar, docs.

**What competitors do:**
- Arahi AI: "reads inbox, drafts in your voice, books meetings, auto-logs
  to Salesforce/HubSpot"
- Gemini Spark: "connect apps and let Gemini connect the dots across your
  digital ecosystem"
- Windows Agent Launchers: "register agents directly with the OS,
  show up in taskbar and Copilot"

**What Aria can integrate (long-term):**

| Feature | Implementation | Effort | Impact |
|---|---|---|---|
| **Email triage** | IMAP integration + AI categorization | High | High |
| **Calendar management** | CalDAV/Google Calendar API | High | High |
| **Smart scheduling** | AI proposes optimal time blocks | High | High |
| **CRM sync** | Push customer interactions to Salesforce/HubSpot | Very High | High |
| **Multi-app automation** | Chain actions across 3+ apps | Very High | High |

**Why it fits Aria:** This is the hardest category but highest value.
Start with computer-use (already built) for apps without APIs, then add
native API integrations for email/calendar.

---

## Recommended Implementation Priority

Based on impact vs effort, here's the recommended roadmap:

### Phase 1: Voice (Weeks 1-3) — Highest ROI
1. **whisper.cpp integration** — speech-to-text, offline
2. **Piper TTS** — Aria speaks back with natural voice
3. **Wake word** — "Hey Aria" via Vosk or openWakeWord
4. **Voice commands** — "Hey Aria, what time is it?"

### Phase 2: Screen Vision (Weeks 3-5)
5. **Screenshot capture** — cross-platform
6. **Vision LLM integration** — send screenshot to GPT-4o/Gemini
7. **"What's on my screen?"** — hotkey + AI description
8. **Error detection** — spot crash/error dialogs, offer help

### Phase 3: Wellness + Proactive (Weeks 5-7)
9. **Break reminders** — 20-20-20, posture, hydration
10. **Pomodoro timer** — focus blocks with Aria states
11. **Idle detection** — Aria reacts to inactivity
12. **Win celebration** — task complete → Aria celebrates

### Phase 4: Clipboard + Memory (Weeks 7-10)
13. **Clipboard monitor** — history + smart paste
14. **Conversation memory** — SQLite store
15. **User preferences** — persistent profile
16. **Context-aware chat** — AI knows your current app

### Phase 5: Advanced Automation (Weeks 10+)
17. **Task recording** — watch + replay user actions
18. **Email/calendar integration** — IMAP + CalDAV
19. **Morning briefing** — AI summarizes your day ahead
20. **Cross-app workflows** — chain actions across apps

---

## Technical Stack Summary

| Capability | Library/Tool | License | Cross-Platform |
|---|---|---|---|
| Speech-to-text | whisper.cpp | MIT | Yes (C/C++) |
| Text-to-speech | Piper TTS | MIT | Yes (ONNX) |
| Wake word | Vosk / openWakeWord | Apache 2.0 | Yes |
| Screenshot | Win32/X11/macOS APIs | — | Platform-specific |
| Vision LLM | OpenAI GPT-4o / Gemini API | API | Yes (HTTP) |
| Clipboard | Win32/xclip/NSPasteboard | — | Platform-specific |
| Local storage | SQLite | Public domain | Yes |
| Vector search | hnswlib | Apache 2.0 | Yes (C++) |
| System stats | sysinfo API / WMI / sysctl | — | Platform-specific |

**Key insight:** whisper.cpp, Piper, and hnswlib are all C/C++ — they
integrate directly into our existing C++ codebase without any Python
dependency. This keeps Aria fast, lightweight, and truly cross-platform.
