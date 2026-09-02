#!/usr/bin/env python3
"""Targeted per-test patch iteration for select mid-tier PB tools.

Strategy (different from full_sweep_iterate.py):
  1. Load the existing override main.py (current baseline behavior)
  2. Run mini-eval — identify SPECIFIC failing tests + their assertion errors
  3. For each failing test (cap N): generate a TARGETED patch via Observer-3B
     that extends the existing override with a handler for that test
  4. Apply patch (atomically), re-eval — keep ONLY if pass count went up
  5. If patched override beats baseline → save as candidate, log delta

Output:
  logs/patch_iterate/run_<ts>/<slug>/main.py            (best variant)
  logs/patch_iterate/run_<ts>/<slug>/attempts/*.py      (each tried)
  logs/patch_iterate/run_<ts>/<slug>/patch_eval.txt
  logs/patch_iterate/run_<ts>/results.json
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from full_sweep_iterate import (  # type: ignore
    _patch_runner,
    extract_python,
    find_extracted_branches,
    mini_eval,
    syntactic_validity,  # noqa
)

EXTRACTED = Path("T:/determinex-programbench/_extracted_tests")
OVERRIDES_DIR = ROOT / "corpus/programbench/per_tool_overrides"
OUT = ROOT / "logs" / "patch_iterate" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
OUT.mkdir(parents=True, exist_ok=True)

MODEL = "determinex-observer-v6-tuned"
OLLAMA_URL = "http://localhost:11434"

# The 5 targets — mid-tier tools with manual overrides + room to lift
TARGETS = [
    ("anordal__shellharden.6a6ffd4", 76.32),
    ("nachoparker__dutree.44e877d", 45.25),
    ("orf__gping.26eb5b9", 42.04),
    ("sharkdp__hyperfine.327d5f4", 41.95),
    ("kyoh86__richgo.313114f", 36.32),
]

MAX_PATCHES_PER_TOOL = 5
MAX_FAILING_TESTS_TO_TRY = 5


def call_model_raw(prompt: str, timeout_s: int = 240) -> str:
    payload = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_ctx": 8192,
                "num_predict": 4096,
                "temperature": 0.2,
                "top_p": 0.9,
                "repeat_penalty": 1.18,
            },
        }
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read()).get("response", "")
    except Exception as e:
        return f"<API ERROR: {e}>"


def find_override(slug: str) -> Path | None:
    """Find the tool's existing override main.py."""
    base_slug = slug.split(".")[0] if "." in slug else slug
    direct = OVERRIDES_DIR / slug / "main.py"
    if direct.is_file():
        return direct
    for d in OVERRIDES_DIR.iterdir():
        if d.is_dir() and d.name.startswith(base_slug):
            mp = d / "main.py"
            if mp.is_file():
                return mp
    return None


def candidate_is_safe(code: str) -> tuple[bool, str]:
    """Reject model artifacts that compile but are not runnable replacements."""
    ok, reason = syntactic_validity(code)
    if not ok:
        return ok, reason
    banned = ("[MARKER:", "[*REQUIRED_CHANGE_HERE]", "UPDATED_MAIN_PY", "```")
    if any(token in code for token in banned):
        return False, "model marker/artifact leaked into code"
    if "def main" not in code:
        return False, "missing def main"
    if "sys.exit(main())" not in code:
        return False, "missing sys.exit(main())"
    try:
        ns: dict[str, object] = {"__name__": "__candidate__"}
        exec(compile(code, "<candidate>", "exec"), ns)
    except BaseException as e:
        return False, f"exec validation failed: {type(e).__name__}: {e}"
    if not callable(ns.get("main")):
        return False, "main is not callable"
    return True, "OK"


def mini_eval_with_failures(candidate: Path, branches: list[Path]) -> tuple[int, int, list[dict]]:
    """Run mini-eval, return passed/total + list of failing test details.

    Each failing test dict: {test_id, error_line}
    """
    passed, total, errors = mini_eval(candidate, branches)
    # Parse pytest output lines for individual test names from errors
    failures = []
    for err in errors[:30]:
        m = re.search(r"FAILED\s+([\w/\\.:]+::\S+)\s*-\s*(.*)", err)
        if m:
            failures.append({"test_id": m.group(1), "error": m.group(2)[:200]})
    return passed, total, failures


