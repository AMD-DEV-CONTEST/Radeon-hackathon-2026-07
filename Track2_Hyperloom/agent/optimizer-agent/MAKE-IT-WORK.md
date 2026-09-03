# MAKE-IT-WORK — making the local optimizer-agent reliably land multi-file code edits

**Scope.** Concrete engineering plan to fix the *specific* failure we observe: the local brain
**diagnoses the first clear error, edits + rebuilds it correctly, then on the subtler
block-format / type_traits mismatch it MISDIAGNOSES (fixates on "the loader is buggy"),
spirals on grep/read, and won't commit the multi-file edit.** Research + synthesis only — no
agent code was modified here. All claims are cited (URLs at the end).

The single most important reframing, backed by every leading agent (SWE-agent, OpenHands, Aider,
Cline): **reliability on multi-file edits comes from the HARNESS and the EDIT FORMAT far more than
from the model's raw IQ.** The techniques below are what turn a weak model from "narrates a fix"
into "commits the fix." We should adopt them *and* swap the brain — both, not either.

---

## Diagnosis of our current harness (grounded in the code)

What we already have that is right:
- Compiler errors **are** fed back — `rebuild()` returns `errors[]` and the transcript keeps them
  (`codetools.py:94-101`). Good; this is the reflexion signal.
- A **loop-breaker** exists — 3× identical call forces a different action (`agent.py:115-125`).
- A **grounded OODA diagnosis** between attempts, seeded with real observations (`agent.py:129-147`).
- Memory/RAG persists across attempts (`memory.py`).

What is causing the observed failure, mapped to the code:

| Observed failure | Root cause in the harness |
|---|---|
| Misdiagnoses subtle block/traits mismatch; fixates on "loader is buggy" | **No localization step** and **no plan/edit separation**. The model reasons about the *bug* and the *edit format* in the same breath, and the OODA prompt is free-form reflection — it "produces plausible-but-wrong root causes" exactly as the literature predicts for a single model splitting attention (Aider Architect/Editor). Telling it "the file is known-good" in prose does not bind its behavior. |
| Won't commit the multi-file edit | **`edit_source` is exact-string replace** (`codetools.py:85-93`). It fails on any whitespace/indent drift and refuses non-unique matches ("matches N places"). For a multi-hunk change across enum→traits→block→dequant→kernel this is brittle; a weak model gets one hunk rejected and retreats to "investigate more." Aider's data: turning OFF tolerant matching raises edit errors ~**900%**. |
| Spirals on grep/read | `grep_source` returns up to 40 raw `file:line` lines and `read_source` up to 200 lines — the model drowns. SWE-agent found that dumping match context "proved too confusing"; they summarize. Nothing here forces the model from *observe* into *act* except the crude 3×-identical loop-breaker. |
| Rarely uses `search_knowledge` over 927 seeded chunks | **~19 tools presented at once**, flat, with the seeded corpus reachable only if the model *chooses* to query it. Weak models don't reliably self-direct RAG. The knowledge should be *pushed* at the localize step, not waited-for. |

---

## Part 1 — The 5 highest-leverage changes (ranked)

### 1. Replace exact-string `edit_source` with a TOLERANT search/replace tool, and add a whole-file editor — *this is the #1 fix for "won't commit the edit"*

