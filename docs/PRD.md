# THEMIS — Product Requirements Document (PRD)
## Version 1.0 | AMD AI DevMaster Hackathon | July 20, 2026

---

## 1. Executive Summary

**Product:** THEMIS — An autonomous AI code review and security analysis tribunal

**Tagline:** *Your pull request never gets through without Themis's blessing.*

**One-liner:** THEMIS is a locally-hosted, AMD ROCm-powered multi-agent AI system that autonomously reviews GitHub pull requests for security vulnerabilities and code quality issues, grounds every finding in authoritative documentation (OWASP, CWE, style guides), and automatically generates a fix pull request — all without sending a single line of code to an external cloud service.

**Competition:** AMD AI DevMaster Hackathon — Track 2: Agentic AI

**Target Score:** 100/100
- Value/Completeness: 60/60
- GPU/ROCm Optimization & Local Inference Speed: 40/40

---

## 2. Problem Statement

### The Problem
Code review is the last line of defence before vulnerabilities reach production — yet it is chronically under-resourced:

- **Security expertise is scarce:** Senior engineers who can spot injection flaws, auth bypasses, and race conditions are rare and expensive.
- **Reviews are inconsistent:** The same code reviewed by two engineers produces wildly different feedback. Style and security standards vary by reviewer mood.
- **Knowledge is not grounded:** When a reviewer says "this looks like a SQL injection," they rarely cite CWE-89 or point to the OWASP A03:2021 specification. Developers don't know *why* something is wrong, only *that* it is.
- **Existing AI tools are shallow:** Tools like PR-Agent make a single LLM call per PR with no specialization, no tool use, and no authoritative grounding. They produce verbose, unverifiable feedback.
- **Cloud AI tools are a privacy risk:** Sending proprietary code to OpenAI or Anthropic APIs violates data privacy policies and IP agreements. Most enterprises cannot use cloud AI code review.

### The Opportunity
A locally-hosted, multi-agent AI system with authoritative knowledge grounding can:
1. Catch security vulnerabilities with the precision of a specialist (Semgrep + LLM synthesis)
2. Ground every finding in OWASP/CWE citations developers can learn from
3. Generate actual code fixes, not just comments
4. Run entirely on local AMD hardware — no code ever leaves the machine
5. Process PRs in seconds, not hours

---

## 3. Target Users

### Primary User — Senior Developer / Tech Lead
- **Context:** Reviews 3-10 PRs per day across a team of 5-15 engineers
- **Pain:** Not enough time to do thorough security reviews on every PR
- **Goal:** Confidence that security and quality bars are met before merging
- **Use of THEMIS:** Submit PR URL → receive structured report → decide approve/reject in 2 minutes

### Secondary User — Junior Developer
- **Context:** Submitting code for review, lacks security awareness
- **Pain:** Gets vague feedback like "this could be vulnerable" with no explanation
- **Goal:** Understand *what* is wrong and *how* to fix it
- **Use of THEMIS:** Receive report with CWE citations + auto-generated fix diff → learn by example

### Tertiary User — Security Engineer / AppSec Team
- **Context:** Responsible for security posture across multiple repositories
- **Pain:** Cannot manually review every PR across 20+ repos
- **Goal:** Automated first-pass security triage before human review
- **Use of THEMIS:** Integrate into CI/CD as a gate — block merges until THEMIS report is clean

### Hackathon Judge (Implicit User)
- **Goal:** Evaluate technical innovation, AMD GPU utilization, and real-world value
- **THEMIS must:** Demonstrate live inference on W7900D with visible GPU metrics, show the complete pipeline end-to-end, present benchmark data proving ROCm performance

---

## 4. User Personas

### Persona 1 — "Elena" (Senior Engineer, 7 years exp.)
- Reviews 8 PRs/day. Misses subtle security issues when fatigued.
- Wants: Fast first-pass triage so she can focus human review on flagged PRs.
- Frustration: "I don't want to read 500 lines of a PR at 5pm to find one SQL injection."

### Persona 2 — "Marcus" (Junior Dev, 6 months exp.)
- Submits PRs with unintentional security antipatterns he doesn't know about.
- Wants: Actionable feedback he can learn from, not just "fix this."
- Frustration: "The senior told me to 'parameterize the query' but didn't show me how."

### Persona 3 — "Priya" (AppSec Lead)
- Responsible for security across 15 repositories.
- Wants: Automated pre-merge gate with zero cloud data exposure.
- Frustration: "We can't use GitHub Copilot review — legal says no code to external APIs."

---

## 5. Use Cases

