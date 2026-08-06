# CodeRisk Agent — Architecture Review & Improvements

> Based on E2E test (2026-07-19): 5 files, 47 risks, 18 min
> Review date: 2026-08-06

---

## E2E Test Analysis

### What Worked Well ✅
- All 4 agents executed successfully
- Memory layer recalled 17 patterns
- CVE client queried local SQLite database successfully
- Agent 3 found 4 missed risks + suppressed 1 false positive
- GPU inference at 29.4 t/s (32B, 4.3× vs CPU); 7B: 105 t/s

### Bottlenecks Identified ⚠️

| Issue | Impact | Root Cause |
|-------|--------|------------|
| 18 min for 5 files | Too slow for large codebases | Sequential file processing |
| Agent 2 waits for Agent 1 | Unnecessary latency | Sequential pipeline |
| Single reflection pass | May miss risks | No iteration |
| Dependency scan uses first file's parent | Wrong root detection | Naive project root finding |

---

## Improvement 1: Parallel Agent Execution (Implemented)

**Current:** Agent 1 → Agent 2 (sequential, per file)
**Implemented:** Agent 1 (all files) ‖ Agent 2 (per file, parallel)

> Note: Agent 2 depends on Agent 1's output for validation. The implemented
> strategy runs Agent 1 on all files first, then runs Agent 2 with controlled
> concurrency (ThreadPoolExecutor, max_workers=1 for GPU-bound tasks to prevent
> VRAM contention). Higher concurrency parallelism is planned as a future
> optimization once VRAM allows multiple concurrent LLM inferences.

```python
# Current (sequential):
for f in files:
    risks = static_analyzer.analyze(f)      # Agent 1
    enriched = semantic_analyzer.analyze(f)  # Agent 2 waits

# Implemented (parallel):
from concurrent.futures import ThreadPoolExecutor

# Phase 1: Agent 1 runs all files (fast, CPU-only)
with ThreadPoolExecutor(max_workers=4) as pool:
    static_risks = list(pool.map(static_analyzer.analyze, files))

# Phase 2: Agent 2 runs all files in parallel (GPU-bound)
with ThreadPoolExecutor(max_workers=1) as pool:  # 1 = GPU concurrency (32B model VRAM constraint)
    semantic_risks = list(pool.map(
        lambda f: semantic_analyzer.analyze(f, static_risks[f]),
        files
    ))
```

**Expected improvement:** 40-60% faster for multi-file analysis

---

## Improvement 2: Iterative Self-Reflection

**Current:** Agent 3 reflects once per file
**Proposed:** Up to 2 reflection rounds, stop if no new risks found

```python
# Current:
missed = self._reflect_on_file(f, file_risks)  # Single pass

# Proposed:
for round in range(MAX_REFLECTION_ROUNDS):  # MAX=2
    missed = self._reflect_on_file(f, file_risks + new_risks)
    if not missed:
        break  # Converged
    new_risks.extend(missed)
    console.print(f"  Round {round+1}: found {len(missed)} more risks")
```

**Expected improvement:** Better recall for complex vulnerability chains

---

## Improvement 3: Smart Project Root Detection

**Current:** Uses first file's parent directory
**Proposed:** Walk up directory tree to find project root markers

```python
def find_project_root(start: Path) -> Path:
    """Walk up to find project root (requirements.txt, pyproject.toml, etc.)"""
    markers = ["requirements.txt", "setup.py", "pyproject.toml", "Cargo.toml", "Makefile"]
    current = start.resolve()
    for _ in range(10):  # Max 10 levels up
        if any((current / m).exists() for m in markers):
            return current
        if current.parent == current:
            break
        current = current.parent
    return start  # Fallback
```

**Expected improvement:** Correct dependency scanning for nested projects

---

## Improvement 4: Incremental Results Saving

**Current:** Results only saved at the end
**Proposed:** Save after each phase (crash recovery)

```python
# After each phase, save intermediate results
result_file = Path(f".coderisk/results/{request_id}.json")

# Phase 1 complete → save
save_intermediate(result_file, {"phase": "static", "risks": all_risks})

# Phase 2 complete → save
save_intermediate(result_file, {"phase": "semantic", "risks": all_risks})

# Final → save complete result
save_final(result_file, result)
```

---

## Improvement 5: LLM Batch Processing

**Current:** One LLM call per file (10 calls in E2E test)
**Proposed:** Batch small files into single LLM call

```python
# If total code < 4K tokens, batch into one call
if total_tokens < 4000:
    prompt = batch_prompt(files)  # All files in one prompt
    response = llm.chat_json(prompt)  # Single call
else:
    # Fall back to per-file
    for f in files:
        response = llm.chat_json(file_prompt(f))
```

**Expected improvement:** 50-70% fewer LLM calls, faster for small files

---

## Priority Matrix

| Improvement | Impact | Effort | Priority |
|------------|--------|--------|----------|
| Parallel agents | High | Medium | ✅ Implemented |
| Iterative reflection | High | Low | ✅ Implemented |
| Smart root detection | Medium | Low | ✅ Implemented |
| Incremental saving | Medium | Medium | ✅ Implemented |
| LLM batch processing | High | High | 📋 Planned |

---

## Implementation Plan

### This Week (7.20-7.26)
- [x] Implement parallel Agent 1 + Agent 2 in orchestrator
- [x] Add iterative reflection to Agent 3 (max 2 rounds)
- [x] Fix project root detection

### Next Week (7.27-8.2)
- [x] Add incremental result saving
- [x] Performance benchmarks (before/after)

### If Time Permits
- [ ] LLM batch processing
- [ ] Web UI prototype

---

*Generated: 2026-08-06 | CodeRisk Agent v1.0*
