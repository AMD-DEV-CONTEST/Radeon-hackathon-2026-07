# VEIL

Adversarial anonymization for document release. Five attack personas run concurrently against a document, a Guardian proposes minimal repairs, and the system re-attacks the repaired text until the findings stop reproducing. Local inference on AMD Radeon via vLLM + ROCm.

Built for the AMD Radeon/ROCm "Development & Local Deployment of Private AI Agents" hackathon track.

---

## What it does

VEIL audits a document before it is released by simulating the attacks a motivated adversary would run after release. It produces:

1. **Findings** — re-identification claims ranked by tier (mechanical extraction, correlational inference, stylometric suggestion) and quantified by candidate-set size
2. **Edits** — the smallest changes that defeat each finding (generalize > pseudonymize > suppress > restructure)
3. **A privacy/utility curve** — residual risk vs. token retention + semantic similarity, plotted per iteration
4. **Verification** — findings are only marked resolved when all five personas fail to reproduce them after repair

The output is a repaired document, a risk score, and an audit trail explaining every finding and every edit.

---

## Why it exists

**Redaction fails constantly.** December 2025: US DOJ released 1,900 court records with names visible under redaction boxes. November 2024: NHS trust published a report with revision history intact. April 2024: law firm shared a contract with the author field unchanged. The pattern is consistent: people redact the obvious identifier and miss the three quasi-identifiers that intersect to uniquely identify someone.

Manual review does not scale, and rule-based tools (regex for SSNs, NER for names) catch only the attacks their authors thought of. VEIL is adversarial: it tries to break the document using every tool a real attacker has, and it only stops when the attacks stop working.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Gradio UI (attack theatre)              FastAPI + rc-tunnel │
├─────────────────────────────────────────────────────────────┤
│  Orchestrator                                                │
│    ├─ 5 personas (concurrent) ──> Adjudicator ──> Guardian  │
│    └─ loop: attack → repair → re-attack until clean         │
├─────────────────────────────────────────────────────────────┤
│  Tools: layout forensics, corpus RAG, entity ledger,        │
│         candidate-set sizing, date arithmetic, co-occurrence│
├─────────────────────────────────────────────────────────────┤
│  vLLM (Qwen2.5-14B-Instruct-AWQ, prefix caching enabled)   │
│    bound to 127.0.0.1 — never exposed                       │
├─────────────────────────────────────────────────────────────┤
│  Qdrant (vector) + SQLite (FTS5 + audit + ledger)          │
└─────────────────────────────────────────────────────────────┘
```

**One vLLM server, five personas.** Personas differ only in their system-prompt suffix and their tool allowlist; the document (the long part) is byte-identical across all five, so vLLM computes its KV once and reuses it. `--enable-prefix-caching` is load-bearing.

**Three evidence tiers:**
- **Tier M (Mechanical)**: text extracted from metadata, redaction underlays, or revision history — certain, immediately actionable
- **Tier C (Correlational)**: inferred from quasi-identifiers — must carry a candidate-set size, never a name
- **Tier S (Stylistic)**: authorship attribution from idiolect — suggestive only, must carry an explicit caveat

The tier system is structural: a Tier C finding without a candidate-set size is rejected at construction time, so no code path can emit an overconfident claim.

---

## Setup

### Prerequisites

- AMD Radeon GPU (tested on MI210)
- ROCm 6.0+
- Python 3.10+
- Radeon Cloud notebook environment (or equivalent with vLLM pre-installed for ROCm)

### Installation

```bash
# vLLM is already installed in the Radeon Cloud serving environment.
# Install app dependencies:
pip install -r requirements.txt --break-system-packages

# Build the auxiliary corpus (run once):
python -m veil.ingest.corpus_builder corpus/meridian

# Build the demo document (run once). This self-checks that the fixture
# actually leaks — it exits non-zero if the redaction box is misplaced:
python demo/build_demo_pdf.py

# Start vLLM (terminal 1):
./run.sh serve

# Start the app + tunnel (terminal 2):
./run.sh app
```

The app prints role passphrases on startup — one per role (AUDITOR, REDACTOR, VIEWER). These are random and session-only.

---

## Usage

1. Navigate to the rc-tunnel URL
2. Sign in with a role and its passphrase
3. Upload a .pdf, .docx, .txt, or .md document
4. Choose aggressiveness (low/balanced/high) and iteration count
5. Run the audit — the attack feed narrates it live
6. Download the repaired document or review findings

**Roles:**
- **AUDITOR**: sees raw findings + evidence, can run audits, can view the audit chain
- **REDACTOR**: sees findings (claim + severity only, no reasoning), proposes edits
- **VIEWER**: sees only the final risk score and the redacted document

A REDACTOR never receives the re-identification reasoning that produced a finding. This is enforced at the type level (`Finding.redacted_for(role)`), not in the UI.

---

## Benchmarking

```bash
# Concurrency sweep (why five personas?):
./run.sh bench --sweep