### UC-01: GitHub PR Review
**Actor:** Senior Developer / Elena
**Flow:**
1. User pastes GitHub PR URL into THEMIS dashboard
2. THEMIS fetches diff (via API or git clone fallback for large PRs)
3. Tribunal agents analyze: Triage → [Security ∥ Style] → Verifier → Fix
4. User watches live Tribunal View with agent reasoning traces
5. Structured report appears with severity badges, CWE citations, confidence scores
6. User approves → Fix Agent opens a counter-PR with patches

**Success criteria:** Report generated in <120 seconds for a 50-file PR

---

### UC-02: Manual File Upload Review
**Actor:** Junior Developer / Marcus
**Flow:**
1. Developer drags `.py`, `.js`, `.ts`, `.go`, `.java` files into THEMIS upload zone
2. Same agent pipeline runs as UC-01
3. Report shows issues with CWE citations and PEP8/style references
4. Code diff viewer shows exact line changes needed
5. Developer downloads the fix patch

**Success criteria:** Developer understands why each finding is a problem (citation provided)

---

### UC-03: CI/CD Integration (Future)
**Actor:** AppSec Lead / Priya
**Flow:**
1. GitHub Actions webhook triggers THEMIS API on every PR open
2. THEMIS runs autonomously, posts report as PR comment
3. If Critical/High findings exist, PR is blocked from merge
4. Fix PR auto-opened by THEMIS if developer opts in

**Note:** This is a post-hackathon feature. V1 requires manual trigger.

---

### UC-04: Benchmark Demonstration (Hackathon Judge)
**Actor:** Hackathon Judge
**Flow:**
1. Navigate to Benchmark panel
2. Click "Run Benchmark" → THEMIS runs 100 inference calls on W7900D
3. Live charts show: tok/s, TTFT, speculative decoding on/off comparison, INT4 vs FP16
4. Results table proves AMD hardware is being used and performing well

---

## 6. Functional Requirements

### Priority: Must Have (M)

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-001 | Accept GitHub PR URL as input | Valid PR URL → diff fetched within 10s |
| FR-002 | Accept file upload (.py, .js, .ts, .go, .java) | Upload → analysis begins within 3s |
| FR-003 | Triage Agent: parse diff, detect languages, prioritize risk | Output: ordered list of files by risk score |
| FR-004 | Security Agent: run Semgrep + Bandit in Docker sandbox | No network access, 30s timeout enforced |
| FR-005 | Security Agent: retrieve OWASP + CWE context via RAG | Every security finding has at least 1 RAG citation |
| FR-006 | Style Agent: run Pylint or ESLint in Docker sandbox | Language-appropriate linter selected automatically |
| FR-007 | Style Agent: retrieve style guide context via RAG | Every style finding has at least 1 guideline citation |
| FR-008 | Verifier Agent: score all findings 0–1 confidence | Findings below 0.7 flagged "low confidence" |
| FR-009 | Verifier Agent: validate all CWE IDs against lookup | Invalid CWE IDs flagged "unverified" |
| FR-010 | Fix Agent: generate code patches for verified findings | Patch applies cleanly to original diff |
| FR-011 | Human approval gate before Fix Agent opens PR | User explicitly confirms before any GitHub write |
| FR-012 | Fix Agent: open counter-PR on GitHub with patches | PR created on `themis/fix-pr-{number}` branch |
| FR-013 | Live WebSocket agent trace to frontend | Agent steps visible within 500ms of occurrence |
| FR-014 | Structured report: severity, CWE, confidence, citation | JSON report + rendered React view |
| FR-015 | Handle large PRs via git clone fallback | PRs with >280 files succeed via fallback path |
| FR-016 | Prompt injection sanitizer on all diff inputs | Known injection patterns redacted before LLM |
| FR-017 | Benchmark endpoint: tok/s, TTFT, spec decoding comparison | JSON results + frontend chart |
| FR-018 | All LLM inference on local AMD W7900D via vLLM | No external API calls for inference |

### Priority: Should Have (S)

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-019 | INT4 quantization benchmark vs FP16 | Comparison chart in Benchmark panel |
| FR-020 | Per-finding code diff viewer in report | Affected lines highlighted |
| FR-021 | Export report as PDF/JSON | Download button in Report View |
| FR-022 | API key authentication on all FastAPI endpoints | Unauthorized requests return 401 |
| FR-023 | Pipeline-level health check for vLLM | `/health` endpoint returns vLLM status |