**Mechanism.** Swap the exact-string replace for the Aider/Cline edit engine:
- Normalize line-endings/BOM/trailing-whitespace before matching.
- **Relative-leading-whitespace matching** (match indentation *shape*, not exact columns).
- **Block-anchor matching**: for a ≥3-line search block, anchor on the first and last line and
  tolerate drift in between (Cline's technique).
- Progressive fallback: re-diff, infer missing markers, split a large hunk into overlapping
  sub-hunks, vary context size (Aider's 5 strategies).
- Add a second edit tool `write_file(path, contents)` = **whole-file rewrite**, and default the
  weak local model to it. Aider: the `whole` format "is the easiest for an LLM to use," and Aider
  *defaults lesser-known models to whole-file*; weak models "are more prone to disobeying" diff
  formatting.

**Why it fixes our failure.** The block/traits change is multi-hunk and indentation-heavy — exactly
where exact-string match rejects an edit and the model gives up. Tolerant matching means a *roughly*
correct edit lands instead of erroring, and whole-file rewrites let the model regenerate a small
file (e.g. a block-struct header) in one shot instead of threading a fragile diff. Aider measured a
**~900% reduction in edit errors** from the tolerance layer alone. This is the change most directly
targeting "won't commit the multi-file edit."

**Source.** Aider unified-diffs / tolerant patching: https://aider.chat/docs/unified-diffs.html ·
edit-format guidance (whole = easiest, weak models default to whole):
https://aider.chat/docs/more/edit-formats.html · Cline tolerant/anchor matching:
https://github.com/cline/cline/issues/2909

### 2. Mandatory LOCALIZE-then-PLAN before any edit, with the fix *decomposed into a checklist* — *this is the #1 fix for "misdiagnose and fixate"*

**Mechanism.** Insert two forced phases before editing:
- **Localize (read-only).** The agent must first produce the *set of edit sites* — the concrete
  `file:line` list it will touch — using summarized search (see #3) and, critically, an **auto-pushed
  RAG lookup**: at localize time the harness itself runs `search_knowledge` on the current error and
  injects the top seeded chunks (we have 927 chunks of ggml source) into context, rather than hoping
  the model queries. Aider's repo-map (tree-sitter + PageRank over the dependency graph) is the
  reference technique for "find the right symbols cheaply without reading everything."
- **Plan (Architect/Editor split).** A dedicated *planning* turn writes the fix as an explicit,
  domain-shaped checklist and *nothing else* — for our task, hard-code the known edit chain as the
  plan template the model must fill in:
  `1) add enum entry  2) add type_traits row  3) define block struct  4) add dequantize fn
   5) register CPU dispatch  6) register GPU kernel dispatch`. Then a separate *edit* turn executes
  each checklist item with the search/replace tool.

**Why it fixes our failure.** The misdiagnosis is an *attention* problem: Aider showed that a single
model "has to split its attention between solving the coding problem and conforming to the edit
format," and separating the two (Architect/Editor) set a SOTA **85%** on their edit benchmark and
lifted weaker models (GPT-4o-mini, Sonnet) over their solo baselines. By forcing the model to first
*name the edit sites* and then *fill a known-good checklist*, we remove the free-form reflection that
currently invents "the loader is buggy." The plan template encodes the truth ("the fix is 6 edits
across N files") structurally, so the model can't wander to "the file is bad" — the checklist has no
box for that. Cline enforces the same Plan/Act boundary (read-only Plan mode cannot write files).

**Source.** Aider Architect/Editor (85%, why splitting helps weak models):
https://aider.chat/2024/09/26/architect.html · Aider repo-map (tree-sitter + PageRank):
https://aider.chat/2023/10/22/repomap.html · Cline Plan/Act:
https://docs.cline.bot/core-workflows/plan-and-act

### 3. Summarize search/read output and hard-force the observe→act transition — kills the grep/read spiral

**Mechanism.**
- **Summarized search** (SWE-agent ACI): `grep_source` should return *files with match counts*
  first ("ggml-common.h: 3 matches, ggml.c: 1 match"), and only expand to lines on request.
  SWE-agent found showing per-match context "proved too confusing for the model."
- **Stateful bounded viewer**: cap `read_source` to ~100 lines/turn with scroll, not 200-line dumps.
- **Action budget**: after K read/grep calls *with no edit*, the harness injects a hard directive:
  "You have localized enough. Emit the plan checklist now, then the first edit_source." This is a
  targeted version of our existing loop-breaker but keyed on *investigation without action*, not on
  *identical repeats*. Keep SWE-agent's other guardrails we partly have: cap malformed-action
  requeries (we already feed truncated JSON back — `agent.py:94-100`), collapse old observations,
  and on step-cap **autosubmit the partial diff** rather than discarding the attempt.

**Why it fixes our failure.** "Spiral on grep/read, rarely commit" is precisely the failure SWE-agent's
summarized ACI + budgets were built to stop. Our loop-breaker only trips on *3× identical* calls; a
model exploring with *different* greps never trips it. Budgeting *investigation-without-edit*
converts endless reading into a forced plan+edit.

**Source.** SWE-agent ACI (summarized search, 100-line viewer, why raw context confuses):
https://swe-agent.com/0.7/background/aci/ · budgets/autosubmit/context-compression:
https://arxiv.org/pdf/2405.15793

### 4. Present FEWER tools, phase-gated — stop the model choosing wrong tools and ignoring RAG

**Mechanism.** Don't expose all ~19 tools every turn. Gate by phase:
- **Recon/Localize phase**: `detect_hardware`, `grep_source`, `read_source`, `search_knowledge`,
  `web_search`/`web_fetch`, `bench_decode` (to get the error). No edit tools offered.
- **Plan phase**: no tools — just produce the checklist.
- **Edit phase**: `edit_source` (search/replace), `write_file`, `rebuild`, `revert_source`,
  `remember`. Search tools still available but the *edit tools are now the salient choice*.
- **Verify phase**: `rebuild`, `bench_decode`, `measure_accuracy`, `log_finding`.

Auto-run `search_knowledge` for the model at localize time (push, don't pull) so the 927 seeded
chunks are actually used.

**Why it fixes our failure.** Fewer, phase-appropriate tools reduce the decision space that lets a
weak model default to "grep again." It also structurally nudges toward committing edits: in the edit
phase, the highest-salience tools *are* the editors. Pushing RAG fixes "rarely uses
search_knowledge." (General agent finding: large flat tool sets degrade tool-selection reliability;
SWE-agent's whole thesis is a *small, purpose-built* command set beats raw shell.)

**Source.** SWE-agent ACI design (small purpose-built command set):
https://swe-agent.com/0.7/background/aci/ · https://arxiv.org/abs/2405.15793

### 5. Rebuild after EVERY edit + a constrained, rubric-driven diagnosis — turn the compiler into the loop's judge

**Mechanism.**
- **Compile-per-edit**: after each checklist item, `rebuild` (fast incremental target, e.g. just the
  object file or `llama-bench`), and feed the *first* compiler error back with ~10 lines of source
  context around it (Aider uses tree-sitter to show code context around each error, not raw logs;
  it retries up to 3×). A red build after editing the enum but before adding the block struct is
  *expected progress*, and the error message literally names the next checklist item ("incomplete
  type 'block_q...'") — this is the anti-misdiagnosis signal.
- **Constrained diagnosis**: replace the free-form OODA prompt (`agent.py:129-147`) with a
  *closed-form rubric* whose hypotheses are restricted to the checklist: "Which of the 6 edit steps
  is incomplete or wrong, given this compiler error? You may NOT conclude the model file is invalid —
  that hypothesis is ruled out by construction." Free reflection is what produced "plausible-but-wrong
  root causes"; a rubric with the wrong-answer removed cannot reach it.

**Why it fixes our failure.** The model misdiagnoses because it reasons *about* the bug abstractly.
The compiler is a ground-truth oracle that, edit-by-edit, tells it exactly which of the 6 steps
remains — replacing speculation with a mechanical next-step. Bounding the diagnosis to the checklist
makes "the loader is buggy" structurally unreachable. OpenHands' CodeAct data shows the *execution
feedback loop*, not model IQ, is what drove SWE-bench resolution up (53%→70s% on the same harness as
models improved, but the loop was the constant enabler).

**Source.** Aider lint/test loop with code-context errors, 3 retries:
https://aider.chat/docs/usage/lint-test.html and https://aider.chat/2024/05/22/linting.html ·
OpenHands CodeAct execution-feedback loop (53% SWE-bench Verified, loop-driven):
https://www.openhands.dev/blog/openhands-codeact-21-an-open-state-of-the-art-software-development-agent

---

## Part 2 — Which LOCAL model should be the brain (ranked)

**Bottom line: switch from the 35B-A3B general MoEs to a DENSE, agentic-trained coder — first choice
`Devstral Small` (24B dense), fallback `Qwen3-Coder-30B-A3B`.** Our current brains
(AgentWorld-35B-A3B, Qwen3.6-35B-A3B-ThinkingCoder) activate only ~3B params/token; reliable
tool-calls and strict edit-format adherence come from *full-capacity* instruction-following, and
they were not trained on real agent rollouts — so a "ThinkingCoder" narrates a fix and stalls without
emitting the tool call. That is our exact "won't commit edits" symptom.

| Rank | Model | Type | Quant / GGUF size | Fits R9700 32GB? | SWE-bench Verified (scaffold) | aider polyglot | Why |
|---|---|---|---|---|---|---|---|
| **1** | **Devstral Small** (24B, Mistral+AllHands) | **Dense 24B** | Q4_K_M ~14–15GB (Q6 ~19GB, Q8 ~25GB all fit) | Yes — ~17GB free for KV | **53.6%** (2507) → **68.0%** (2512, vendor) via OpenHands | n/a | **Purpose-built for the SWE-agent/OpenHands loop.** RL'd on read→edit→run→iterate trajectories; native tool-calling + XML edit formats. Dense = every param attends to the tool schema each token. Apache-2.0. |
| 2 | **Qwen3-Coder-30B-A3B-Instruct** | MoE 30.5B/3.3B active | UD-Q4_K_XL **17.7GB** | Yes — ~14GB free | **51.6%** (OpenHands, 100 turns) | ~60.9% | Explicit "function-call format," strong tool-caller, long context. But A3B — shares the 3B-active flakiness that bites us now. Prefer only if dense Devstral won't load. |
| 3 | Qwen2.5-Coder-32B-Instruct | Dense 32B | Q4_K_M **19.9GB** | Yes — ~12GB free | ~30% (needs external agent) | **16.4%** whole / 8.0% diff | Superb *code editor inside an aider loop*, but NOT agentic-trained — weak at self-driving tool-use. Good as the **Editor** model in an Architect/Editor split. |
| 4 | Codestral 25.01 (22B) | Dense 22B | Q4_K_M ~13GB | Yes | low | 11.1% whole | Fast completion, weak multi-file agentic edits. Not recommended for the loop. |
| — | GLM-4.5-Air (106B/12B MoE) | MoE | Q4 ~62GB | **Only across both R9700s (64GB)** | ~mid-50s% | — | Strong agent model but needs both cards — violates the "brain on ONE card" constraint. |
| — | DeepSeek-Coder-V2-Lite (16B), DeepSeek-V2.5, Qwen3-Coder-480B, GLM-4.5/4.6 (355B) | — | too small-&-old / too big | Skip / no | — | — | Either not agentic-trained (V2-Lite, 2024) or doesn't fit 32GB. |

**Why a dedicated dense coder beats our 35B-A3B (the crux of our failure):**
1. **Dense vs sparse active params.** Devstral's full 24B attend to the tool schema and edit-format
   on *every* token; a 3B-active router is far flakier at "emit a valid tool call, then actually
   apply the edit." Reliable JSON/diff adherence is a full-capacity behavior.
2. **Agentic SFT/RL on real PRs and full rollouts.** Devstral/Qwen-Coder learned *the loop* — commit
   edits, call tools, hit stop conditions. A general "ThinkingCoder" over-reasons and stalls. This is
   literally the "narrates a fix but won't commit" pathology.
3. **The polyglot score is a trap.** Our A3B scores well on aider polyglot, but polyglot is
   *single-file, single-turn* edits with retries — not a multi-file autonomous tool-calling loop.
   **SWE-bench-Verified-via-scaffold** (what Devstral optimizes) is the metric that predicts our
   workload; polyglot does not.

**Recommendation.** Serve **Devstral Small 24B at Q4_K_M** on the brain card (leaves ample KV
headroom for our long context). If the current lemonade/llama.cpp build can't load the newest
Devstral weights, use the **2507** release (53.6%) or **Qwen3-Coder-30B-A3B** (17.7GB). Optionally
run **Architect = Devstral, Editor = Qwen2.5-Coder-32B** if we implement the plan/edit split (#2) and
have VRAM/time for two model loads — but a single dense Devstral is the simplest reliable win.

**Sources.** aider leaderboards https://aider.chat/docs/leaderboards/ · Devstral 2512 (68.0%)
https://mistral.ai/news/devstral-2-vibe-cli/ · Devstral 2507 (53.6%) https://mistral.ai/news/devstral-2507/
· HF Devstral card https://huggingface.co/mistralai/Devstral-Small-2-24B-Instruct-2512 · Qwen3-Coder-30B-A3B
https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct (SWE-bench repro 51.6%: discussions/30) ·
GGUF sizes: unsloth Qwen3-Coder-30B-A3B-GGUF (Q4_K_XL 17.7GB), bartowski Qwen2.5-Coder-32B-GGUF (Q4_K_M 19.9GB).
*Caveat:* Devstral-2512's 68% is a late-2025/2026 vendor figure not yet cross-listed on aider's board;
the 2507 53.6% is the conservative, independently-reported number.

---

## Part 3 — Reference architecture: how the loop SHOULD be structured

Replace the current single flat OODA-retry loop with an explicit **phased state machine**. Each phase
exposes only its tools (#4) and has an exit gate. This maps directly onto the existing files.

```
                         ┌─────────────────────────────────────────────┐
                         │  per model target (Bonsai-Q2 first, then fp8) │
                         └─────────────────────────────────────────────┘
   ┌──────────┐   error   ┌───────────┐  edit-sites  ┌──────────┐  checklist  ┌──────────┐
   │ 0 RECON  ├──────────▶│ 1 LOCALIZE├─────────────▶│ 2 PLAN   ├────────────▶│ 3 EDIT   │
   │ hw+bench │           │ read-only │  + pushed    │ fill the │             │ 1 hunk / │
   │ get real │           │ summarized│  RAG chunks  │ 6-step   │             │ file at  │
   │ error    │           │ grep+RAG  │              │ template │             │ a time   │
   └──────────┘           └───────────┘              └──────────┘             └────┬─────┘
        ▲                       ▲  budget: K reads w/o edit → force PLAN            │
        │                       │                                                   │ rebuild
        │  next model           │        compiler error names next step            ▼
        │                       │   ┌──────────┐   red build   ┌─────────────────────┐
        │  all steps green      └───┤ 5 DIAGNOSE│◀──────────────┤ 4 COMPILE (per edit)│
        │  + loads + benched        │ rubric:   │               │ feed 1st error +    │
   ┌────┴─────────┐  green build     │ which of 6│  green build  │ ~10 lines context   │
   │ 6 VERIFY     │◀─────────────────│ steps?    │──────────────▶│ (retry ≤3)          │
   │ load+ppl+t/s │                  │ NOT "file │               └─────────────────────┘
   │ log_finding  │                  │  is bad"  │
   └──────────────┘                  └───────────┘
```

**Phase contract:**
- **0 Recon** — detect hardware, `bench_decode` to surface the real load error verbatim. (Have this.)
- **1 Localize (read-only, no edit tools)** — summarized `grep_source` (files+counts) + bounded
  `read_source` (~100 lines). **Harness auto-runs `search_knowledge(error)`** and injects top seeded
  chunks. Exit gate: the model outputs the concrete `file:line` **edit-site list**. Budget: after K
  reads with no edit-site list, force exit.
- **2 Plan (no tools)** — fill the hard-coded fix template
  (`enum → type_traits → block struct → dequant → CPU dispatch → GPU dispatch`) with the specific
  files/symbols. This is the Architect step; "file is invalid" is not a template option.
- **3 Edit** — execute ONE checklist item with the **tolerant search/replace** or **whole-file**
  tool. Surgical: one hunk/file, then compile.
- **4 Compile (per edit)** — incremental `rebuild`; on error, feed the *first* error + ~10 lines of
  context. Green partial build = progress; a "type incomplete" error *names the next step*.
- **5 Diagnose (rubric, only on stuck build)** — closed-form: "which of the 6 steps is wrong, given
  this error? You may not conclude the file is invalid." Replaces free-form OODA.
- **6 Verify** — full `rebuild` + `bench_decode` (loads?) + `measure_accuracy` + `log_finding`;
  then optimize (existing levers). Report `BEST:`.

**How this maps onto the existing code (minimal surgery):**
- `codetools.py` — replace `edit_source` exact-match body with tolerant search/replace; add
  `write_file`; make `grep_source` return file+count summaries by default.
- `agent.py::run_attempt` — turn the flat step loop into the phase machine; gate the `tools` list per
  phase; change the loop-breaker to fire on *reads-without-edit*, and autosubmit partial diff on cap.
- `agent.py::diagnose` — swap the free-form OODA prompt for the closed-form rubric bound to the
  6-step checklist.
- `memory.py` — call `search_knowledge` from the harness at Localize (push RAG) instead of relying on
  the model to invoke it.
- `agent.py` config — point `BRAIN` at Devstral Small 24B Q4_K_M.

**Priority order to implement (fixes the misdiagnose-and-won't-commit failure fastest):**
1. Tolerant search/replace + whole-file edit tool (Part 1 #1) — unblocks *committing* edits.
2. Localize→Plan checklist with pushed RAG (#2) — stops the *misdiagnosis* at its root.
3. Constrained rubric diagnosis + compile-per-edit (#5) — makes "loader is buggy" unreachable.
4. Swap brain to Devstral Small 24B (Part 2) — dense agentic coder that actually commits.
5. Summarized search + investigation-budget + phase-gated tools (#3, #4) — ends the spiral.

Changes 1–3 are harness-only and independent of the model; do them first, then swap the brain — the
harness fixes make *any* model more reliable, and the dense agentic coder compounds them.

---

## Sources
- Aider — unified diffs & tolerant patching (20%→61%; ~900% fewer edit errors w/ flexible matching): https://aider.chat/docs/unified-diffs.html
- Aider — edit formats (whole = easiest for LLMs; weak models default to whole): https://aider.chat/docs/more/edit-formats.html
- Aider — edit-format leaderboard (two metrics: solved % vs valid-edit %): https://aider.chat/docs/leaderboards/edit.html · main board: https://aider.chat/docs/leaderboards/
- Aider — Architect/Editor split (85% SOTA; why splitting helps weak models): https://aider.chat/2024/09/26/architect.html
- Aider — repo-map (tree-sitter + PageRank localization): https://aider.chat/2023/10/22/repomap.html · https://aider.chat/docs/repomap.html
- Aider — lint/test auto-fix loop (code-context errors, 3 retries): https://aider.chat/docs/usage/lint-test.html · https://aider.chat/2024/05/22/linting.html
- SWE-agent — ACI design (summarized search, 100-line viewer, guardrails): https://swe-agent.com/0.7/background/aci/ · paper: https://arxiv.org/abs/2405.15793 (pdf: https://arxiv.org/pdf/2405.15793)
- OpenHands — CodeAct execution-feedback loop (53% SWE-bench Verified): https://www.openhands.dev/blog/openhands-codeact-21-an-open-state-of-the-art-software-development-agent
- Cline — Plan/Act separation: https://docs.cline.bot/core-workflows/plan-and-act · tolerant/anchor matching: https://github.com/cline/cline/issues/2909
- Devstral Small — Mistral+AllHands agentic coder: 2507 (53.6%) https://mistral.ai/news/devstral-2507/ · 2512 (68.0%) https://mistral.ai/news/devstral-2-vibe-cli/ · HF card: https://huggingface.co/mistralai/Devstral-Small-2-24B-Instruct-2512
- Qwen3-Coder-30B-A3B (51.6% SWE-bench via OpenHands; Q4_K_XL 17.7GB): https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct · GGUF: https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF
- Qwen2.5-Coder-32B (aider polyglot 16.4% whole; Q4_K_M 19.9GB): https://huggingface.co/bartowski/Qwen2.5-Coder-32B-Instruct-GGUF
- GLM-4.5 (64.2% SWE-bench, needs >32GB): https://arxiv.org/abs/2508.06471
