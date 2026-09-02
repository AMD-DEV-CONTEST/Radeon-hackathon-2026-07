#!/usr/bin/env python3
"""programbench_argv_miner.py - per-tool extraction of:
  - value_flags: flags that take a following argument (mined from run("-X","v") patterns)
  - positional_shapes: ordered arg shapes
  - expected_strings: substrings the tests grep / wait_for / assert on stdout/stderr
  - expected_keypresses: keys sent via tmux/pexpect send_keys
  - expected_rc: returncode values tests assert (set; usually {0,1,2})
  - workspace_fixtures: file/dir/git-init operations to pre-stage (from conftest)
  - structured_output_keys: JSON/YAML keys tests parse out

Walks every test tarball in HF cache, extracts eval/tests/*.py, regex-mines
each file. Output written to logs/mass_run_v2/argv_miner.json.

This is the load-bearing piece: it lets each scaffold know EXACTLY what the
tests want without having to guess from family heuristics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tarfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "logs" / "mass_run_v2" / "argv_miner.json"
HF_CACHE = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
HF_SNAPSHOT = HF_CACHE / "datasets--programbench--ProgramBench-Tests" / "snapshots"


# ── extraction patterns ────────────────────────────────────────────────────
# Match run("-X", "value", "path")  or  run_command("-X", "value")
#   capturing the flag and the next positional string literal
RX_RUN_CALL = re.compile(
    r"(?:run|run_command|run_exe|self\.run|subprocess\.run|subprocess\.check_output|subprocess\.check_call)\s*\(\s*\[?\s*((?:[\"'][^\"']{1,200}[\"']\s*,?\s*){1,12})",
    re.DOTALL,
)
RX_STRING_LITERAL = re.compile(r"[\"']([^\"']{1,200})[\"']")
RX_WAIT_FOR = re.compile(r"(?:wait_for|expect|expect_exact)\s*\(\s*[\"']([^\"']{1,200})[\"']")
RX_SEND_KEYS = re.compile(r"send_keys\s*\(\s*[fr]?[\"']([^\"']{1,200})[\"']")
RX_ASSERT_IN_STDOUT = re.compile(
    r"assert\s+[\"']([^\"']{1,200})[\"']\s+in\s+(?:result\.stdout|result\.stderr|output|stdout|stderr|capture)",
)
RX_ASSERT_RC = re.compile(r"(?:returncode|exit_code|rc)\s*==\s*(\d+)")
RX_CHECK_EXIT = re.compile(r"check_exit\s*=\s*(\d+)")
RX_JSON_LOADS = re.compile(r"json\.loads\s*\(\s*(?:result\.stdout|stdout|output)\s*\)")
RX_JSON_GET = re.compile(r"\[[\"']([A-Za-z_][A-Za-z0-9_-]{0,40})[\"']\]")  # data["key"]
RX_GIT_INIT = re.compile(r"git[ _]init|\.git/?", re.I)
RX_MKFIFO = re.compile(r"mkfifo", re.I)
RX_TMP_PATH = re.compile(r"tmp_path|tmpdir|TemporaryDirectory")
RX_WORKSPACE_FILE = re.compile(
    r"(?:open|write_text|with open)\s*\(\s*(?:tmp_path\s*/\s*)?[\"']([\w./_-]+\.[a-z]{1,5})[\"']"
)
RX_FIXTURE_FILE = re.compile(r"(?:fixture|fixtures)/([\w./_-]+)")
RX_NETWORK_PORT = re.compile(
    r"(?:bind|listen|connect)\s*\(\s*\(?\s*[\"']?(?:127\.0\.0\.1|localhost|0\.0\.0\.0)[\"']?\s*,\s*(\d{2,5})"
)


# Flags we will NEVER auto-promote to value-flag even if heuristics say so.
# These are counter-style boolean flags whose "next token" is just a positional.
NEVER_VALUE_FLAGS = {
    "--",
    "-v",
    "-vv",
    "-vvv",
    "-vvvv",
    "-vvvvv",
    "-q",
    "-qq",
    "-qqq",
    "--verbose",
    "--quiet",
    "--silent",
    "-h",
    "--help",
    "-V",
    "--version",
    "--debug",
    "--no-color",
    "--color",
    "--pretty",
    "--compact",
    "--json",
    "-r",
    "--recursive",
    "-a",
    "--all",
    "-f",
    "--force",
    "-n",
    "--dry-run",
    "-y",
    "--yes",
    "-i",
    "--ignore-case",
    "--no-confirm",
    "--confirm",
    "--check",
    "--list",
    "-l",
    "--long",
    "-s",
    "--short",
}


# ── data class ─────────────────────────────────────────────────────────────
def _new_entry() -> dict[str, Any]:
    return {
        "value_flags": set(),  # flags that take a following arg
        "value_flag_counts": {},  # flag -> {"value": n, "standalone": n}
        "positional_shapes": [],  # ordered argv samples
        "expected_strings": set(),  # wait_for / assert ... in stdout
        "expected_keypresses": set(),
        "expected_rc": set(),
        "workspace_files": set(),  # files tests write/expect in workspace
        "fixture_paths": set(),
        "needs_git_init": False,
        "needs_mkfifo": False,
        "needs_tmp": False,
        "needs_network": False,
        "network_ports": set(),
        "uses_json_loads": False,
        "json_keys": set(),
        "test_files_scanned": 0,
        "branches_scanned": 0,
    }


def _to_sorted_list(s: Any) -> list:
    if isinstance(s, set):
        return sorted(str(x) for x in s)
    return s


def _serialize(entry: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in entry.items():
        if isinstance(v, set):
            out[k] = _to_sorted_list(v)
        else:
            out[k] = v
    return out


# ── mining ─────────────────────────────────────────────────────────────────
def mine_py(text: str, entry: dict[str, Any]) -> None:
    # value_flags: per-flag counts based on what immediately follows the flag
    # in the args list. We tokenize the args blob into items (split on commas
    # not inside parens/brackets) so that Python variable expressions like
    # `json_backend` are seen as distinct tokens even though they're not
    # string literals — that lets us count `-j json_backend` as value-use.
    counts = entry["value_flag_counts"]
    for m in RX_RUN_CALL.finditer(text):
        args_blob = m.group(1)
        # Split args_blob into top-level comma-separated tokens
        items, depth, buf = [], 0, ""
        for ch in args_blob:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if ch == "," and depth <= 0:
                items.append(buf.strip())
                buf = ""
            else:
                buf += ch
        if buf.strip():
            items.append(buf.strip())

        # Identify which items are flag string literals
        def _flag_of(item: str) -> str | None:
            m2 = re.match(r"^[fr]?[\"']([^\"']+)[\"']$", item)
            if not m2:
                return None
            v = m2.group(1)
            if v.startswith("-") and not v.startswith("---") and len(v) > 1:
                return v
            return None

        flag_toks: list[str | None] = [_flag_of(it) for it in items]
        literal_strs: list[str] = []
        for it in items:
            m2 = re.match(r"^[fr]?[\"']([^\"']+)[\"']$", it)
            if m2:
                literal_strs.append(m2.group(1))
        entry["positional_shapes"].append(literal_strs[:8])

        for i, tok in enumerate(flag_toks):
            if tok is None:
                continue
            if tok in NEVER_VALUE_FLAGS:
                continue
            # `-X=value` form is a strong value-flag signal
            if "=" in tok and len(tok) > 3:
                base = tok.split("=", 1)[0]
                if base not in NEVER_VALUE_FLAGS:
                    rec = counts.setdefault(base, {"value": 0, "standalone": 0})
                    rec["value"] += 2
                continue
            rec = counts.setdefault(tok, {"value": 0, "standalone": 0})
            # Look at next item in the args list (could be literal string OR
            # python variable expression). If it's a flag-shaped string lit,
            # this flag is standalone. Otherwise (any non-flag thing) it's value.
            if i + 1 < len(flag_toks):
                if flag_toks[i + 1] is None:
                    # next is non-flag — either a value literal or a variable
                    rec["value"] += 1
                else:
                    rec["standalone"] += 1
            else:
                # last item in the args list = standalone use (rc check, etc)
                rec["standalone"] += 1

    # wait_for / expect strings
    for m in RX_WAIT_FOR.finditer(text):
        s = m.group(1).strip()
        if s and len(s) < 200:
            entry["expected_strings"].add(s)

    # send_keys
    for m in RX_SEND_KEYS.finditer(text):
        s = m.group(1).strip()
        if s:
            entry["expected_keypresses"].add(s[:80])

    # assert "X" in stdout/stderr
    for m in RX_ASSERT_IN_STDOUT.finditer(text):
        s = m.group(1).strip()
        if s and len(s) < 200:
            entry["expected_strings"].add(s)

    # rc assertions
    for m in RX_ASSERT_RC.finditer(text):
        try:
            entry["expected_rc"].add(int(m.group(1)))
        except ValueError:
            pass
    for m in RX_CHECK_EXIT.finditer(text):
        try:
            entry["expected_rc"].add(int(m.group(1)))
        except ValueError:
            pass

    # json parse
    if RX_JSON_LOADS.search(text):
        entry["uses_json_loads"] = True
    for m in RX_JSON_GET.finditer(text):
        k = m.group(1)
        if 1 < len(k) < 40 and not k.isdigit():
            entry["json_keys"].add(k)

    # fixtures / files
    if RX_GIT_INIT.search(text):
        entry["needs_git_init"] = True
    if RX_MKFIFO.search(text):
        entry["needs_mkfifo"] = True
    if RX_TMP_PATH.search(text):
        entry["needs_tmp"] = True
    for m in RX_WORKSPACE_FILE.finditer(text):
        f = m.group(1)
        if "/" not in f or len(f.split("/")) < 4:
            entry["workspace_files"].add(f)
    for m in RX_FIXTURE_FILE.finditer(text):
        f = m.group(1)
        if len(f) < 80:
            entry["fixture_paths"].add(f)
    for m in RX_NETWORK_PORT.finditer(text):
        try:
            entry["network_ports"].add(int(m.group(1)))
            entry["needs_network"] = True
        except ValueError:
            pass


def mine_branch_tar(tar_path: Path, entry: dict[str, Any]) -> int:
    """Scan all eval/tests/*.py inside a branch tarball. Returns # py files."""
    n = 0
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            for member in tf.getmembers():
                name = member.name.lower()
                if not name.endswith(".py"):
                    continue
                if (
                    "eval/tests" not in name
                    and "eval\\tests" not in name
                    and not name.endswith("conftest.py")
                ):
                    continue
                try:
                    f = tf.extractfile(member)
                    if f is None:
                        continue
                    text = f.read().decode("utf-8", errors="replace")
                    mine_py(text, entry)
                    n += 1
                except Exception:
                    continue
    except Exception:
        pass
    return n


def mine_tool(snapshot_dir: Path, instance_id: str) -> dict[str, Any]:
    entry = _new_entry()
    tool_dir = snapshot_dir / instance_id / "tests"
    if not tool_dir.is_dir():
        return _serialize(entry)
    branches = sorted(tool_dir.glob("*.tar.gz"))
    for branch in branches:
        n = mine_branch_tar(branch, entry)
        if n:
            entry["test_files_scanned"] += n
            entry["branches_scanned"] += 1
    # Post-process value_flag_counts → value_flags set.
    # A flag is a value-flag iff value_count >= 2 AND value_count > standalone_count.
    for flag, c in entry["value_flag_counts"].items():
        if flag in NEVER_VALUE_FLAGS:
            continue
        if c["value"] >= 2 and c["value"] > c["standalone"]:
            entry["value_flags"].add(flag)
    return _serialize(entry)


def find_snapshot() -> Path | None:
    if not HF_SNAPSHOT.is_dir():
        return None
    snapshots = sorted(HF_SNAPSHOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return snapshots[0] if snapshots else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", help="just mine one instance")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    snap = find_snapshot()
    if snap is None:
        print(f"ERROR: HF cache not found at {HF_SNAPSHOT}")
        return 1
    print(f"snapshot: {snap}")

    insts = sorted(p.name for p in snap.iterdir() if p.is_dir() and "__" in p.name)
    if args.instance:
        insts = [i for i in insts if args.instance in i]
    print(f"tools to mine: {len(insts)}")

    results: dict[str, Any] = {}
    for i, inst in enumerate(insts, 1):
        entry = mine_tool(snap, inst)
        results[inst] = entry
        if i % 10 == 0 or i == len(insts):
            print(
                f"  [{i}/{len(insts)}] {inst}: "
                f"branches={entry['branches_scanned']} "
                f"vflags={len(entry['value_flags'])} "
                f"strings={len(entry['expected_strings'])} "
                f"keys={len(entry['expected_keypresses'])}"
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwritten: {args.out}")

    # Summary
    vflag_tools = sum(1 for r in results.values() if r["value_flags"])
    str_tools = sum(1 for r in results.values() if r["expected_strings"])
    key_tools = sum(1 for r in results.values() if r["expected_keypresses"])
    json_tools = sum(1 for r in results.values() if r["uses_json_loads"])
    net_tools = sum(1 for r in results.values() if r["needs_network"])
    git_tools = sum(1 for r in results.values() if r["needs_git_init"])
    print()
    print("=== summary ===")
    print(f"  tools with value-flag hints: {vflag_tools}")
    print(f"  tools with expected-string hints: {str_tools}")
    print(f"  tools with keypress hints (TUI): {key_tools}")
    print(f"  tools using json.loads (structured output): {json_tools}")
    print(f"  tools binding network ports: {net_tools}")
    print(f"  tools needing git init: {git_tools}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