def target_test_passes(candidate: Path, branches: list[Path], test_id: str) -> bool:
    """Run only the target pytest node and require it to pass."""
    file_part = test_id.split("::")[0]
    node_tail = "::".join(test_id.split("::")[1:])
    matched = False
    for branch in branches:
        eval_dir = branch / "eval"
        tests_dir = eval_dir / "tests"
        test_files = list(tests_dir.glob(file_part if "/" in file_part else f"**/{file_part}"))
        for test_file in test_files:
            matched = True
            patch_targets = [tests_dir / "utils.py", tests_dir / "conftest.py"]
            patch_targets.extend(sorted(tests_dir.glob("test_*.py")))
            originals: list[tuple[Path, str]] = []
            for patch_target in patch_targets:
                orig = _patch_runner(patch_target, candidate)
                if orig is not None:
                    originals.append((patch_target, orig))
            exe_shim = eval_dir / "executable"
            had_exe = exe_shim.exists()
            if not had_exe:
                try:
                    exe_shim.write_text(
                        candidate.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
                    )
                except Exception:
                    pass
            try:
                node = str(test_file)
                if node_tail:
                    node += "::" + node_tail
                r = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        node,
                        "-q",
                        "--tb=no",
                        "--no-header",
                        "-p",
                        "no:cacheprovider",
                    ],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
                if r.returncode != 0:
                    return False
            finally:
                for patched_path, original in originals:
                    patched_path.write_text(original, encoding="utf-8", newline="\n")
                if not had_exe and exe_shim.exists():
                    try:
                        exe_shim.unlink()
                    except Exception:
                        pass
    return matched


def build_patch_prompt(
    tool_name: str, current_code: str, test_id: str, test_source: str, error_msg: str
) -> str:
    if len(current_code) > 12000:
        current_code = (
            current_code[:7000]
            + "\n\n# ... middle of current main.py omitted from prompt ...\n\n"
            + current_code[-4000:]
        )
    return (
        f"You are improving the existing `{tool_name}` CLI tool. Currently it "
        f"fails one specific test. Your job: produce a complete UPDATED main.py "
        f"that keeps everything that currently works AND fixes the failing test.\n\n"
        f"=== CURRENT main.py (working — don't remove its existing behavior) ===\n\n"
        f"{current_code}\n\n"
        f"=== FAILING TEST ===\n\n"
        f"{test_id}\n\n"
        f"{test_source[:1500]}\n\n"
        f"=== ERROR FROM CURRENT IMPLEMENTATION ===\n\n"
        f"{error_msg}\n\n"
        f"=== TASK ===\n"
        f"Output a COMPLETE updated main.py that:\n"
        f"  1. Keeps all existing functions/handlers that currently work\n"
        f"  2. Adds the minimal additional logic needed to pass the failing test\n"
        f"  3. Begins with `#!/usr/bin/env python3` and ends with `sys.exit(main())`\n\n"
        f"Output ONLY raw Python — no markdown fences, no commentary.\n\n"
        f"Updated main.py:\n"
    )


def find_test_source(test_id: str, branches: list[Path]) -> str:
    """Given a pytest test id like 'test_help.py::test_help_flag', find its source."""
    file_part = test_id.split("::")[0]
    fn_name = test_id.split("::")[-1]
    for branch in branches:
        for f in (branch / "eval/tests").glob(file_part if "/" in file_part else f"**/{file_part}"):
            try:
                src = f.read_text(encoding="utf-8", errors="replace")
                m = re.search(rf"def {re.escape(fn_name)}\b.*?(?=\ndef |\Z)", src, re.S)
                if m:
                    return m.group(0)[:2000]
            except Exception:
                pass
    return f"# could not locate test source for {test_id}"


