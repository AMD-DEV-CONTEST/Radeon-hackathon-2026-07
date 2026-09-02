#!/usr/bin/env python3
"""ProgramBench official-eval runner — the ONLY judge of true scores.

Wraps `uv run programbench eval` + parses the per-instance eval JSON.
Sha-keyed cache avoids re-evaluating identical submissions.

Public API:
    run_eval(instance_id, run_dir) -> EvalResult
        EvalResult.score    (int 0-100)
        EvalResult.passed   (int)
        EvalResult.total    (int)
        EvalResult.failures (list[dict] with name/message/test_code, capped at 5)
        EvalResult.cached   (bool — was this a cache hit?)
        EvalResult.error    (str | "" — set if eval crashed)

The cache lives at `c:/Dev/Determinex/logs/eval_cache/<sha>.json`.
Key = sha256 of the submission tarball.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import os as _os

PROGRAMBENCH_DIR = Path(_os.environ.get("PROGRAMBENCH_DIR", "T:/Dev/ProgramBench"))
DETERMINEX_ROOT = Path(_os.environ.get("DETERMINEX_ROOT", Path(__file__).resolve().parents[1]))
PB_STAGING_ROOT = Path(_os.environ.get("DETERMINEX_PB_STAGING_ROOT", "T:/determinex-staging"))
DOCKER_CONFIG_FALLBACK = PB_STAGING_ROOT / "docker-config"
EVAL_CACHE_DIR = DETERMINEX_ROOT / "logs" / "eval_cache"
EVAL_TIMEOUT = 1200  # 20 min per instance — generous for cold HF pulls
MAX_FAILURES_FED_BACK = 40  # was 12; DeepSeek 64K can hold the breadth signal

from programbench_resource_guard import build_eval_cmd, describe_policy  # noqa: E402


def _eval_env() -> dict[str, str]:
    """Environment for official eval subprocesses."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if not env.get("DOCKER_CONFIG"):
        DOCKER_CONFIG_FALLBACK.mkdir(parents=True, exist_ok=True)
        env["DOCKER_CONFIG"] = str(DOCKER_CONFIG_FALLBACK)
    return env


