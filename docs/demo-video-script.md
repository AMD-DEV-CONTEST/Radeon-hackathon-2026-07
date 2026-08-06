# CodeRisk Agent — Demo Video Script v4

> Duration: 3 min 35 sec (215s) + 25s buffer = 4 min max
> Format: Terminal recording + narration
> Language: English
> Version: v4 (2026-07-19) — Resolves all 5 remaining risks from Kimi review

---

## Scene 1: The Problem (20s)

**[Screen: XZ Utils news headline]**

> "In 2024, the XZ Utils backdoor nearly compromised every Linux distribution worldwide. One maintainer. A few lines of malicious code. The entire software supply chain almost collapsed."

**[Screen: Terminal with CodeRisk Agent logo]**

> "CodeRisk Agent catches these risks before code ships — and it runs entirely on your local AMD GPU. Code never leaves your machine."

---

## Scene 2: Quick Demo — One Command, Full Analysis (75s)

### Part A: The Command (5s)

**[Screen: Full-screen terminal, dark theme, 18pt font]**

```bash
python3 main.py analyze tests/test_cases/ --output terminal
```

> "One command. Let me walk you through what happens."

### Part B: Phase 1-2 — Static Analysis (15s)

**[Screen: Terminal showing Phase 1 and Phase 2 output]**

> "Phase 1: Pattern matching for buffer overflows, command injection, deserialization. Fast, CPU-only. Found 18 initial risks across our test suite of 5 vulnerability samples — both C and Python files."

> "Phase 2: Semgrep integration — industry-standard rules from the open-source community."

### Part C: Why Better Than Semgrep (15s)

**[Screen: Split view — left: Semgrep output, right: CodeRisk output]**

> "But here's the difference. Semgrep sees `strcpy` and flags it — it needs human-written rules for context. CodeRisk Agent uses LLM to automatically understand the context — the input is already validated. Risk downgraded to LOW."

> "And Agent 3's self-reflection found something Semgrep completely missed: a `malloc()` without NULL check at line 58. That's a real vulnerability that static analysis alone would miss."

### Part D: Phase 3-4 — AI Analysis (20s)

**[Screen: Terminal showing LLM calls and Agent 3 output]**

> "Phase 3: The LLM reads the code like a human auditor. It generates attack scenarios — 'An attacker can inject arbitrary commands through the host parameter.'"

> "Phase 4: Deep verification. Triple cross-validation — tool confirmation, CWE knowledge base, and local CVE database query — real CVE numbers, real CVSS scores, all offline."

### Part E: The Report (20s)

**[Screen: Show risk table with CWE links, then zoom into one risk]**

> "47 vulnerabilities detected across C and Python files. Every one has evidence, CWE classification, and a fix suggestion."

**[Screen: Zoom into RISK-014 — show before/after code]**

> "Look at this one. `strcpy(dest, src)` — buffer overflow. The fix? `strncpy` with bounds checking. Concrete, actionable, copy-paste ready."

---

## Scene 3: Architecture Deep Dive (60s)

### Part A: Overview (10s)

**[Screen: Simple pipeline diagram — just Agent 1 → Agent 2 → Agent 3 → Agent 4, left to right]**

> "Four specialized agents in an orchestrated pipeline. Let me show you the key differentiators."

### Part B: Agent 2 — Semantic Analysis (10s)

**[Screen: Highlight Agent 2, show LLM inference output]**

> "Agent 2 runs Qwen2.5-Coder-32B on the AMD GPU. It understands code logic, not just patterns. It can find vulnerabilities that no regex will ever catch."

### Part C: Agent 3 — Deep Verification (25s)

**[Screen: Animate — first show tool confirmation, then add CWE layer, then add CVE layer]**

> "Agent 3 is where the magic happens. Triple cross-validation."

> "First: tool confirmation — did static analysis and LLM agree?"

**[Screen: Add CWE knowledge base layer]**

> "Second: CWE knowledge base — are there known exploits?"

**[Screen: Add local CVE database layer]**

> "Third: local CVE database query — real CVE numbers, real CVSS scores."

**[Screen: Show Agent 3 finding missed risks]**

> "And the self-reflection loop. Agent 3 asks: 'Did I miss anything?' In our tests, it found 4 vulnerabilities the previous agents missed. And it automatically suppressed 1 known false positive."

### Part D: Memory Layer (15s)

**[Screen: Show memory recall in terminal output]**

> "And it learns. Watch this — the first run, the system builds a memory of confirmed patterns."

