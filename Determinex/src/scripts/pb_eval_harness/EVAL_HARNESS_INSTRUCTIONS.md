# Determinex ProgramBench Full Eval Harness — Autonomous Execution Instructions

> **This file is the complete runbook for running all ProgramBench evals.**
> If you are an AI agent (Gemini Flash, Claude, Codex), read every section before executing anything.
> Do NOT skip sections. Do NOT improvise steps that are not listed here.
> The order matters. Follow it exactly.

---

## Context: What Happened and Why You Are Here

- ProgramBench has 200 tools. Each tool must be reimplemented and pass 100% of its test suite.
- **Prior to 2026-06-07**, evals were capped at 400 tests per tool. This was an artificial limit.
- **As of 2026-06-07**, the 400-test cap has been removed. All evals must now run the FULL test suite.
- Because of this, many tools that were counted as "locked" (passing 100%) are now reclassified as
  `pending_unlock` — they only passed the first 400 tests, not the full suite.
- **Your job**: Run every tool's existing submission through the uncapped eval harness, record the real
  scores, and update the index. Tools that pass 100% of the full suite get promoted to `strict_lock`.

## Current Score Reality (post-uncapping)

| Category | Count | Meaning |
|----------|-------|---------|
| `strict_lock` | 15 | Truly done — 100% full suite, 0 not_run |
| `upstream_skips` | 5 | 100% but have upstream-side skips (acceptable) |
| `ceiling_confirmed` | 7 | Cannot reach 100%, skip these |
| `pending_unlock` | 56 | Have submissions, need re-eval under full suite |
| `board_cache_only` | 117 | Have partial scores, need fix work + eval |

**Real aggregate score: 31.41% (100,471 / 319,881 tests)**

---

## Machine Requirements (Verify Before Starting)

```
OS:      Windows 10/11
Docker:  Running (Docker Desktop)
Python:  3.11+ with uv installed
RAM:     16GB+ recommended
CPU:     12-core system — can sustain heavy Docker load
Disk T:  100GB+ free on T: drive
```

---

## Step 1: Verify Pre-Flight (REQUIRED — do this first)

Run these commands. If any fail, stop and report the error.

```powershell
# 1a. Verify Docker is running
docker info

# 1b. Verify ProgramBench harness
cd T:\Dev\ProgramBench
uv run programbench --help

# 1c. Install psutil if not present (for accurate resource monitoring)
pip install psutil

# 1d. Verify the eval index exists
Test-Path C:\Dev\Determinex\corpus\programbench\eval_index.json

# 1e. Verify the locked directory has submissions
Get-ChildItem C:\Dev\Determinex\corpus\programbench\locked -Recurse -Filter submission.tar.gz | Measure-Object | Select-Object Count
```

**Expected outputs:**
- `docker info` → prints server info, no errors
- `programbench --help` → shows eval, info, blob commands
- `eval_index.json` exists → True
- Submission count → 56 or more

If any check fails, stop and report exactly which command failed and what the error was.

---

## Step 2: Run the Language Audit (One-Time Setup)

This generates `corpus/programbench/language_audit.md` — the ranked tool list with language detection.
Core-language tools (Rust, Go, C, C++, Python) run FIRST. Non-core (Java, Haskell, unknown) run LAST.

```powershell
cd C:\Dev\Determinex
python scripts\pb_eval_harness\pb_language_audit.py
```

**Expected output**: prints counts of core vs non-core tools, writes two files.
**Read the output**. Note which tools are flagged as non-core — these will appear at the bottom of the queue.

---

## Step 3: Run the Dry-Run (Required — Read the Queue First)

This shows exactly what will run, in what order, without executing anything.

```powershell
cd C:\Dev\Determinex
python scripts\pb_eval_harness\pb_full_eval_runner.py --dry-run --phase pending
```

**Read the output carefully.** The dry-run shows:
- Tool slug
- Old score (capped at 400 tests)
- `not_run` count (how many tests were never executed)
- Detected language
- Whether it is core-language (✓) or non-core (✗)

The queue order is:
1. Core-language `pending_unlock` tools, sorted by current score DESC (easiest wins first)
2. Non-core `pending_unlock` tools at the bottom

---

## Step 4: Run the Pending-Unlock Evals (Main Work)

This runs all 56 `pending_unlock` tools through the full uncapped eval harness, one at a time.

```powershell
cd C:\Dev\Determinex
python scripts\pb_eval_harness\pb_full_eval_runner.py --phase pending
```

### What This Does Automatically

For each tool in the queue, the harness will:

