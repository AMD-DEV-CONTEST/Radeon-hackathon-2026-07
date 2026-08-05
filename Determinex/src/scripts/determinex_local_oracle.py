#!/usr/bin/env python3
"""Determinex local oracle -- the cheap pre-eval check.

Runs a reimplementation against the I/O examples extracted from the shipped
pytest suite (determinex_io_extractor), entirely locally: no Docker, no network, no
Hetzner round-trip. A fix is validated in milliseconds, so the expensive
ProgramBench Docker eval is spent only on a candidate that is already local-green
(or to measure the residual the local oracle can't see).

Its report is built to make the SYSTEM do the work and leave the LLM a small,
specific add-in: failures are grouped, each shows the exact command, expected vs
actual, and a focused diff + a one-line classification (rc / exact / contains).

PB-compliant: it never touches the eval, tests, goldens, or collection. It only
runs the candidate binary the operator is iterating.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from determinex_io_extractor import Example, extract_dir  # noqa: E402

_COMPILED_NATIVE_ROOTS: set[Path] = set()


def _drop_binary_placeholder(argv):
    argv = list(argv)
    if not argv:
        return argv
    head = str(argv[0]).replace("\\", "/")
    if head.rsplit("/", 1)[-1] == "executable":
        return argv[1:]
    return argv


def _shell_for_compile():
    candidates = []
    if os.name == "nt":
        candidates.extend(
            [
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\sh.exe",
                "sh",
                "bash",
            ]
        )
    else:
        candidates.extend(["sh", "bash", "/bin/sh"])
    for candidate in candidates:
        if "\\" in candidate or "/" in candidate:
            if Path(candidate).exists():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


def _prepare_command(reimpl: Path, timeout=60):
    """Return (cmd_prefix, workspace, error) for Python or native reimpls."""
    reimpl = reimpl.resolve()
    root = reimpl if reimpl.is_dir() else reimpl.parent
    compile_sh = root / "compile.sh"
    executable = root / "executable"

    if compile_sh.exists():
        from intake.hardened_runner import run as _hrun  # noqa: E402

        root_key = root.resolve()
        if root_key not in _COMPILED_NATIVE_ROOTS:
            shell = _shell_for_compile()
            if not shell:
                return [], root, "<compile error: no sh/bash available for compile.sh>"
            res = _hrun(
                [shell, str(compile_sh)],
                workspace=root,
                cwd=root,
                timeout=timeout,
                extra_env={"PYTHONIOENCODING": "utf-8"},
                output_limit=None,
            )
            if res.timed_out:
                return [], root, "<compile timeout>"
            if res.exit_code != 0 or res.blocked or res.tool_missing:
                reason = res.stderr or res.stdout or f"<runner error: {res.reason}>"
                return [], root, f"<compile failed: {reason.strip()[:400]}>"
            _COMPILED_NATIVE_ROOTS.add(root_key)
        if not executable.exists():
            return [], root, "<compile failed: executable was not produced>"
        return _executable_cmd(executable), root, ""

    if reimpl.is_file() and reimpl.suffix == ".py":
        return [sys.executable, str(reimpl)], reimpl.parent, ""

    if reimpl.is_file():
        return _executable_cmd(reimpl), reimpl.parent, ""

    return [], root, f"<candidate error: {reimpl} is not a reimpl file or directory>"


def _executable_cmd(path: Path):
    if os.name == "nt":
        try:
            if path.read_bytes().startswith(b"#!"):
                shell = _shell_for_compile()
                if shell:
                    return [shell, str(path)]
        except OSError:
            pass
    return [str(path)]


def _run_reimpl(reimpl: Path, ex: Example, timeout=10):
    argv = _drop_binary_placeholder(ex.argv)
    cmd_prefix, workspace, prepare_error = _prepare_command(reimpl)
    if prepare_error:
        return None, "", prepare_error
    cmd = [*cmd_prefix, *argv]
    # Run each example in a FRESH per-call subdir of the workspace, so file-arg inputs
    # (and any files the tool writes, e.g. a config) are ISOLATED -- a config/output staged
    # for one example must never pollute another (this caused find_config() to pick up a
    # stale tex-fmt.toml and wrap at the wrong width across all later examples).
    import uuid as _uuid

    rundir = Path(workspace) / f".citrun_{_uuid.uuid4().hex[:10]}"
    try:
        rundir.mkdir(parents=True, exist_ok=True)
    except OSError:
        rundir = Path(workspace)
    for _fn, _content in (getattr(ex, "files", None) or {}).items():
        try:
            fp = rundir / _fn
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(_content, encoding="utf-8")
        except OSError:
            pass
    # The candidate is model/operator-generated code. Per the security carve-out
    # it is NEVER run via raw subprocess: it goes through intake.hardened_runner
    # (workspace-bounded cwd, scrubbed env, network + Docker denied). Full output
    # is kept (output_limit=None) so exact-stdout comparison stays byte-faithful.
    from intake.hardened_runner import run as _hrun  # noqa: E402

    # ``None`` would let subprocess inherit this process' stdin through the
    # hardened runner. Under SSH/session runners that fd can stay open forever,
    # hanging stdin-reading tools on examples that have no input payload.
    stdin_payload = ex.stdin if ex.stdin is not None else ""
    try:
        res = _hrun(
            cmd,
            workspace=workspace,
            cwd=rundir,
            timeout=timeout,
            extra_env={**(ex.env or {}), "PYTHONIOENCODING": "utf-8"},
            stdin=stdin_payload,
            output_limit=None,
        )
    finally:
        if rundir != Path(workspace):
            shutil.rmtree(rundir, ignore_errors=True)
    if res.timed_out:
        return None, "", "<timeout>"
    if res.exit_code < 0 or res.blocked or res.tool_missing:
        return None, res.stdout, res.stderr or f"<runner error: {res.reason}>"
    return res.exit_code, res.stdout, res.stderr


def _check(ex: Example, rc, out, err):
    """Return (ok, reason, detail)."""
    # Undo the Windows text-mode \r\n translation so the local oracle matches
    # the Linux/Docker eval (these tools emit \n; CRLF is a Windows-runner only
    # artifact). Harmless for the rare tool that truly emits \r\n.
    out = out.replace("\r\n", "\n")
    err = err.replace("\r\n", "\n")
    if ex.expect_rc is not None and rc != ex.expect_rc:
        return (
            False,
            "rc",
            f"expected rc={ex.expect_rc}, got rc={rc}"
            + (f"  stderr={err.strip()[:80]!r}" if err.strip() else ""),
        )
    if getattr(ex, "expect_rc_nonzero", False) and rc == 0:
        return False, "rc_nonzero", "expected a nonzero (failure) rc, got rc=0"
    rc_in = getattr(ex, "expect_rc_in", None)
    if rc_in and rc not in rc_in:
        return False, "rc_in", f"expected rc in {rc_in}, got rc={rc}"
    if ex.expect_stdout is not None and out != ex.expect_stdout:
        diff = "\n".join(
            difflib.unified_diff(
                ex.expect_stdout.splitlines(),
                out.splitlines(),
                "expected",
                "actual",
                lineterm="",
                n=1,
            )
        )
        return False, "exact", diff[:600]
    # stderr is imperative context for error cases -- the reference-enriched oracle
    # carries the EXACT messages, so enforce them (a build must match byte-for-byte).
    es = getattr(ex, "expect_stderr", None)
    if es is not None and err != es:
        diff = "\n".join(
            difflib.unified_diff(
                es.splitlines(),
                err.splitlines(),
                "expected_stderr",
                "actual_stderr",
                lineterm="",
                n=1,
            )
        )
        return False, "stderr", diff[:600]
    for snip in ex.expect_in:
        hay = out + "\n" + err
        needle = snip
        if getattr(ex, "ci", False):  # test compared against .lower()/.casefold()
            hay, needle = hay.lower(), snip.lower()
        if needle not in hay:
            return (
                False,
                "contains",
                f"missing {snip!r}; got stdout={out.strip()[:80]!r} stderr={err.strip()[:80]!r}",
            )
    # OR-GROUPS (2026-07-16): `assert A in out or B in out` -- captured in expect_in_any as
    # a list of OR-groups, each an "at least one of these" alternative set. Wired here so a
    # captured OR-group is actually ENFORCED, not just recorded and silently ignored -- a
    # candidate satisfying none of a group's alternatives must fail, the same way it would
    # against the real reference test.
    for group in getattr(ex, "expect_in_any", None) or []:
        hay = out + "\n" + err
        needles = group
        if getattr(ex, "ci", False):
            hay = hay.lower()
            needles = [n.lower() for n in group]
        if not any(n in hay for n in needles):
            return (
                False,
                "contains_any",
                (
                    f"missing all of {group!r} (need at least one); "
                    f"got stdout={out.strip()[:80]!r} stderr={err.strip()[:80]!r}"
                ),
            )
    # NEGATIVE ASSERTIONS (2026-07-16): `assert "unexpected argument" not in output` -- the
    # semantic mirror of expect_in. Enforced the same way: a candidate whose output DOES
    # contain a forbidden snippet must fail, or expect_not_in would be captured correctly
    # and then silently ignored, same class of gap as the OR-groups above.
    for snip in getattr(ex, "expect_not_in", None) or []:
        hay = out + "\n" + err
        needle = snip
        if getattr(ex, "ci", False):
            hay, needle = hay.lower(), snip.lower()
        if needle in hay:
            return (
                False,
                "not_contains",
                (
                    f"forbidden snippet {snip!r} present; "
                    f"got stdout={out.strip()[:80]!r} stderr={err.strip()[:80]!r}"
                ),
            )
    return True, "", ""


def examples_from_spec(spec_path: Path):
    """Load a pre-harvested answer-key (pb_bulk_spec.py output) into Examples.

    The spec merges every branch's tests into one list, so this validates a
    reimpl against the FULL observed behavior in one ms pass -- no re-extraction.
    Returns (examples, n_tests, n_examples)."""
    data = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    fields = {f for f in Example.__dataclass_fields__}  # tolerate schema drift
    exs = []
    for d in data.get("examples", []):
        # If the spec was reference-enriched (pb_enrich_spec), the EXACT real output
        # is the authoritative target: byte-match the reference => guaranteed to satisfy
        # any assertion the grader makes. Prefer it over io_extractor's partial literal.
        if d.get("ref_stdout") is not None and not d.get("ref_unobserved"):
            d = {
                **d,
                "expect_stdout": d["ref_stdout"],
                "expect_stderr": d.get("ref_stderr"),
                "expect_rc": d.get("ref_rc", d.get("expect_rc")),
            }
        exs.append(Example(**{k: v for k, v in d.items() if k in fields}))
    return exs, data.get("n_tests_total", len(exs)), len(exs)


def run_oracle(
    reimpl: Path,
    test_dir: Path | None = None,
    only=None,
    show_fail=25,
    examples=None,
    n_tests=None,
    label=None,
):
    if examples is None:
        assert test_dir is not None, "run_oracle needs test_dir or examples"
        cov = extract_dir(test_dir)
        examples = cov.examples
        n_tests, n_examples, skipped = cov.n_tests, cov.n_examples, len(cov.skipped)
    else:
        n_tests = n_tests if n_tests is not None else len(examples)
        n_examples, skipped = len(examples), 0
    label = label or str(test_dir)
    if only:
        examples = [e for e in examples if only in e.test or only in e.source]
    passed = 0
    by_module_fail = defaultdict(list)
    reason_counts = Counter()
    for ex in examples:
        rc, out, err = _run_reimpl(reimpl, ex)
        ok, reason, detail = _check(ex, rc, out, err)
        if ok:
            passed += 1
        else:
            reason_counts[reason] += 1
            mod = ex.source.split(":")[0]
            by_module_fail[mod].append((ex, reason, detail))
    total = len(examples)
    print(f"\n{'=' * 72}")
    print(f"  LOCAL ORACLE  {reimpl.name}  vs  {label}")
    print(
        f"  {passed}/{total} local examples pass   "
        f"(coverage {n_examples}/{n_tests} tests, "
        f"{skipped} not extractable)"
    )
    print(f"  failure classes: {dict(reason_counts)}")
    print(f"{'=' * 72}")
    shown = 0
    for mod in sorted(by_module_fail, key=lambda m: -len(by_module_fail[m])):
        fails = by_module_fail[mod]
        print(f"\n  [{mod}]  {len(fails)} failing")
        for ex, reason, detail in fails:
            if shown >= show_fail:
                print(f"    ... (+{sum(len(v) for v in by_module_fail.values()) - shown} more)")
                return passed, total, reason_counts
            argv = " ".join(_drop_binary_placeholder(ex.argv)) if ex.argv else ""
            sd = f" <stdin={ex.stdin!r}>" if ex.stdin else ""
            print(f"    {reason.upper():9} {ex.test}")
            print(f"      $ executable {argv}{sd}")
            for line in detail.splitlines()[:6]:
                print(f"        {line}")
            shown += 1
    return passed, total, reason_counts


def main(argv=None):
    ap = argparse.ArgumentParser(description="Determinex local oracle (cheap pre-eval)")
    ap.add_argument("reimpl", type=Path, help="the reimplementation (.py/.go/.rs/binary)")
    ap.add_argument(
        "test_dir",
        type=Path,
        nargs="?",
        help="dir with shipped test_*.py + goldens (omit if --spec)",
    )
    ap.add_argument(
        "--spec",
        type=Path,
        help="pre-harvested answer key from pb_bulk_spec.py "
        "(corpus/programbench/specs/<slug>.json) -- validates against "
        "ALL branches' merged behavior in one pass",
    )
    ap.add_argument("--only", help="filter examples by test-name/source substring")
    ap.add_argument("--show-fail", type=int, default=25)
    a = ap.parse_args(argv)
    if a.spec:
        exs, n_tests, _ = examples_from_spec(a.spec)
        passed, total, _ = run_oracle(
            a.reimpl,
            only=a.only,
            show_fail=a.show_fail,
            examples=exs,
            n_tests=n_tests,
            label=a.spec.name,
        )
    else:
        if not a.test_dir:
            ap.error("provide test_dir or --spec")
        passed, total, _ = run_oracle(a.reimpl, a.test_dir, a.only, a.show_fail)
    # exit non-zero if any local example fails (useful as a gate)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