**[Screen: Show second run with memory recall]**

> "Second run on similar code. 'Memory: pattern found, using cached result.' Detection is faster. False positives are suppressed. The system gets smarter with every scan."

---

## Scene 4: GPU Performance (45s)

### Part A: Environment (10s)

**[Screen: Split view — left: terminal, right: rocm-smi]**

> "This is running on an AMD Radeon Pro W7900 with ROCm 7.2.4. The model is loaded into GPU memory — every analysis benefits from hardware acceleration."

### Part B: Performance Data (20s)

**[Screen: Performance comparison]**

> "Let me show you the numbers."

| Mode | Speed |
|------|-------|
| CPU only | 6.8 tokens/s |
| AMD GPU (ROCm HIP, 32B) | 29.4 tokens/s |
| AMD GPU (ROCm HIP, 7B) | 105 tokens/s |

> "4.3 times faster with GPU acceleration on the 32B production model. No API calls. No cloud dependency. No data leaving your machine."

### Part C: ROCm Build (15s)

**[Screen: Show terminal with build success message]**

> "Getting HIP working in the Radeon Cloud container took some detective work. We found the right build configuration for ROCm 7.2.4, and GPU inference worked immediately."

> "This is what local AI looks like. Real performance. Real privacy. Real security."

---

## Scene 5: Closing (15s)

**[Screen: Architecture diagram + key stats]**

> "CodeRisk Agent. Four AI agents. Orchestrated pipeline. Memory learning. Local CVE validation. All running on your local AMD GPU."

**[Screen: GitHub repo + team name]**

> "github.com/a9320/code-risk-agent | Yang Weike | AMD AI DevMaster Hackathon 2026"

---

## Appendix: Production Notes

### Recording Checklist
- [ ] Terminal font: 18pt+, dark theme (VS Code Dark or similar)
- [ ] Pre-load model before recording (avoid 30s startup wait)
- [ ] rocm-smi running in background (tmux split pane)
- [ ] Practice narration 2-3 times
- [ ] Background music: subtle, tech-focused, not distracting
- [ ] Record Scene 2 and Scene 3 first (don't depend on GPU)
- [ ] Record Scene 4 last (depends on GPU availability)

### GPU Fallback Plans

**Plan A: ROCm HIP available (best case)**
- Split screen: terminal + rocm-smi
- Show real-time inference with GPU utilization
- Performance data: 29.4 t/s (32B), 105 t/s (7B)

**Plan B: Only Vulkan available**
- Show radeontop or vulkaninfo
- Note: Vulkan backend was not benchmarked; ROCm HIP is the primary backend
- "We focused on ROCm HIP for GPU acceleration. The architecture could support Vulkan as a fallback, but performance was not measured."

**Plan C: CPU only (worst case)**
- Be honest: "In this container environment, GPU access is limited. But the architecture is designed for local GPU inference."
- Show pre-recorded benchmark data as overlay
- "The code is ready. The GPU is waiting."

### Key Moments to Highlight
1. **XZ Utils story** — establishes stakes in 20 seconds
2. **Semgrep vs CodeRisk comparison** — shows differentiation
3. **Agent 3 finding missed risks** — demonstrates intelligence
4. **Before/after code fix** — shows actionable output
5. **Memory recall** — demonstrates learning
6. **4.3× GPU speedup (32B)** — tangible performance benefit

### Time Budget

| Scene | Target | Content |
|-------|--------|---------|
| 1. Problem | 20s | XZ Utils + local AI pitch |
| 2. Demo | 75s | Command + phases + comparison + report |
| 3. Architecture | 60s | Agent 2 + Agent 3 + memory |
| 4. Performance | 45s | rocm-smi + numbers + build story |
| 5. Closing | 15s | Summary + repo |
| **Total** | **215s** | **3:35** |
| Buffer | 25s | Transitions, pauses |
| **Max** | **240s** | **4:00** |

### v4 Changelog (from v3)
1. ✅ ROCm Build story simplified — removed cmake flag details, kept "found the right build configuration"
2. ✅ "47 vulnerabilities" contextualized — added "across C and Python files" and "test suite of 5 vulnerability samples"
3. ✅ Architecture diagram uses step-by-step animation — start with simple pipeline, layer by layer add CWE/CVE
4. ✅ Multi-language support mentioned — "both C and Python files" in Scene 2
5. ✅ One-click fix noted as future work — "copy-paste ready" in current version, --fix parameter planned