1. **Extract** the tool's `submission.tar.gz` from `corpus/programbench/locked/<tool>/` into
   `T:\determinex-programbench\full_evals_YYYYMMDD\<tool>_submission\`
2. **Run** `uv run programbench eval <submission_dir> --filter <tool_slug> --force`
   from `T:\Dev\ProgramBench`
3. **Capture** all output (stdout + stderr) to `T:\determinex-programbench\full_evals_YYYYMMDD\<tool>_result\`
4. **Parse** the result to extract: passed, failed, skipped, not_run, total, score%
5. **Classify** the new status:
   - `strict_lock` — passed == total, failed == 0, not_run == 0, skipped == 0
   - `upstream_skips` — passed == total, but some upstream-side skips (acceptable)
   - `near_lock` — score >= 95% (needs fix work)
   - `strong_candidate` — score >= 70%
   - `needs_work` — below 70%
6. **Update** `corpus/programbench/eval_index.json` with the real new score
7. **Log** result to `T:\determinex-programbench\full_evals_YYYYMMDD\run_log.jsonl`

### Resource Management (Automatic)

The harness monitors CPU/memory while running. Resource thresholds:

| Threshold | Value | Action |
|-----------|-------|--------|
| CPU pause | 88% sustained for 30s | Pause and wait |
| CPU resume | 70% | Resume next tool |
| Eval timeout | 30 minutes | Kill and mark timeout |

You will see resource status lines like:
```
  [RES] CPU=45.2%  MEM=62.1%  Docker=1 containers