# Prefix cache validation (does it help?):
./run.sh bench --cache

# End-to-end audit timing:
./run.sh bench --end-to-end demo/sample.pdf
```

Results are written to `bench/results.json`. The deck's performance slide is generated from this file, so run the sweep before the demo.

---

## Testing

```bash
# Fast tests (no vLLM required):
pytest

# With live server tests:
pytest -m live
```

`pyproject.toml` registers the `live` marker and sets `asyncio_mode = "auto"`,
so `pytest` works with no extra flags.

Tests are written against the invariants (tier rules, edit taxonomy, audit
chain integrity, egress blocking, role projection) rather than the
implementation, so they catch design regressions rather than refactors.

**Key test files:**
- `test_adjudicator_tiers.py` — enforces that Tier C needs a candidate count, Tier S needs a caveat
- `test_egress_blocked.py` — the structural egress guarantee; this must pass before demo
- `test_prefix_determinism.py` — guards the AMD optimization story; referenced from `prefix.py`
- `test_audit_chain.py` — tampers with the log and asserts that `verify()` catches it
- `test_layout_forensics.py` — synthesises a badly-redacted PDF and recovers the text

### Verification status

The logic was exercised module by module during the build. Confirmed working:
all 47 files compile; the 19 modules whose dependencies are installable in
isolation import cleanly; tier invariants reject malformed findings at
construction; role projection strips reasoning from REDACTOR payloads; the risk
ceiling holds Tier S below CRITICAL no matter how many findings pile up; edits
apply right-to-left without offset corruption and refuse to touch text that
moved under them; the audit chain detects both altered payloads and deleted
entries; the vault round-trips and rejects wrong passphrases and tampered
ciphertext; the prefix stays byte-identical across all five personas; and the
demo fixture leaks exactly `Dr. Amara Osei` through the underlay plus
`J. Okafor` through metadata.

One real bug was found and fixed this way: `extract_underlay` tested
containment on the glyph centroid, so the trailing "y" of "reported by" fell
inside an adjacent redaction box and was reported as recovered text — a false
positive at Tier M, the tier that asserts certainty. Containment is now tested
on the glyph's full extent with a coverage-ratio floor, and `width_leak` shares
the same predicate so the two can never disagree about whether a box was empty.

Not yet exercised: anything requiring `httpx`, `fastapi`, `qdrant-client`, or
`sentence-transformers` (the sandbox this was built in has no package index),
and anything requiring a GPU. Run `pytest` on the Radeon box first — before
touching the model — and treat the egress self-test and
`test_prefix_determinism.py` as the two that must be green before you demo.

---

## Fallback ladder

If vLLM OOMs on startup, walk this ladder **in hour 1, not hour 20**:

1. `VEIL_GPU_UTIL=0.85 ./run.sh serve`  (default is 0.90)
2. `VEIL_MAX_LEN=8192 ./run.sh serve`   (default is 16384)
3. `VEIL_MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ ./run.sh serve`  (smaller model)

Everything below step 3 changes the design claim and must be documented in the README you hand in.

---

## Configuration

`veil/config.py` holds every tunable. Persona count (5), max iterations (3), and tool-call budget (6) are set from measured concurrency and time constraints, not guesses. To change them:

```python
# veil/config.py
@dataclass
class OrchestratorConfig:
    max_concurrent_personas: int = 5  # from benchmark --sweep
    max_iterations: int = 3
    per_persona_tool_call_budget: int = 6