@dataclass
class EvalResult:
    score: int = 0  # 0-100
    passed: int = 0
    total: int = 0  # passed + failed (excludes not_run)
    not_run: int = 0  # tests missing from JUnit XML — invisible to score but block lock
    failures: list[dict] = field(default_factory=list)
    cached: bool = False
    error: str = ""
    eval_json_path: str = ""
    # Per-test status map: {test_name: "passed"|"failure"|"skipped"|"not_run"}.
    # Used to diff against prior attempt and surface "wins/regressions/persistent" to model.
    per_test: dict[str, str] = field(default_factory=dict)
    # Category aggregates — clusters of failures sharing root cause indicators.
    # Each: {category, count, sample_names, common_message}
    categories: list[dict] = field(default_factory=list)
    # Per-branch breakdown: {branch_hash: {passed, failed, not_run}}
    # Used to identify which branches are producing no JUnit output.
    branch_breakdown: dict[str, dict] = field(default_factory=dict)

    @property
    def is_lock(self) -> bool:
        """True only when official eval reports a perfect score."""
        return self.score >= 100 and self.total > 0

    def feedback_block(self) -> str:
        """Format failures for re-injection into the next attempt's prompt.
        Includes (1) failure-pattern summary at top so model sees ROOT-CAUSE clusters,
        (2) per-failure detail with EXPECTED vs ACTUAL + fixture content."""
        if self.error:
            return f"[Eval error: {self.error}]"
        if not self.failures:
            return ""
        n_failed = self.total - self.passed
        lines = [
            f"[Official ProgramBench eval ran: {self.passed}/{self.total} pass ({self.score}/100).]",
            "",
        ]
        # ── PRESERVATION DIRECTIVE — always first so model sees it before anything else ──
        if self.passed > 0:
            lines.append(
                f"⚠ PRESERVE {self.passed} PASSING TESTS: Your code currently passes {self.passed}/{self.total} tests."
            )
            lines.append(
                "  Do NOT regress them. Fix only what is explicitly listed as failing below."
            )
            lines.append("")
        # ── NOT_RUN / JUNIT PACKAGING ANALYSIS — second priority after preservation.
        # not_run means the test exists in tests.json but your binary produced no JUnit XML
        # for it. The gate COUNTS not_run as "not passing" — you cannot lock with any not_run.
        if self.not_run > 0 and self.branch_breakdown:
            silent_branches = [b for b, c in self.branch_breakdown.items() if c.get("silent")]
            partial_branches = [
                (b, c)
                for b, c in self.branch_breakdown.items()
                if c.get("not_run", 0) > 0 and not c.get("silent")
            ]
            lines.append(
                f"🔇 NOT_RUN WARNING: {self.not_run} tests are missing from your JUnit XML output."
            )
            lines.append(
                "   These tests exist in ProgramBench's test suite but your binary produced NO result for them."
            )
            lines.append(
                "   The gate CANNOT lock with any not_run tests — they count as unresolved."
            )
            lines.append("")
            if silent_branches:
                lines.append(
                    f"   SILENT BRANCHES ({len(silent_branches)}) — binary runs but emits NO JUnit XML at all:"
                )
                for b in silent_branches[:8]:
                    c = self.branch_breakdown[b]
                    lines.append(f"     branch {b}: 0 passed, 0 failed, {c['not_run']} not_run")
                lines.append(
                    "   FIX: These branches likely have a different invocation pattern (different flags,"
                )
                lines.append(
                    "        stdin format, or env vars) that your binary doesn't handle. The binary exits"
                )
                lines.append(
                    "        cleanly but produces no parseable output. Check compile.sh exec wrapper."
                )
            if partial_branches:
                lines.append(
                    f"   PARTIAL BRANCHES ({len(partial_branches)}) — some tests run, some not_run:"
                )
                for b, c in sorted(partial_branches, key=lambda x: -x[1]["not_run"])[:6]:
                    lines.append(
                        f"     branch {b}: {c['passed']} passed, {c['failed']} failed, {c['not_run']} not_run"
                    )
            lines.append("")
        # ── FAILURE PATTERN ANALYSIS — shows the model that 47 'ci_flag' failures
        # ── are ONE missing implementation, not 47 separate problems. THE highest-leverage
        # ── piece of feedback for breaking score plateaus.
        if self.categories:
            lines.append(f"━━━ FAILURE SIGNATURE ANALYSIS ({n_failed} total failures) ━━━")
            lines.append(
                "Failures clustered by SHAPE (returncode + stderr + assertion type) — each cluster = ONE distinct bug."
            )
            lines.append("")
            top_cat = self.categories[0] if self.categories else None
            top_pct = int(100 * top_cat["count"] / max(n_failed, 1)) if top_cat else 0
            if top_cat:
                lines.append(
                    f"⚡ YOUR SOLE OBJECTIVE THIS ATTEMPT: Fix cluster #1 ({top_cat['count']} tests, {top_pct}% of failures)."
                )
                lines.append(
                    "   Only after cluster #1 is at 0 failures should you touch anything else."
                )
                lines.append("")
            for i, c in enumerate(self.categories[:8], 1):
                pct = 100 * c["count"] / max(n_failed, 1)
                priority = "← FIX THIS ATTEMPT" if i == 1 else ("← next" if i == 2 else "")
                lines.append(f"  #{i}  [{c['count']:>3} tests, {pct:>4.1f}%]  {priority}")
                lines.append(f"        signature: {c['category']}")
                if c.get("sample_names"):
                    lines.append(
                        f"        tests in this cluster: {', '.join(c['sample_names'][:3])}"
                    )
                # Show 1-2 actual messages so model sees the failure shape, not a misleading "common" one
                for j, m in enumerate(c.get("sample_messages", [])[:2]):
                    snippet = m[:160].replace("\n", " ")
                    lines.append(f"        msg sample {j + 1}: {snippet}")
            lines.append("━━━ END SIGNATURE ANALYSIS ━━━")
            lines.append("")
        lines.append(
            f"Top {min(len(self.failures), MAX_FAILURES_FED_BACK)} individual failing tests (sampled across files for breadth):"
        )
        for f in self.failures[:MAX_FAILURES_FED_BACK]:
            lines.append(f"\n--- {f['name']} ---")
            # GROUND TRUTH (fix #4): if we ran the reference binary with this test's
            # input, show its output. Model MUST match this byte-exactly.
            ref = f.get("reference_output")
            ref_inv = f.get("reference_invocation")
            if (
                ref
                and ref.get("error") == ""
                and (ref.get("stdout") or ref.get("stderr") or ref.get("returncode") is not None)
            ):
                args_disp = ref_inv.get("args", []) if ref_inv else []
                stdin_disp = (ref_inv.get("stdin_preview", "") if ref_inv else "")[:120]
                lines.append(
                    "  REFERENCE BINARY OUTPUT (run original tool with these args/stdin — match byte-exactly):"
                )
                lines.append(f"    args:   {args_disp}")
                if stdin_disp:
                    lines.append(f"    stdin:  {stdin_disp}")
                lines.append(f"    returncode: {ref['returncode']}")
                if ref.get("stdout"):
                    lines.append("    stdout (first 400 chars):")
                    for ln in ref["stdout"][:400].split("\n")[:12]:
                        lines.append(f"      | {ln}")
                if ref.get("stderr"):
                    lines.append(f"    stderr (first 200 chars): {ref['stderr'][:200]}")
            fix_name = f.get("fixture_name", "")
            fix_content = f.get("fixture_content", "")
            if fix_name and fix_content:
                lines.append(f"  EXPECTED OUTPUT (from fixture {fix_name} — match byte-exactly):")
                for ln in fix_content.split("\n")[:30]:
                    lines.append(f"    | {ln}")
                if fix_content.count("\n") > 30:
                    lines.append(f"    | ... [+{fix_content.count(chr(10)) - 30} more lines]")
            exp = f.get("expected", "")
            act = f.get("actual", "")
            if exp or act:
                if exp:
                    lines.append(f"  EXPECTED (inline): {exp}")
                if act:
                    lines.append(f"  ACTUAL:   {act}")
            msg = f.get("message", "")[:600]
            lines.append(f"  Failure detail: {msg}")
            tc = f.get("test_code", "")[:1000]
            if tc:
                lines.append(f"  Test code: {tc}")
        return "\n".join(lines)


