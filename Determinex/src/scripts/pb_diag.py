#!/usr/bin/env python3
"""
pb_diag.py — ProgramBench instant diagnosis tool.

Given a tool slug, reads its best eval.json, extracts failing test tracebacks,
matches them against the KB pattern signatures, and suggests fixes.

Usage:
    python scripts/pb_diag.py <slug>            # diagnose failing tests
    python scripts/pb_diag.py <slug> --full     # show full tracebacks
    python scripts/pb_diag.py board             # show near-lock targets ranked
    python scripts/pb_diag.py cluster <pattern> # find all tools matching a pattern
    python scripts/pb_diag.py triage <slug>     # classify failures winnable vs impossible
    python scripts/pb_diag.py triage board      # rank near-lock tools by TRUE ceiling
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
BOARD_PATH = REPO / "logs" / "programbench_lock_board.json"
KB_PATH = REPO / "logs" / "pb_kb.json"

# Inline pattern signatures (duplicated from pb_kb.py so pb_diag works standalone)
PATTERN_SIGNATURES = {
    "version_string_ldflags": {
        "description": "Binary outputs 'dev'/'unknown' but golden expects pinned version string.",
        "signals": [
            "version dev",
            "gitversion:  dev",
            "gitversion:  unknown",
            'version = "dev"',
            "version 2.",
            "gitversion:  2.",
            "version unknown",
        ],
        "fix": (
            "Go ldflags: -X main.version=<expected> -X main.commit=<sha> -X main.date=<date>. "
            "Find expected values in golden files. Check main.go for var names."
        ),
    },
    "bin_name_argv0": {
        "description": "Error messages reference wrong binary name (executable vs real name).",
        "signals": ["executable: ", "exec -a", "argv[0]", "ambr:", "bin_name"],
        "fix": 'Use exec -a "<toolname>" in wrapper so argv[0] matches binary name in error messages.',
    },
    "rc_code_mismatch": {
        "description": "Tool returns wrong exit code for error conditions.",
        "signals": [
            "returncode == 1",
            "returncode == 2",
            "exit code 1",
            "exit code 2",
            "assert rc ==",
            "assert ret ==",
        ],
        "fix": "Run real upstream binary to check rc. Probe both rc=1 and rc=2 before patching — changing universally causes regressions.",
    },
    "version_prefix_v": {
        "description": "Version string has/lacks 'v' prefix vs what tests expect.",
        "signals": ["v1.", "v2.", "v0.", "assert '1.", "assert '2.", "lstrip"],
        "fix": "Strip 'v' prefix or add it in the version output. Use sed in wrapper.",
    },
    "tty_interactive_block": {
        "description": "Tool blocks waiting for TTY/interactive input; tests time out.",
        "signals": ["timeout", "timed out", "blocking", "--no-interactive", "stdin isatty"],
        "fix": 'Detect TTY in wrapper: [ -t 0 ] && exec bin "$@" || exec bin --no-interactive -y "$@"',
    },
    "is_a_directory": {
        "description": "Tool prints 'Is a directory' for directory args — test expects this behavior.",
        "signals": ["is a directory", "eisdir", "isdirectory"],
        "fix": "Replicate upstream 'Is a directory' error for directory paths in compile.sh or wrapper.",
    },
    "missing_binary_path": {
        "description": "Binary not found at expected path after compile.sh.",
        "signals": ["not found", "no such file", "command not found", "executable not found"],
        "fix": "Check compile.sh installs to /usr/local/bin/<name>. Verify executable wrapper path.",
    },
    "help_text_format": {
        "description": "Help text format differs from golden (spacing, capitalization, usage line).",
        "signals": [
            "usage:",
            "Usage:",
            "assert out ==",
            "help.txt",
            "help_stdout.txt",
            "AssertionError: assert '\\nusage",
        ],
        "fix": "Diff actual vs golden help text. Common issues: 'Usage:' vs 'usage:', extra newlines, version in header.",
    },
    "stdout_stderr_swap": {
        "description": "Tool writes to stdout when test expects stderr (or vice versa).",
        "signals": ["assert err ==", 'assert out == ""', "stderr", "assert stdout"],
        "fix": "Check if binary writes errors to stdout vs stderr. Use 2>&1 redirect or separate capture in wrapper.",
    },
}


# ---------------------------------------------------------------------------
# Impossibility classifier.
#
# Many ProgramBench "failures" are NOT implementation bugs — they are
# structurally unwinnable inside the offline eval container. Chasing them is
# pure waste. These signatures read the EXTRACTED TEST SOURCE (not just the
# traceback) and classify each failing test so an automated loop knows which
# failures are worth an agent's time and which are dead ends.
#
# Verdict taxonomy:
#   WINNABLE              — fixable in compile.sh / source; spend effort here.
#   IMPOSSIBLE_NETWORK    — asserts a real cloud/HTTP response (AWS error
#                           codes, ARNs, live endpoints). No network in eval.
#   IMPOSSIBLE_MOCK_STUB  — asserts success/behavior against a placeholder mock
#                           that does not actually serve (dead URL / returns
#                           None). Cannot pass for ANY binary, incl. upstream.
#   IMPOSSIBLE_MOCK_PARTIAL — uses an in-process mock that omits an operation
#                           the real binary must call (e.g. DescribeParameters).
#   IMPOSSIBLE_CONFLICT   — golden conflicts with another branch's golden for
#                           the same invocation (e.g. version dev vs pinned).
#   NEEDS_VENDORED_DEP    — test module import-errors on a pip package the
#                           offline container lacks (requests, boto3, moto).
# ---------------------------------------------------------------------------
EXTRACTED_TESTS_ROOT = Path("T:/determinex-programbench/_extracted_tests")

IMPOSSIBLE_SIGNATURES = {
    "IMPOSSIBLE_NETWORK": {
        "desc": "Asserts a live cloud/HTTP response; no network in eval container.",
        # Strings that can ONLY appear if a real remote service answered.
        "test_src_signals": [
            "AccessDeniedException",
            "UnauthorizedOperation",
            "arn:aws:",
            "ExpiredToken",
            "InvalidClientTokenId",
            "amazonaws.com",
            "ConnectTimeout",
            "could not connect to",
            "NoCredentialProviders",
        ],
    },
    "NEEDS_VENDORED_DEP": {
        "desc": "Test module import-errors on a pip dep absent offline.",
        "traceback_signals": [
            "ModuleNotFoundError: No module named 'requests'",
            "ModuleNotFoundError: No module named 'boto3'",
            "ModuleNotFoundError: No module named 'moto'",
            "ImportError while importing test module",
        ],
    },
    "IMPOSSIBLE_MOCK_STUB": {
        "desc": "Asserts behavior against a placeholder mock that never serves.",
        # Fixture admits it is a stub: returns a dead URL / None placeholder.
        "test_src_signals": [
            "For now, return None",
            "placeholder to show the approach",
            "Would be real mock server",
            "return 'http://localhost:4000'",
            'return "http://localhost:4000"',
            "needs actual mock server",
            "tests will need actual mock",
        ],
    },
}

# Operations a real AWS/SSM binary commonly calls that thin mocks omit.
_COMMON_OMITTED_OPS = [
    "DescribeParameters",
    "GetParametersByPath",
    "ListTagsForResource",
    "GetCallerIdentity",
]


def _read_extracted_test_source(slug: str, branch: str, test_name: str) -> str:
    """Best-effort: read the source of the failing test's module + function.

    test_name looks like 'tests.test_foo.TestBar.test_baz' or with an 'eval.'
    prefix. We locate eval/tests/<module>.py under the branch dir and return
    the whole module text (cheap, and lets us see fixtures it depends on).
    """
    base = EXTRACTED_TESTS_ROOT / slug / branch / "eval" / "tests"
    if not base.exists():
        # some datasets nest differently; fall back to a glob.
        root = EXTRACTED_TESTS_ROOT / slug
        if not root.exists():
            return ""
        parts = test_name.replace("eval.", "").split(".")
        mod = next((p for p in parts if p.startswith("test_")), "")
        if not mod:
            return ""
        for cand in root.rglob(f"{mod}.py"):
            try:
                return cand.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        return ""
    parts = test_name.replace("eval.", "").split(".")
    mod = next((p for p in parts if p.startswith("test_")), "")
    f = base / f"{mod}.py"
    if f.exists():
        try:
            return f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    return ""


def _extract_function_body(module_src: str, test_name: str) -> str:
    """Pull the source of the specific failing test function from a module.

    Falls back to the whole module if the function can't be isolated. Uses a
    simple indentation walk so we don't depend on importing the test module.
    """
    fn = test_name.split(".")[-1]
    lines = module_src.splitlines()
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        if stripped.startswith(f"def {fn}(") or stripped.startswith(f"async def {fn}("):
            indent = len(ln) - len(stripped)
            body = [ln]
            for nxt in lines[i + 1 :]:
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                    break
                body.append(nxt)
            return "\n".join(body)
    return module_src


def classify_failure(slug: str, fail: dict) -> tuple[str, str]:
    """Return (verdict, reason) for a single failing/errored test."""
    branch = fail.get("branch", "")
    name = fail.get("name", "")
    extra = fail.get("extra", {}) or {}
    tb = (extra.get("text", "") or "") + " " + (extra.get("message", "") or "")
    module_src = _read_extracted_test_source(slug, branch, name)
    fn_src = _extract_function_body(module_src, name)
    # Does THIS test depend on a mock-server fixture? (function-level, precise)
    uses_mock = "mock_ssm_server" in fn_src or "mock_server" in fn_src or "mock_ssm_server" in name

    # 1. Missing pip dep (collection-time import error).
    for sig in IMPOSSIBLE_SIGNATURES["NEEDS_VENDORED_DEP"]["traceback_signals"]:
        if sig in tb:
            dep = "requests/boto3/moto"
            for d in ("requests", "boto3", "moto"):
                if d in tb:
                    dep = d
                    break
            return ("NEEDS_VENDORED_DEP", f"import {dep} fails (offline)")

    # 2. Stub mock that never serves — only if THIS test actually uses the mock
    #    fixture AND the module's fixture is a stub.
    if uses_mock:
        for sig in IMPOSSIBLE_SIGNATURES["IMPOSSIBLE_MOCK_STUB"]["test_src_signals"]:
            if sig in module_src:
                return (
                    "IMPOSSIBLE_MOCK_STUB",
                    "uses placeholder mock fixture (dead URL / returns None)",
                )

    # 3. Live-cloud assertion — match only against the FUNCTION body's asserts,
    #    not mock response templates elsewhere in the module.
    for sig in IMPOSSIBLE_SIGNATURES["IMPOSSIBLE_NETWORK"]["test_src_signals"]:
        if sig in fn_src or sig in tb:
            # If the test uses a mock fixture, an AWS token is the mock's own
            # response, not a live-service requirement -> defer to mock checks.
            if not uses_mock or sig in tb:
                return (
                    "IMPOSSIBLE_NETWORK",
                    f"asserts live-service token {sig!r}; no network in eval",
                )

    # 4. Partial mock: traceback shows UnknownOperation for an op the binary
    #    must call but the mock omits.
    if "UnknownOperation" in tb or "Unknown:" in tb:
        for op in _COMMON_OMITTED_OPS:
            if op in tb:
                return ("IMPOSSIBLE_MOCK_PARTIAL", f"mock omits {op}; real binary requires it")
        return ("IMPOSSIBLE_MOCK_PARTIAL", "mock returned UnknownOperation")

    # 5. Version/golden conflict heuristic: a 'dev'/'unknown' expectation while
    #    another branch wants a pinned version (or vice versa).
    low = tb.lower()
    if (
        "version dev" in low
        or "gitversion:  dev" in low
        or "buildhash:  unknown" in low
        or "gitversion:  unknown" in low
    ):
        return (
            "IMPOSSIBLE_CONFLICT",
            "branch expects dev/unknown version; conflicts with pinned-version branch",
        )

    return ("WINNABLE", "no impossibility signal; likely fixable")


def cmd_triage(args):
    """Classify every failing test of a tool as winnable vs structurally impossible.

    Usage: pb_diag.py triage <slug>
           pb_diag.py triage board   # rank all near-lock tools by WINNABLE count
    """
    if args and args[0] == "board":
        return _triage_board()
    slug = args[0] if args else ""
    board = load_board()
    entry = find_board_entry(board, slug)
    if not entry:
        print(f"Tool not found in board: {slug!r}")
        sys.exit(1)
    eval_path = entry.get("best_eval_path") or entry.get("eval_path")
    real_slug = entry.get("slug", slug)
    passed = entry.get("best_passed", 0)
    total = entry.get("best_runnable_total", 0)

    failures = _get_failures_and_errors(eval_path)
    buckets: dict[str, list[tuple[str, str]]] = {}
    for f in failures:
        verdict, reason = classify_failure(real_slug, f)
        buckets.setdefault(verdict, []).append((f.get("name", ""), reason))

    winnable = len(buckets.get("WINNABLE", []))
    true_ceiling = passed + winnable

    print(f"\n{'=' * 64}\n  {real_slug}")
    print(f"  Current: {passed}/{total}   Failing: {len(failures)}")
    print(f"  WINNABLE failures: {winnable}")
    print(
        f"  TRUE CEILING (passed + winnable): {true_ceiling}/{total}"
        + ("   -> LOCKABLE" if true_ceiling == total else "   -> NOT lockable")
    )
    print(f"{'=' * 64}\n")
    order = [
        "WINNABLE",
        "IMPOSSIBLE_MOCK_STUB",
        "IMPOSSIBLE_MOCK_PARTIAL",
        "IMPOSSIBLE_NETWORK",
        "IMPOSSIBLE_CONFLICT",
        "NEEDS_VENDORED_DEP",
    ]
    for v in order:
        items = buckets.get(v, [])
        if not items:
            continue
        print(f"[{v}] x{len(items)}")
        for nm, reason in items:
            print(f"    - {nm.split('.')[-1]}: {reason}")
        print()


def _triage_board():
    board = load_board()
    rows = []
    for e in board:
        if e.get("locked_archive"):
            continue
        rt = e.get("best_runnable_total", 0)
        ps = e.get("best_passed", 0)
        if rt <= 0 or (rt - ps) == 0 or (rt - ps) > 12:
            continue
        eval_path = e.get("best_eval_path") or e.get("eval_path")
        slug = e.get("slug", "")
        fails = _get_failures_and_errors(eval_path)
        win = sum(1 for f in fails if classify_failure(slug, f)[0] == "WINNABLE")
        rows.append((win, rt - ps, ps + win == rt, e.get("best_score", 0), slug))
    # Lockable-after-winnable first, then most winnable.
    rows.sort(key=lambda r: (not r[2], -r[0], r[1]))
    print(f"\n{'Winnable':>9} {'Left':>5} {'Lockable':>9} {'Score':>8}  Slug")
    print("-" * 72)
    for win, left, lockable, score, slug in rows:
        mark = "YES" if lockable else "no"
        print(f"{win:>9} {left:>5} {mark:>9} {score:>7.2f}%  {slug}")


def _get_failures_and_errors(eval_path: str) -> list[dict]:
    p = Path(eval_path) if eval_path else None
    if not p or not p.exists():
        return []
    ev = json.loads(p.read_text(encoding="utf-8"))
    return [t for t in ev.get("test_results", []) if t.get("status") in ("failure", "error")]


def load_board() -> list[dict]:
    return json.loads(BOARD_PATH.read_text(encoding="utf-8"))


def load_kb() -> dict | None:
    if KB_PATH.exists():
        return json.loads(KB_PATH.read_text(encoding="utf-8"))
    return None


def find_board_entry(board: list[dict], slug: str) -> dict | None:
    slug_lower = slug.lower()
    for e in board:
        if e.get("slug", "").lower() == slug_lower:
            return e
        if e.get("base_slug", "").lower() == slug_lower:
            return e
        if slug_lower in (e.get("slug", "") or "").lower():
            return e
    return None


def get_failures(eval_path: str) -> list[dict]:
    """Extract failing tests with their traceback text from eval.json."""
    p = Path(eval_path)
    if not p.exists():
        return []
    ev = json.loads(p.read_text(encoding="utf-8"))
    results = ev.get("test_results", [])
    return [t for t in results if t.get("status") == "failure"]


def match_patterns(text: str) -> list[dict]:
    text_lower = text.lower()
    hits = []
    for pid, p in PATTERN_SIGNATURES.items():
        score = sum(1 for sig in p["signals"] if sig.lower() in text_lower)
        if score > 0:
            hits.append({"id": pid, "score": score, **p})
    return sorted(hits, key=lambda x: -x["score"])


def cmd_diagnose(slug: str, full: bool = False):
    board = load_board()
    entry = find_board_entry(board, slug)
    if not entry:
        print(f"Tool not found in board: {slug!r}")
        sys.exit(1)

    eval_path = entry.get("best_eval_path") or entry.get("eval_path")
    score = entry.get("best_score", 0)
    passed = entry.get("best_passed", 0)
    total = entry.get("best_runnable_total", 0)
    left = total - passed
    locked = entry.get("locked_archive", False)

    print(f"\n{'=' * 60}")
    print(f"  {entry.get('slug', slug)}")
    print(f"  Score: {score:.2f}% ({passed}/{total}, {left} left)")
    print(f"  Locked: {locked}")
    if eval_path:
        print(f"  Eval: {eval_path}")
    print(f"{'=' * 60}\n")

    if locked:
        print("Already locked. Nothing to diagnose.")
        return

    if not eval_path:
        print("No eval.json found. Run an eval first.")
        return

    failures = get_failures(eval_path)
    if not failures:
        print("No failures found in eval.json (check status field).")
        return

    print(f"Found {len(failures)} failing test(s).\n")

    # Aggregate all traceback text for pattern matching
    all_text = ""
    for i, t in enumerate(failures[:20], 1):
        name = t.get("name", "unknown")
        extra = t.get("extra", {}) or {}
        text = (extra.get("text", "") or "").strip()
        all_text += " " + text

        print(f"[{i}] {name}")
        if full:
            print(text[:1500])
        else:
            # Show first 3 meaningful lines
            lines = [l for l in text.splitlines() if l.strip() and not l.startswith(" ")]
            for l in lines[:4]:
                print(f"    {l}")
        print()

    if len(failures) > 20:
        print(f"  ... {len(failures) - 20} more failures not shown.\n")

    # Pattern matching
    patterns = match_patterns(all_text)
    if patterns:
        print(f"\n{'-' * 60}")
        print("  PATTERN MATCHES")
        print(f"{'-' * 60}")
        for p in patterns[:4]:
            print(f"\n[{p['id']}] score={p['score']} — {p['description']}")
            print(f"  FIX: {p['fix']}")
    else:
        print("\nNo known patterns matched. Inspect tracebacks above manually.")

    # Check KB for similar tools
    kb = load_kb()
    if kb and patterns:
        top_pattern = patterns[0]["id"]
        print(f"\n  Tools with similar pattern ({top_pattern}):")
        examples = patterns[0].get("example_tools", [])
        for ex in examples:
            matching = [k for k in kb.get("tools", {}) if ex in k]
            for m in matching[:2]:
                sections = kb["tools"][m].get("sections", {})
                fix_note = sections.get("cluster_transfer_notes", "")[:200]
                if fix_note:
                    print(f"  [{m}]: {fix_note[:120]}")


def cmd_board(_args):
    board = load_board()
    unlocked = [
        e for e in board if not e.get("locked_archive") and e.get("best_runnable_total", 0) > 0
    ]
    unlocked.sort(key=lambda e: -e.get("best_score", 0))

    print(f"\n{'Score':>8} {'Passed':>8} {'Total':>8} {'Left':>6}  Slug")
    print("-" * 70)
    for e in unlocked[:30]:
        sc = e.get("best_score", 0)
        ps = e.get("best_passed", 0)
        rt = e.get("best_runnable_total", 0)
        left = rt - ps
        slug = e.get("slug", "")
        marker = " ◀ NEAR LOCK" if left <= 10 else ""
        print(f"{sc:>7.2f}% {ps:>8} {rt:>8} {left:>6}  {slug}{marker}")


def cmd_cluster(args):
    """Find all unlocked tools whose failures match a pattern."""
    pattern_id = args[0] if args else ""
    pat = PATTERN_SIGNATURES.get(pattern_id)
    if not pat:
        print(f"Unknown pattern: {pattern_id!r}")
        print("Available:", ", ".join(PATTERN_SIGNATURES.keys()))
        return

    board = load_board()
    unlocked = [e for e in board if not e.get("locked_archive") and e.get("best_eval_path")]

    print(f"\nScanning {len(unlocked)} unlocked tools for pattern: {pattern_id}\n")
    hits = []
    for e in unlocked:
        eval_path = e.get("best_eval_path") or e.get("eval_path")
        if not eval_path:
            continue
        failures = get_failures(eval_path)
        all_text = " ".join((f.get("extra", {}) or {}).get("text", "") or "" for f in failures)
        score = sum(1 for sig in pat["signals"] if sig.lower() in all_text.lower())
        if score > 0:
            hits.append((score, e.get("slug"), e.get("best_score", 0), len(failures)))

    hits.sort(key=lambda x: -x[0])
    print(f"{'Pattern Score':>14} {'PB Score':>10} {'Failures':>10}  Slug")
    print("-" * 65)
    for sig_score, slug, pb_score, n_fail in hits:
        print(f"{sig_score:>14} {pb_score:>9.2f}% {n_fail:>10}  {slug}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    rest = args[1:]

    if cmd == "board":
        cmd_board(rest)
    elif cmd == "cluster":
        cmd_cluster(rest)
    elif cmd == "triage":
        cmd_triage(rest)
    else:
        full = "--full" in rest
        cmd_diagnose(cmd, full=full)