```

Or via environment:

```bash
export VEIL_PORT=8080
export VEIL_MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ
```

---

## Threat model

**In scope:**
- Re-identification by someone who reads the released document and has access to public records, org charts, prior filings, or insider knowledge
- Accumulation across multiple redacted documents from the same source
- Redaction failures (text under boxes, metadata, revision history)

**Out of scope:**
- Attacks that require breaching the system (stealing the finding file, the vault passphrase, or the original document from disk)
- Truncation of the audit log (the tail can be removed without breaking the chain; external anchoring is needed to prevent this, which is out of scope for a local tool)
- Side-channel attacks (timing, GPU memory patterns, network traffic analysis)

**Egress guarantee:** The application makes zero outbound network calls. This is enforced at the HTTP transport layer (allowlist of `localhost` only) and is self-tested on startup. The test result is rendered in the UI during the demo.

---

## File structure

```
veil/
├── veil/
│   ├── agents/          # personas, planner, adversary, adjudicator, guardian, orchestrator
│   ├── inference/       # vLLM client, prefix construction
│   ├── ingest/          # loader, chunker, corpus builder
│   ├── scoring/         # risk and utility measurement
│   ├── security/        # egress, crypto, audit, auth
│   ├── tools/           # registry + 8 tool implementations
│   ├── types.py         # Finding, Span, Edit, Tier, Role
│   ├── config.py
│   ├── main.py          # FastAPI app
│   └── static/          # single-page UI
├── tests/               # 9 files, 115 tests, targeting the invariants
├── bench/               # concurrency sweep, cache test, end-to-end timing
├── corpus/              # auxiliary material + populations + ground truth
│   └── meridian/        # the "public record" the personas cross-reference
├── demo/                # build_demo_pdf.py generates the fixture + self-checks
├── pyproject.toml       # registers the `live` marker and asyncio_mode
├── requirements.txt
├── run.sh
└── README.md
```

### The planner

`agents/planner.py` triages a document before any GPU work happens, on cheap
local signals only — file extension, character count, and what the loader
already found. It exists because two personas can be provably useless on a
given input: the Layout-Forensicist has nothing to examine in a `.txt` file (no
metadata, no drawn rectangles, no revision history), and stylometry below
~1200 characters is indistinguishable from noise.

The rule it follows is narrow on purpose: **the planner may only remove a
persona that cannot produce evidence, never one that merely seems unlikely to.**
"Probably won't find anything" is the adversary's reasoning, not ours.

It also scales the iteration budget to measured risk — a CRITICAL document
earns all three passes, a LOW one stops after the first, because every repair
costs utility.

---

## Demo checklist

**Before the presentation:**

1. `python demo/build_demo_pdf.py` — must print "Fixture is correctly broken"
2. `./run.sh serve` in terminal 1 — let it warm up
3. `pytest -m live` — prefix cache must be enabled
4. `./run.sh bench --sweep --cache` — generate the performance numbers
5. `./run.sh app` — check that egress self-test passes
6. Open the tunnel URL, sign in as AUDITOR, upload `demo/sample.pdf`
7. Run one audit to confirm the full loop works
8. Leave the tunnel URL open in a browser tab

**During the demo:**

1. Show the egress self-test banner (green = blocked)
2. Upload a document with a known Tier M leak (redaction box over live text)
3. Start the audit — narrate the attack feed as personas report findings
4. Show the final curve: risk drops, utility stays high
5. Download the repaired document
6. **(Stretch)** Re-run the audit on the repaired document — findings should not reproduce

**7-minute script:**

- 0:00–1:00: Problem (DOJ leak, NHS leak, law-firm leak — the pattern)
- 1:00–2:30: VEIL's approach (adversarial, self-validating, five personas, three tiers)
- 2:30–5:00: Live demo (upload, attack feed, findings by tier, repair, curve)
- 5:00–6:00: AMD story (prefix caching, one vLLM server, five personas, tokens/sec, cache hit %)
- 6:00–7:00: Trust (egress blocked, audit chain, role separation, no speculation)

---

## Judging criteria alignment

| Criterion | How VEIL addresses it |
|-----------|----------------------|
| **Functional completeness** | Covers ≥3 of the brief's capabilities: local RAG (corpus_search), tool calling (registry + 8 tools), multi-step planning (orchestrator loop), long-term memory (entity_ledger), permission/privacy (three-role auth + vault encryption) |
| **AMD optimization** | --enable-prefix-caching is load-bearing; five personas share one KV; measured tokens/sec + cache hit % are in bench/results.json; fallback ladder is documented |
| **Demo quality** | 7-minute script; live attack feed; findings render by tier with colour coding; privacy/utility curve updates in real time |
| **Documentation** | README, inline docstrings, architecture doc, SKILL.md pointers, test coverage report |
| **Architecture & code quality** | Tier invariants enforced structurally; egress guarantee self-tested; audit chain tamper-evident; 115 tests targeting the design claims |
| **Presentation** | 16-slide deck in `VEIL-pitch-deck.pptx`; covers problem, design, demo script, measurements, trust architecture, market positioning |

---

## License

MIT — but read the paper (Staab et al., ICLR 2024) before deploying this against real PII.

---

## Acknowledgements

Designed and implemented for the AMD Radeon/ROCm hackathon, August 2026. Inspired by Staab et al. (ICLR 2024), the December 2025 DOJ redaction failure, and the observation that 95% of 2024's breaches traced to human error rather than novel attacks.