```

**Do NOT manually kill the process** unless something is clearly broken.
The harness handles timeouts automatically.

### If a Tool Times Out

The harness marks it as `timeout` in the run log and moves to the next tool.
You do not need to intervene. Report timeout tools in your summary.

### If the Harness Crashes

If `pb_full_eval_runner.py` itself crashes (not a tool timeout), restart it with `--resume`:

```powershell
python scripts\pb_eval_harness\pb_full_eval_runner.py --phase pending --resume
```

`--resume` skips tools that already have a `completed` entry in the run log.

---

## Step 5: Monitor Progress (Optional — Run in a Second Terminal)

You can watch resource usage in real time:

```powershell
# Live resource snapshot every 10 seconds
while (1) {
    $cpu = (Get-WmiObject -Class Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
    $mem = (Get-WmiObject -Class Win32_OperatingSystem)
    $memPct = [math]::Round(100 - ($mem.FreePhysicalMemory / $mem.TotalVisibleMemorySize * 100), 1)
    $docker = (docker ps -q 2>$null | Measure-Object -Line).Lines
    Write-Host "$(Get-Date -Format 'HH:mm:ss')  CPU=${cpu}%  MEM=${memPct}%  Docker=${docker} containers"
    Start-Sleep 10
}
```

Or check the resource log directly:
```powershell
Get-Content T:\determinex-programbench\full_evals_YYYYMMDD\resource_log.jsonl -Tail 5
```
(Replace YYYYMMDD with today's date, e.g., 20260608)

---

## Step 6: Review the Results

When the pending-unlock phase completes, check the summary:

```powershell
# Human-readable summary
python -c "
import json, pathlib
summary = json.loads(pathlib.Path(r'T:\determinex-programbench\full_evals_YYYYMMDD\summary.json').read_text())
promoted = [r for r in summary['results'] if r['new_status'] in ('strict_lock', 'upstream_skips')]
regressed = [r for r in summary['results'] if r['new_pct'] < r['old_pct'] - 5]
print(f'=== RESULTS ===')
print(f'Total ran: {summary[\"total_ran\"]}')
print(f'New locks: {summary[\"total_promoted_to_lock\"]}')
print(f'Regressions: {summary[\"total_regressed\"]}')
print()
print('=== NEW LOCKS ===')
for r in promoted:
    print(f'  {r[\"slug\"]}: {r[\"old_pct\"]:.1f}% -> {r[\"new_pct\"]:.1f}% ({r[\"new_status\"]})')
print()
print('=== REGRESSIONS (need investigation) ===')
for r in regressed:
    print(f'  {r[\"slug\"]}: {r[\"old_pct\"]:.1f}% -> {r[\"new_pct\"]:.1f}% (DELTA {r[\"new_pct\"]-r[\"old_pct\"]:+.1f}%)')
"
```
(Replace YYYYMMDD with today's date)

**Report every promoted tool and every regression.** A regression means the full test suite exposed
failures that the capped 400-test run missed. These need investigation.

---

## Step 7: Identify Non-Core Language Tools for Later Work

After the pending-unlock phase, check which tools are flagged as non-core language.
These are placed at the bottom of the queue and should NOT be attempted until core tools are done.

```powershell
cd C:\Dev\Determinex
python -c "
import json, pathlib
audit = json.loads(pathlib.Path('corpus/programbench/language_audit.json').read_text())
non_core = [r for r in audit if not r['is_core'] and not r['skip']]
print('NON-CORE LANGUAGE TOOLS (need runtime setup before eval):')
for r in non_core:
    print(f'  {r[\"slug\"]}: {r[\"lang\"]} ({r[\"score_pct\"]:.1f}%)')
"
```

**These tools require:**
- Java tools: JDK + Maven/Gradle in the Docker image
- Haskell tools: GHC + Stack/Cabal
- Unknown tools: Investigation of the source to determine build requirements

**Do not attempt to lock these until the runtime is verified working.**

---

## Step 8: Run Board-Cache Tools (Optional — Wednesday Stretch Goal)

After the 56 pending-unlock tools are done, the board-cache tools (117 tools with partial scores)
can be run. These need fix work first, but some may already pass more tests with the full suite.

```powershell
python scripts\pb_eval_harness\pb_full_eval_runner.py --phase board
```

The board-cache phase will likely find many tools still failing. That is expected.
The goal is to establish accurate baseline scores post-uncapping.

---

## Output Location Reference

All outputs go to: `T:\determinex-programbench\full_evals_YYYYMMDD\`

| File | Contents |
|------|---------|
| `run_log.jsonl` | One JSON line per tool: slug, status, scores, elapsed time |
| `resource_log.jsonl` | CPU/memory/Docker samples every 5 seconds |
| `summary.json` | Final summary: promoted locks, regressions, totals |
| `<slug>_submission\` | Extracted submission files (compile.sh + source) |
| `<slug>_result\` | stdout.txt, stderr.txt, eval artifacts |

Updated index: `C:\Dev\Determinex\corpus\programbench\eval_index.json`

---

## Error Reference

| Error | Cause | Fix |
|-------|-------|-----|
| `Docker is not running` | Docker Desktop not started | Open Docker Desktop, wait for it to start |
| `ProgramBench harness not working` | uv not installed or wrong dir | `cd T:\Dev\ProgramBench && uv sync` |
| `No submission.tar.gz` | Tool never had a submission archived | Skip — report in summary |
| `Timeout (30 min)` | Docker container hung | Harness auto-kills, marks timeout, continues |
| `returncode != 0` | Eval ran but tests failed | Normal — record the score and move on |
| `eval_index.json write failed` | File locked | Retry — the harness retries index updates |

---

## What "Strict Lock" Actually Means (Post-Uncapping)

A tool is a `strict_lock` if and only if:
- `passed == total` (every test passed)
- `failed == 0`
- `not_run == 0` (no tests were skipped by the harness infrastructure)
- `skipped == 0` (no upstream-side pytest skips)

A tool is `upstream_skips` if:
- `passed == (total - skipped)` (all executable tests pass)
- `failed == 0`
- `not_run == 0`
- `skipped > 0` but these skips are from the upstream test suite (pytest.mark.skip, platform skips)

**The 400-test cap caused `not_run > 0` for many tools. That is why they were reclassified.**
After this harness runs, `not_run` should be 0 for every tool that had a valid submission.
If `not_run > 0` after a full eval, that means the harness itself had an infrastructure problem.
Report any `not_run > 0` cases — they need manual investigation.

---

## IMPORTANT: What NOT to Do

1. **Do NOT edit eval test fixtures** — the pytest tests in the Docker container are ground truth.
   Never modify them to make a tool appear to pass.

2. **Do NOT run multiple tools in parallel** — the harness is sequential by design.
   Docker on this machine cannot sustain parallel evals without CPU saturation.

3. **Do NOT manually update eval_index.json** — the harness updates it atomically after each eval.
   Manual edits during a run will be overwritten.

4. **Do NOT count a tool as locked** unless `not_run == 0 AND failed == 0`.
   "All tests passed that ran" is NOT a lock. `not_run > 0` means the test cap is still in effect
   or there is an infrastructure problem.

5. **Do NOT attempt non-core-language tools** without first verifying the runtime is in the
   Docker image. Java tools will fail with `javac not found` if JDK is not installed.

---

## Final Report (Required After All Phases Complete)

After ALL pending-unlock tools have been evaluated, write a brief report containing:

1. Total new strict locks promoted (count and list of slugs)
2. Total tools that regressed (were passing capped tests but fail full suite)
3. Total tools where `not_run > 0` after eval (infrastructure issues)
4. The updated aggregate score from `eval_index.json`
5. List of non-core-language tools that need runtime setup

This report goes in: `T:\determinex-programbench\full_evals_YYYYMMDD\FINAL_REPORT.md`

---

*Harness version: post-uncap-2026-06-08*
*All evals using this harness are marked with `last_eval_source: full_harness_post_uncap`*