### Priority: Could Have (C)

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| FR-024 | Go language support (Semgrep only) | `.go` files analyzed by Semgrep |
| FR-025 | Java language support (Semgrep only) | `.java` files analyzed by Semgrep |
| FR-026 | Re-run analysis with different model parameters | UI toggle for temperature / top-p |
| FR-027 | Historical report storage per repository | Past reports accessible in dashboard |

### Priority: Won't Have (W) — V1 Scope

| ID | Requirement | Reason |
|---|---|---|
| FR-028 | GitHub webhook / CI/CD auto-trigger | Requires server-side GitHub App, too complex for V1 |
| FR-029 | Multi-repository portfolio view | Out of scope for hackathon timeline |
| FR-030 | User authentication (multi-user) | Single-user local deployment only in V1 |

---

## 7. Non-Functional Requirements

### Performance
| ID | Requirement | Target |
|---|---|---|
| NFR-001 | PR analysis time (50-file PR) | < 120 seconds end-to-end |
| NFR-002 | LLM output throughput (W7900D) | > 45 tokens/second (batch size 1) |
| NFR-003 | Time to first token (4K context) | < 2 seconds |
| NFR-004 | RAG retrieval time (per query) | < 500ms |
| NFR-005 | WebSocket event latency | < 500ms agent step → browser |

### Security
| ID | Requirement |
|---|---|
| NFR-006 | All static analysis runs in Docker with no network access |
| NFR-007 | Prompt injection sanitizer applied before all LLM calls |
| NFR-008 | `GITHUB_TOKEN` never logged or exposed in API responses |
| NFR-009 | CWE IDs validated against static lookup before citing |
| NFR-010 | Per-request LangGraph state — no cross-request state leakage |

### Reliability
| ID | Requirement |
|---|---|
| NFR-011 | LangGraph recursion limit: 30 steps (hard cap) |
| NFR-012 | Tool call loop detection via SHA-256 hash |
| NFR-013 | Docker sandbox hard timeout: 30 seconds per tool |
| NFR-014 | GitHub API rate limit awareness + exponential backoff |
| NFR-015 | Graceful degradation if vLLM is unavailable (503 with message) |

### Maintainability
| ID | Requirement |
|---|---|
| NFR-016 | All config in environment variables (no hardcoded secrets) |
| NFR-017 | All dependencies pinned in `requirements.txt` |
| NFR-018 | All Docker image versions pinned (no `:latest` in production) |

---

## 8. Success Metrics

### Hackathon Success Metrics (Primary)
| Metric | Target |
|---|---|
| Hackathon score | ≥ 85/100 |
| Demo video completeness | Full pipeline shown end-to-end |
| ROCm benchmark data | tok/s + TTFT + speculative decoding delta documented |

### Product Quality Metrics (Secondary)
| Metric | Target |
|---|---|
| False positive rate (security findings) | < 30% (Semgrep tuned + Verifier filter) |
| CWE citation accuracy | 100% (all invalid IDs caught by validator) |
| PR analysis success rate | > 95% (including fallback path) |
| Pipeline completion rate (no crashes) | > 99% on standard PRs |

---

## 9. Constraints

| Constraint | Detail |
|---|---|
| **Hardware** | AMD Radeon PRO W7900D only (1 GPU, 48GB VRAM) |
| **Model size** | Max ~38GB VRAM for model weights at FP16 (0.80 utilization) |
| **Deadline** | August 6, 2026 — all features must be demo-ready |
| **Video** | 3–5 minutes, must show live GPU operation |
| **PR title format** | `Track 2, [Team Name], Themis` |
| **Budget** | Radeon Cloud credits valid post-July 23; heavy runs must complete before then |
| **Privacy** | No code sent to external APIs — 100% local inference |

---

## 10. Assumptions

1. The W7900D instance on Radeon Cloud is provisioned and accessible via SSH.
2. `GITHUB_TOKEN` (fine-grained PAT) is set and has repository read + PR write permissions.
3. Docker is available on the Radeon Cloud instance for sandboxed tool execution.
4. The developer has at least one public GitHub repository with known or seeded vulnerabilities for demo purposes.
5. Internet access is available from the Radeon Cloud instance for Hugging Face model downloads (before models are cached to PVC).

---

## 11. Out of Scope (V1)

- Multi-user authentication system
- CI/CD webhook integration / GitHub App
- Support for languages beyond Python, JavaScript, TypeScript, Go, Java
- Dynamic loading of additional knowledge bases
- Mobile or tablet interface
- Kubernetes/production deployment configuration
- SBOM (Software Bill of Materials) analysis
- Dependency vulnerability scanning (only code review, not package analysis)
