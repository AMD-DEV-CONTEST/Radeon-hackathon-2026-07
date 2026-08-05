#!/usr/bin/env python3
"""
silent_success_audit.py — every place a failure or an unknown becomes a success
==============================================================================
Static, read-only AST inventory of the one bug shape that keeps recurring in this codebase:
a layer that converts "we failed" or "we don't know" into "fine".

WHY THIS EXISTS
On 2026-08-02, six instances were found in a single day, in six different files, by hand:

  * `status_map.get(inner_res.status, "TAURI_COMMAND_OK")` — an unmapped status became OK
  * a second copy of that same table in `ide/_tauri_driver.py`, found only after the first
    was fixed, so the frontend's behaviour depended on which path it took
  * `determinex_backend_cli.py` printed a BLOCKED status and returned exit 0
  * `hive/workspace.verify_corpus_entry` returned True (signature valid) when the verifier
    could not be imported — the log said "skipped", the return value said "verified"
  * `public_authority_boundary_status` checked REQUIRED flags only when present, then
    reported `ab.get(flag, True)` — the no-overclaim surface overclaiming
  * `public_readiness_spine_dashboard_status` reported `ledger_chain_valid` as True and
    `mutation_detected` as False when the checkpoint said neither

They are one bug wearing six outfits, and grepping for the last one never finds the next.

CLASSIFICATION (closed set, mirroring parallel_execution_layer_audit.py)
  EXCEPT_RETURNS_SUCCESS   an error handler returns a truthy/pass-shaped value
  GET_DEFAULTS_TO_SUCCESS  a lookup falls back to a success-shaped literal
  DECLARED_FAIL_CLOSED     the same shape, but the truthy value means "unsafe / exclude /
                           do not proceed" — correct, and declared here with its reason
  UNKNOWN_REQUIRES_REVIEW  on a load-bearing surface, not declared        <- fails --strict

THE LITERAL IS NOT THE FINDING; WHAT THE LITERAL MEANS IS. `return True` from an except is
correct in `rag_guard.is_binary_file` (True = "binary, do not ingest") and in
`manifest._pid_alive` (True = "alive, do not recover the session"). Both are fail-CLOSED.
A scan that cannot tell those apart cries wolf and gets ignored, which is how the six real
ones survived. Hence DECLARED_FAIL_CLOSED: every exemption is listed with a reason, so the
exemption list is itself reviewable.

    python scripts/dev/silent_success_audit.py [--json OUT] [--md OUT] [--strict]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCAN_ROOT = _ROOT / "scripts"

_SKIP_PARTS = {"__pycache__", ".venv", "venv", "node_modules", "site-packages", "archive"}

#: Surfaces where a silent success reaches a user, an oracle verdict, or a security
#: decision. A candidate outside these still gets listed, but only these fail --strict.
_LOAD_BEARING = ("ide/", "oracle", "verif", "repair", "adjudicat", "hive/", "safety", "governance")

#: Words that make a string literal look like an assertion of success.
#:
#: Matched on WORD BOUNDARIES, not as substrings. The first version used `in`, so
#: "IDE_PATCH_PLAN_BLOCKED_SCHEMA_INVALID" matched because "INVALID" contains "VALID" -- the
#: scanner reported a fail-CLOSED default (its fallback is a BLOCKED token) as a silent
#: success. An audit that inverts the meaning of its own finding is worse than no audit;
#: this is the same class of error the audit hunts, committed by the audit.
_SUCCESS_TOKENS = ("OK", "PASS", "PASSED", "SUCCESS", "HEALTHY", "CLEAN", "VALID", "GRANTED")

#: Negating prefixes: a token preceded by one of these asserts the OPPOSITE.
_NEGATIONS = ("IN", "UN", "NON", "NOT_", "NO_", "BLOCKED", "FAILED", "DENIED")

#: (file, symbol, detail) -> reason. The truthy value here means "unsafe / stop", not "fine".
#: Reviewed 2026-08-02.
#:
#: Keyed by file + symbol + the DETAIL string rather than by line number, for two reasons:
#: line numbers move on every edit, and a (file, symbol) key alone would exempt every future
#: silent-success added anywhere inside that function -- an exemption is a claim about one
#: expression, not a permit for the whole body.
_DECLARED_FAIL_CLOSED: dict[tuple[str, str, str], str] = {
    ("hive/rag_guard.py", "is_binary_file", "except -> return True"):
        "True means 'binary, do NOT ingest' — an unreadable file is excluded, not accepted",
    ("hive/rag_guard.py", "is_oversized_file", "except -> return True"):
        "True means 'too large, do NOT ingest' — a stat failure excludes the file",
    ("hive/manifest.py", "_pid_alive", "except -> return True"):
        "True means 'process alive, do NOT recover this session' — uncertainty is treated "
        "as live so a running session is never stolen",
    ("ide/public_proof_report_export_status.py", "load", ".get(..., True)"):
        "a contract field with no explicit `required` is treated as REQUIRED — the stricter "
        "reading, so absence tightens the contract rather than loosening it",
}


def _asserts_success(text: str) -> bool:
    """Does this string literal claim success, allowing for negating prefixes?

    Split on non-alphanumerics so tokens are compared as WORDS: "BLOCKED_SCHEMA_INVALID"
    yields {BLOCKED, SCHEMA, INVALID} and matches nothing, where a substring test matched
    VALID inside INVALID and inverted the verdict.
    """
    upper = text.upper()
    words = [w for w in re.split(r"[^A-Z0-9]+", upper) if w]
    if any(w.startswith(_NEGATIONS) or w in _NEGATIONS for w in words):
        return False
    return any(w in _SUCCESS_TOKENS for w in words)


def _is_success_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant):
        if node.value is True:
            return "True"
        if isinstance(node.value, str) and _asserts_success(node.value):
            return repr(node.value)
    return None


def _returned_success(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Return) or node.value is None:
        return None
    lit = _is_success_literal(node.value)
    if lit:
        return lit
    if isinstance(node.value, ast.Call):
        for kw in node.value.keywords:
            if kw.arg in ("passed", "ok", "healthy", "valid", "success") and _is_success_literal(
                kw.value
            ):
                return f"{kw.arg}=True"
    return None


class _Scan(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: list[dict] = []
        self._fn: list[str] = []

    def _visit_fn(self, node) -> None:
        self._fn.append(node.name)
        self.generic_visit(node)
        self._fn.pop()

    visit_FunctionDef = _visit_fn
    visit_AsyncFunctionDef = _visit_fn

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        for stmt in ast.walk(node):
            got = _returned_success(stmt)
            if got:
                self.hits.append({
                    "kind": "EXCEPT_RETURNS_SUCCESS",
                    "line": getattr(stmt, "lineno", node.lineno),
                    "symbol": self._fn[-1] if self._fn else "<module>",
                    "detail": f"except -> return {got}",
                })
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get" and len(node.args) == 2:
            lit = _is_success_literal(node.args[1])
            if lit:
                self.hits.append({
                    "kind": "GET_DEFAULTS_TO_SUCCESS",
                    "line": node.lineno,
                    "symbol": self._fn[-1] if self._fn else "<module>",
                    "detail": f".get(..., {lit})",
                })
        self.generic_visit(node)


def audit() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(_SCAN_ROOT.rglob("*.py")):
        if set(path.parts) & _SKIP_PARTS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
        except SyntaxError:
            continue
        scan = _Scan()
        scan.visit(tree)
        rel = str(path.relative_to(_ROOT)).replace("\\", "/")
        short = rel[len("scripts/"):] if rel.startswith("scripts/") else rel
        for hit in scan.hits:
            declared = _DECLARED_FAIL_CLOSED.get((short, hit["symbol"], hit["detail"]))
            hit["file"] = rel
            hit["load_bearing"] = any(s in rel for s in _LOAD_BEARING)
            if declared:
                hit["kind"] = "DECLARED_FAIL_CLOSED"
                hit["reason"] = declared
            elif hit["load_bearing"]:
                hit["kind"] = "UNKNOWN_REQUIRES_REVIEW"
            rows.append(hit)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--json", default=None)
    ap.add_argument("--md", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any UNKNOWN_REQUIRES_REVIEW remains")
    args = ap.parse_args()

    rows = audit()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1

    print(f"Silent Success Audit - {len(rows)} sites")
    for k in sorted(counts):
        print(f"  {k:<28} {counts[k]}")

    unknown = [r for r in rows if r["kind"] == "UNKNOWN_REQUIRES_REVIEW"]
    if unknown:
        print("\nUNKNOWN_REQUIRES_REVIEW (load-bearing, undeclared):")
        for r in unknown:
            print(f"  {r['file']}:{r['line']}  {r['symbol']}  {r['detail']}")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nWrote JSON: {args.json}")
    if args.md:
        lines = ["# Silent Success Audit", "",
                 "> Generated by `scripts/dev/silent_success_audit.py`.", "",
                 "| Classification | Count |", "| --- | --- |"]
        lines += [f"| {k} | {counts[k]} |" for k in sorted(counts)]
        lines += ["", "## UNKNOWN_REQUIRES_REVIEW", ""]
        lines += ([f"- `{r['file']}:{r['line']}` `{r['symbol']}` — {r['detail']}"
                   for r in unknown] or ["_None._"])
        lines += ["", "## Declared fail-closed", ""]
        for (f, sym, detail), why in sorted(_DECLARED_FAIL_CLOSED.items()):
            lines.append(f"- `{f}` `{sym}` `{detail}` — {why}")
        Path(args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote Markdown: {args.md}")

    return 1 if (args.strict and unknown) else 0


if __name__ == "__main__":
    sys.exit(main())