def _sha_submission(submission_tar: Path) -> str:
    h = hashlib.sha256()
    with submission_tar.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _cache_path(sha: str) -> Path:
    EVAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return EVAL_CACHE_DIR / f"{sha}.json"


def _run_preflight(instance_id: str, inst_dir: Path, submission: Path) -> str:
    """Return an error string if the cleanroom image/submission preflight fails."""
    source_dir = inst_dir / "source"
    cmd = [
        sys.executable,
        str(DETERMINEX_ROOT / "scripts" / "programbench_image_preflight.py"),
        instance_id,
        "--submission-tar",
        str(submission),
    ]
    if source_dir.is_dir():
        cmd += ["--source-dir", str(source_dir)]
    proc = subprocess.run(
        cmd,
        cwd=str(DETERMINEX_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_eval_env(),
        timeout=900,
    )
    if proc.returncode != 0:
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return f"preflight failed before official eval:\n{out[:4000]}"
    print(proc.stdout.strip())
    return ""


EXTRACTED_TESTS_ROOT = Path("T:/determinex-programbench/_extracted_tests")


def _resolve_fixture(instance_id: str, fixture_name: str, max_chars: int = 1500) -> str:
    """Try to find an extracted fixture file for this instance. Returns content or ''."""
    if not instance_id or not fixture_name:
        return ""
    base = EXTRACTED_TESTS_ROOT / instance_id
    if not base.is_dir():
        return ""
    # Search across all branches for matching fixture
    for branch_dir in base.iterdir():
        if not branch_dir.is_dir():
            continue
        for found in branch_dir.rglob(fixture_name):
            try:
                txt = found.read_text(encoding="utf-8", errors="replace")
                return txt[:max_chars]
            except Exception:
                continue
    return ""


def _categorize_failures(failed_results: list[dict], top_k: int = 8) -> list[dict]:
    """Cluster failures by FAILURE SIGNATURE (not test name keyword).

    Each failure gets a key derived from its actual symptoms:
      - returncode (1, 2, etc)
      - stderr fingerprint (first sentence of error message, normalized)
      - assertion shape (in stdout, in stderr, equality on returncode, etc)

    This produces clusters like:
      "returncode=1 / stderr='unexpected end of JSON input'" — 23 tests
      "returncode=0 / stdout-table-mismatch (+----+ vs +---+)" — 47 tests
      "returncode=2 / argparse: unrecognized argument" — 9 tests

    vs the old test-name-keyword approach which created phantom clusters like
    "all 13 tests with 'version' in name" (which actually failed for 13 different reasons).
    """
    import re

    sigs: list[tuple[str, str, str]] = []  # (signature_key, test_name, msg_excerpt)

    for r in failed_results:
        name = r.get("name", "") or ""
        extra = r.get("extra") or {}
        msg = str(extra.get("message", ""))

        # Parse CompletedProcess fields if present
        cp = _extract_completed_process(msg)

        # Component 1: returncode (most predictive single signal)
        rc = cp.get("returncode")
        rc_part = f"rc={rc}" if rc is not None else "rc=?"

        # Component 2: stderr fingerprint — first line of stderr, normalized
        stderr_raw = cp.get("stderr") or ""
        stderr_clean = stderr_raw.strip("b'\"").strip()
        # Strip Python tracebacks down to the final exception line for clustering
        if "Traceback" in stderr_clean:
            lines = [l for l in stderr_clean.split("\\n") if l.strip()]
            stderr_clean = lines[-1] if lines else stderr_clean
        # First "sentence" or first 80 chars
        stderr_sig = re.split(r"[.\\n]", stderr_clean, maxsplit=1)[0][:80].strip()

        # Component 3: assertion shape (what was being checked)
        assertion_shape = ""
        if "in stdout" in msg.lower():
            assertion_shape = "in_stdout"
        elif "in stderr" in msg.lower():
            assertion_shape = "in_stderr"
        elif re.search(r"returncode\s*==", msg):
            assertion_shape = "returncode_eq"
        elif "stdout ==" in msg.lower():
            assertion_shape = "stdout_eq"
        elif "stderr ==" in msg.lower():
            assertion_shape = "stderr_eq"
        elif "assert" in msg.lower():
            assertion_shape = "assert_other"

        # Build signature key — combination of (returncode, assertion shape, stderr fingerprint)
        if stderr_sig:
            key = f"{rc_part} + {assertion_shape}: stderr='{stderr_sig}'"
        elif assertion_shape:
            key = f"{rc_part} + {assertion_shape}"
        else:
            # Fallback: prefix of assertion message
            key = f"{rc_part} + {msg[:60].strip()}"

        sigs.append((key, name, msg[:200]))

    # Aggregate
    by_cat: dict[str, list[tuple[str, str]]] = {}
    for key, name, msg in sigs:
        by_cat.setdefault(key, []).append((name, msg))

    cats = []
    for key, items in by_cat.items():
        cats.append(
            {
                "category": key[:200],
                "count": len(items),
                "sample_names": [n for n, _ in items[:3]],
                # Include sample MESSAGES (one per test) so model sees variety even within a cluster
                "sample_messages": [m for _, m in items[:2]],
            }
        )
    cats.sort(key=lambda c: -c["count"])
    return cats[:top_k]


def _extract_fixture_path(test_code: str) -> str:
    """Best-effort: find a fixture filename referenced in the test code."""
    import re

    # Common patterns:
    #   REPO_ROOT / "eval" / "tests" / "data" / "default_table.txt"
    #   "test_resources/test_core/expected_output.txt"
    #   open("data/foo.txt")
    # Look for any quoted *.txt or *.json file reference.
    candidates = re.findall(r"['\"]([\w./-]+\.(?:txt|json))['\"]", test_code)
    if not candidates:
        return ""
    # Prefer ones in `data` or `test_resources` paths
    for c in candidates:
        if "test_resources" in c or "/data/" in c or "data\\" in c:
            return Path(c).name
    return Path(candidates[0]).name


def _parse_eval_json(
    eval_json_path: Path, instance_id: str = ""
) -> tuple[int, int, int, list[dict], str, dict[str, str], list[dict], dict[str, dict]]:
    """Returns (passed, total, not_run, failures, error_str, per_test_status, categories, branch_breakdown)."""
    try:
        d = json.loads(eval_json_path.read_text(encoding="utf-8"))
    except Exception as e:
        return 0, 0, 0, [], f"failed to parse eval JSON: {e}", {}, [], {}

    if d.get("error_code"):
        err = f"eval error_code={d['error_code']} details={str(d.get('error_details', ''))[:200]}"
        return 0, 0, 0, [], err, {}, [], {}

    results = d.get("test_results", [])
    passed = sum(1 for r in results if r.get("status") == "passed")
    failed_results = [r for r in results if r.get("status") == "failure"]
    not_run_results = [r for r in results if r.get("status") == "not_run"]
    failed = len(failed_results)
    not_run = len(not_run_results)
    total = passed + failed  # exclude not_run from denominator — matches board metric
    per_test: dict[str, str] = {
        r.get("name", ""): r.get("status", "") for r in results if r.get("name")
    }

    # Branch breakdown: tells the model which branches are emitting JUnit XML vs. silent.
    branch_breakdown: dict[str, dict] = {}
    for r in results:
        b = r.get("branch", "unknown")
        s = r.get("status", "")
        if b not in branch_breakdown:
            branch_breakdown[b] = {"passed": 0, "failed": 0, "not_run": 0}
        if s == "passed":
            branch_breakdown[b]["passed"] += 1
        elif s == "failure":
            branch_breakdown[b]["failed"] += 1
        elif s == "not_run":
            branch_breakdown[b]["not_run"] += 1
    # Category aggregation BEFORE diversification — clusters all 176 failures into ~8 patterns
    categories = _categorize_failures(failed_results, top_k=8)

    # Identify branches that are entirely silent (all not_run) — JUnit packaging failure signal.
    # These need different treatment than behavioral failures.
    for b, counts in branch_breakdown.items():
        counts["silent"] = counts["passed"] == 0 and counts["failed"] == 0 and counts["not_run"] > 0

    # FAILURE DIVERSIFICATION: instead of taking the FIRST 12 failures (which are
    # usually 12 variants of the same root-cause bug), sample failures across DIFFERENT
    # test FILES so the model sees the breadth of what's broken. This surfaces multiple
    # failure CLASSES per attempt instead of forcing the model to fix one class repeatedly.
    by_file: dict[str, list[dict]] = {}
    for r in failed_results:
        name = r.get("name", "<unknown>")
        # Extract file: "tests.test_complex_scenarios.test_X" -> "tests.test_complex_scenarios"
        # OR "eval/tests/test_help.py::test_X" -> "eval/tests/test_help.py"
        if "::" in name:
            tfile = name.split("::", 1)[0]
        else:
            parts = name.rsplit(".", 1)
            tfile = parts[0] if len(parts) == 2 else name
        by_file.setdefault(tfile, []).append(r)

    # Round-robin: take 1 from each file, then 2nd, etc., until we hit MAX_FAILURES_FED_BACK.
    diversified: list[dict] = []
    file_keys = sorted(by_file.keys())
    while len(diversified) < MAX_FAILURES_FED_BACK and file_keys:
        for fk in list(file_keys):
            if not by_file[fk]:
                file_keys.remove(fk)
                continue
            diversified.append(by_file[fk].pop(0))
            if len(diversified) >= MAX_FAILURES_FED_BACK:
                break

    failures = []
    for r in diversified:
        extra = r.get("extra") or {}
        msg = str(extra.get("message", ""))
        text = str(extra.get("text", ""))
        # STRUCTURED EXTRACTION (fix A v1): inline assertion patterns
        expected, actual = _extract_expected_actual(text, msg)
        # FIXTURE FILE RESOLUTION (fix A v2): if test references an external fixture
        # file (e.g. `data/expected_output.txt`), read it and surface the EXPECTED
        # output to the model. This is the actual ground truth for byte-exact tests.
        fixture_name = _extract_fixture_path(text)
        fixture_content = _resolve_fixture(instance_id, fixture_name) if fixture_name else ""
        failures.append(
            {
                "name": r.get("name", "<unknown>"),
                "message": msg[:800],
                "test_code": text[
                    :1200
                ],  # bumped from 600 — tests with file fixtures need more context
                "expected": expected,
                "actual": actual,
                "fixture_name": fixture_name,
                "fixture_content": fixture_content,
            }
        )
    return passed, total, not_run, failures, "", per_test, categories, branch_breakdown


def _extract_expected_actual(test_code: str, fail_msg: str) -> tuple[str, str]:
    """Best-effort regex parse of pytest assertion + failure message.
    Returns (expected_str, actual_str). Both may be empty if extraction failed."""
    import re

    expected, actual = "", ""
    m = re.search(
        r"assert\s+(?:result|out|res|r)\.(stdout|stderr|returncode)\s*==\s*(.+?)\s*$",
        test_code,
        re.MULTILINE,
    )
    if m:
        expected = f"{m.group(1)} == {m.group(2)[:200]}"
    cp = _extract_completed_process(fail_msg)
    if cp.get("returncode") is not None:
        parts = [f"returncode={cp['returncode']}"]
        if cp.get("stdout"):
            parts.append(f"stdout={cp['stdout'][:200]}")
        if cp.get("stderr"):
            parts.append(f"stderr={cp['stderr'][:300]}")
        actual = "  ".join(parts)
    return expected[:300], actual[:500]


def _extract_completed_process(fail_msg: str) -> dict:
    """Parse a pytest failure message for the CompletedProcess(...) repr.

    Captures args, returncode, stdout, stderr as structured fields. Tolerates
    multiple message shapes (`+ where X = CompletedProcess(...)`, inline reprs, etc).
    Returns dict with optional keys: args, returncode, stdout, stderr.
    """
    import re

    out: dict = {}
    cp = re.search(
        r"CompletedProcess\(\s*args=(\[[^\]]*\])\s*,\s*returncode=(\-?\d+)"
        r"(?:\s*,\s*stdout=(b?(?:[\"'][^\"']*[\"']|None)))?"
        r"(?:\s*,\s*stderr=(b?(?:[\"'][^\"']*[\"']|None)))?\s*\)",
        fail_msg,
        re.DOTALL,
    )
    if cp:
        out["args"] = cp.group(1)[:300]
        out["returncode"] = int(cp.group(2))
        if cp.group(3):
            out["stdout"] = cp.group(3)
        if cp.group(4):
            out["stderr"] = cp.group(4)
    return out


def run_eval(
    instance_id: str,
    run_dir: Path,
    force: bool = False,
    use_cache: bool = True,
) -> EvalResult:
    """Run `programbench eval` against the submission for this instance.

    Args:
        instance_id: e.g. "psampaz__go-mod-outdated.bb79367"
        run_dir: T:/determinex-programbench/<run_name>/ — parent of <instance_id>/
        force: re-run even if eval.json already exists
        use_cache: check the sha-keyed cache before re-running
    """
    inst_dir = run_dir / instance_id
    if not inst_dir.is_dir():
        return EvalResult(error=f"instance dir missing: {inst_dir}")

    submission = inst_dir / "submission.tar.gz"
    if not submission.exists():
        return EvalResult(error="no submission.tar.gz to evaluate")

    preflight_error = _run_preflight(instance_id, inst_dir, submission)
    if preflight_error:
        return EvalResult(error=preflight_error)

    sha = _sha_submission(submission)
    cache_file = _cache_path(sha)

    # Cache hit
    if use_cache and cache_file.exists() and not force:
        try:
            d = json.loads(cache_file.read_text(encoding="utf-8"))
            return EvalResult(
                score=int(d.get("score", 0)),
                passed=int(d.get("passed", 0)),
                total=int(d.get("total", 0)),
                not_run=int(d.get("not_run", 0)),
                failures=d.get("failures", []),
                cached=True,
                error=d.get("error", ""),
                eval_json_path=d.get("eval_json_path", ""),
                per_test=d.get("per_test", {}),
                categories=d.get("categories", []),
                branch_breakdown=d.get("branch_breakdown", {}),
            )
        except Exception:
            pass  # fall through to re-eval

    # Run the harness with an absolute scaffold path because cwd changes to PROGRAMBENCH_DIR.
    author_filter = instance_id.split("__")[0]  # e.g. "psampaz" → narrows the scan
    cmd, policy = build_eval_cmd(
        scaffold_root=run_dir.resolve(),
        filter_re=author_filter,
        instance_id=instance_id,
        force=True,
    )
    if policy.quarantined:
        return EvalResult(error=f"eval quarantined by resource guard: {policy.reason}")
    print(f"  [pb-guard] {describe_policy(policy)}")
    env = _eval_env()

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROGRAMBENCH_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=policy.timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return EvalResult(error=f"eval timed out after {policy.timeout_seconds}s")
    except Exception as e:
        return EvalResult(error=f"eval subprocess error: {type(e).__name__}: {e}")

    # Parse the eval JSON the harness wrote (look in inst_dir for *.eval.json)
    eval_json: Path | None = None
    for p in inst_dir.glob("*.eval.json"):
        eval_json = p
        break
    if eval_json is None:
        # Try eval_report.json
        alt = inst_dir / "eval_report.json"
        if alt.exists():
            eval_json = alt
    if eval_json is None:
        # Fall back to parsing stdout score
        err = (proc.stderr or "") + "\n--- STDOUT ---\n" + (proc.stdout or "")
        # write full output to a log so we can diagnose without truncation
        log_dump = inst_dir / "eval_error.log"
        try:
            log_dump.write_text(err, encoding="utf-8", errors="replace")
        except Exception:
            pass
        return EvalResult(
            error=f"no eval JSON written (full output in {log_dump}); first 2000 chars:\n{err[:2000]}"
        )

    passed, total, not_run, failures, err, per_test, categories, branch_breakdown = (
        _parse_eval_json(eval_json, instance_id=instance_id)
    )
    score = round(100 * passed / total) if total > 0 else 0

    # GROUND-TRUTH INJECTION (fix #4): for the top failing tests, run the original
    # reference binary (still at /workspace/executable in the cleanroom image) with
    # the test's actual input and capture stdout/stderr/returncode. This is what the
    # model MUST produce to match. Single biggest unlock for byte-exact tests.
    if failures and not err:
        try:
            ref_env = _eval_env()
            if ref_env.get("DOCKER_CONFIG"):
                os.environ.setdefault("DOCKER_CONFIG", ref_env["DOCKER_CONFIG"])
            from reference_diff import diff_batch as _ref_diff

            image = f"programbench/{instance_id.replace('__', '_1776_')}:task_cleanroom"
            failures = _ref_diff(image, failures, max_n=6)
        except Exception as _e:
            print(f"  [ref-diff] skipped: {_e}")

    result = EvalResult(
        score=score,
        passed=passed,
        total=total,
        not_run=not_run,
        failures=failures,
        cached=False,
        error=err,
        eval_json_path=str(eval_json),
        per_test=per_test,
        categories=categories,
        branch_breakdown=branch_breakdown,
    )

    # Persist to cache (failures now include fixture_name/fixture_content + categories)
    try:
        cache_file.write_text(
            json.dumps(
                {
                    "instance_id": instance_id,
                    "submission_sha": sha,
                    "score": score,
                    "passed": passed,
                    "total": total,
                    "not_run": not_run,
                    "failures": failures,
                    "error": err,
                    "eval_json_path": str(eval_json),
                    "per_test": per_test,
                    "categories": categories,
                    "branch_breakdown": branch_breakdown,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    return result


# CLI for one-off use
def _main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("instance_id")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    r = run_eval(args.instance_id, args.run_dir, force=args.force)
    print(f"score={r.score}/100  passed={r.passed}/{r.total}  cached={r.cached}")
    if r.error:
        print(f"ERROR: {r.error}")
    if r.failures:
        print(f"\n{r.feedback_block()}")


if __name__ == "__main__":
    _main()