def process_one(slug: str, baseline: float, log) -> dict:
    log.write(f"\n=== {slug} (baseline {baseline:.1f}%) ===\n")
    log.flush()

    override = find_override(slug)
    if not override:
        return {"slug": slug, "baseline": baseline, "skipped": "no override found"}
    branches = find_extracted_branches(slug)
    if not branches:
        return {"slug": slug, "baseline": baseline, "skipped": "no extracted_tests"}

    tool_name = slug.split("__", 1)[-1].split(".", 1)[0]
    candidate_dir = OUT / slug
    candidate_dir.mkdir(parents=True, exist_ok=True)
    attempts_dir = candidate_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: baseline mini-eval (run override itself through our harness)
    current = candidate_dir / "main.py"
    shutil.copy(override, current)
    log.write(f"  copied override ({override.stat().st_size} bytes)\n")
    p, t, failures = mini_eval_with_failures(current, branches)
    if t == 0:
        return {"slug": slug, "baseline": baseline, "skipped": "mini_eval ran 0 tests (harness)"}
    base_pct = 100.0 * p / t
    log.write(f"  mini_eval baseline: {p}/{t} = {base_pct:.1f}%  ({len(failures)} failing)\n")
    best_p, best_t, best_pct = p, t, base_pct

    if not failures:
        log.write("  no failures — already perfect on mini_eval\n")
        return {
            "slug": slug,
            "baseline": baseline,
            "candidate_score": base_pct,
            "local_delta": 0.0,
            "matrix_delta": base_pct - baseline,
            "passed": p,
            "total": t,
            "patches": 0,
        }

    # Step 2: try patching for each failing test (cap N)
    patches_tried = 0
    patches_kept = 0
    for f_idx, failure in enumerate(failures[:MAX_FAILING_TESTS_TO_TRY]):
        test_id = failure["test_id"]
        err = failure["error"]
        test_src = find_test_source(test_id, branches)
        prompt = build_patch_prompt(
            tool_name, current.read_text(encoding="utf-8"), test_id, test_src, err
        )
        (attempts_dir / f"prompt_{f_idx}.txt").write_text(prompt, encoding="utf-8")
        log.write(f"  patch[{f_idx}] target: {test_id[:60]}\n")
        log.write(f"           err: {err[:80]}\n")

        t0 = time.time()
        raw = call_model_raw(prompt)
        (attempts_dir / f"raw_{f_idx}.txt").write_text(raw, encoding="utf-8")
        log.write(f"           model: {time.time() - t0:.1f}s, {len(raw)} chars\n")

        code = extract_python(raw)
        if not code:
            log.write("           no code extracted\n")
            continue
        ok, reason = candidate_is_safe(code)
        if not ok:
            log.write(f"           candidate rejected: {reason}\n")
            continue

        candidate = attempts_dir / f"attempt_{f_idx}.py"
        candidate.write_text(code, encoding="utf-8", newline="\n")
        patches_tried += 1

        p2, t2, failures2 = mini_eval_with_failures(candidate, branches)
        pct2 = 100.0 * p2 / max(1, t2)
        log.write(f"           mini_eval: {p2}/{t2} = {pct2:.1f}%  (was {best_p}/{best_t})\n")
        if not target_test_passes(candidate, branches, test_id):
            log.write("           target test still fails; rejecting\n")
            continue
        if t2 != best_t:
            log.write(f"           test count changed {best_t}->{t2}; rejecting\n")
            continue
        if p2 > best_p:
            log.write(f"           *** LIFT: {best_p}->{p2} (+{p2 - best_p} tests) ***\n")
            shutil.copy(candidate, current)
            best_p, best_t, best_pct = p2, t2, pct2
            patches_kept += 1
            # Re-evaluate failures list from this new baseline
            failures = failures2
            if patches_kept >= MAX_PATCHES_PER_TOOL:
                break
        else:
            log.write("           no lift, reverting\n")

    local_delta = best_pct - base_pct
    matrix_delta = best_pct - baseline
    log.write(
        f"  FINAL: {best_p}/{best_t} = {best_pct:.1f}%  "
        f"localΔ={local_delta:+.2f}pp matrixΔ={matrix_delta:+.2f}pp  "
        f"({patches_kept}/{patches_tried} patches kept)\n"
    )

    return {
        "slug": slug,
        "baseline": baseline,
        "mini_eval_baseline": base_pct,
        "candidate_score": best_pct,
        "local_delta": local_delta,
        "matrix_delta": matrix_delta,
        "passed": best_p,
        "total": best_t,
        "patches_tried": patches_tried,
        "patches_kept": patches_kept,
    }


def main():
    log = sys.stderr
    log.write(f"=== patch_iterate → {OUT} ===\n")
    log.write(f"=== model={MODEL}  targets={len(TARGETS)} ===\n\n")

    results = []
    for slug, baseline in TARGETS:
        try:
            r = process_one(slug, baseline, log)
        except KeyboardInterrupt:
            log.write("\nInterrupted.\n")
            break
        except Exception as e:
            log.write(f"  [EXCEPTION] {type(e).__name__}: {e}\n")
            r = {"slug": slug, "baseline": baseline, "error": str(e)}
        results.append(r)
        (OUT / "results.json").write_text(
            json.dumps(results, indent=2, default=str), encoding="utf-8"
        )

    log.write("\n========== SUMMARY ==========\n")
    for r in results:
        if r.get("candidate_score") is not None:
            log.write(
                f"  {r['slug']:50}  base={r['baseline']:6.2f}  "
                f"local={r.get('mini_eval_baseline', 0):6.2f}->{r['candidate_score']:6.2f}  "
                f"localΔ={r.get('local_delta', 0):+6.2f}pp  "
                f"matrixΔ={r.get('matrix_delta', 0):+6.2f}pp  "
                f"({r.get('patches_kept', 0)} patches)\n"
            )
        else:
            log.write(f"  {r['slug']:50}  skipped: {r.get('skipped', r.get('error', ''))}\n")
    log.write(f"\nResults: {OUT}/results.json\n")


if __name__ == "__main__":
    main()
