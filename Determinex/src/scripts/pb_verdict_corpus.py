#!/usr/bin/env python3
"""ProgramBench verdict corpus ingest — compiler-verified labeled training data.

For every gate result (Rule A or Rule B), walks the candidate eval JSON and
emits one ShareGPT-format row per test into
`corpus/programbench/training_corpus/pb_verdict_corpus.jsonl`.

Each row pairs:
  - the test it was evaluated against (test_name + module + failure message
    when present)
  - the override implementation that produced the verdict. Python tools store
    `main.py`; native tools store `main.go`, `src/main.rs`, or `main.c` rather
    than the Python exec wrapper.
  - the compiler oracle verdict ("pass" / "fail")
  - which decision_rule admitted the candidate ("A" or "B"), purely for
    weighting/filtering by the trainer

The score ledger is untouched. The training corpus eats both Rule A and
Rule B verdicts because the compiler oracle's pass/fail is ground truth
regardless of which surface it was measured on.

Idempotency: a SHA-256 hash of (slug, candidate_eval_path, test_name,
decision_rule) is stored on every row as `metadata.row_hash`. Re-running
the ingest against the same gate result is a no-op. The seen-set is
maintained at `.pb_verdict_corpus_seen.txt` (one hash per line) so the
check is O(1) per row.

Non-fatal contract: callers (notably `pb_apply_gate_decision.py`) wrap
ingest in try/except. A corpus write failure must NOT abort the gate
decision chain.

Usage (CLI):
    python scripts/pb_verdict_corpus.py <gate_result.json>
        [--corpus <path>]
        [--limit N]   # process only first N tests (for smoke tests)
        [--dry-run]

Usage (programmatic, called from apply_gate_decision):
    from pb_verdict_corpus import ingest_gate_result
    written = ingest_gate_result(Path(gate_path))
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "corpus" / "programbench" / "training_corpus" / "pb_verdict_corpus.jsonl"
DEFAULT_SEEN = DEFAULT_CORPUS.parent / ".pb_verdict_corpus_seen.txt"
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"

# Truncation budgets — keep rows in the few-KB range. The trainer can lift
# the cap if needed; this just prevents single rows from blowing up the file.
_MAX_OVERRIDE_BYTES = 12_000
_MAX_FAIL_MESSAGE_BYTES = 1_500

_SYSTEM_PROMPT = (
    "You are a Determinex agent implementing CLI tools to pass byte-exact "
    "behavioral tests. When given a test specification, you produce the "
    "language-correct implementation that the test will pass against the "
    "upstream binary."
)

_LANG_BY_EXT = {
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".toml": "toml",
    ".mod": "go",
    ".sh": "bash",
}


def _row_hash(slug: str, eval_path: str, test_name: str, decision_rule: str | None) -> str:
    h = hashlib.sha256()
    h.update(slug.encode("utf-8", "ignore"))
    h.update(b"\x00")
    h.update(eval_path.encode("utf-8", "ignore"))
    h.update(b"\x00")
    h.update(test_name.encode("utf-8", "ignore"))
    h.update(b"\x00")
    h.update((decision_rule or "").encode("utf-8", "ignore"))
    return h.hexdigest()


def _load_seen(seen_path: Path) -> set[str]:
    if not seen_path.is_file():
        return set()
    try:
        return {
            line.strip()
            for line in seen_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        }
    except OSError:
        return set()


def _read_text_truncated(path: Path) -> str:
    try:
        b = path.read_bytes()[:_MAX_OVERRIDE_BYTES]
        return b.decode("utf-8", "replace")
    except OSError:
        return ""


def _source_language_for_path(path: str) -> str:
    p = Path(path)
    if path == "go.mod":
        return "go"
    if p.name == "Cargo.toml":
        return "rust"
    return _LANG_BY_EXT.get(p.suffix.lower(), "text")


def _pick_implementation_files(override_dir: Path) -> list[tuple[str, Path]]:
    """Return source files that represent the implementation, not wrappers."""
    native_sets = [
        [("go.mod", override_dir / "go.mod"), ("main.go", override_dir / "main.go")],
        [
            ("Cargo.toml", override_dir / "Cargo.toml"),
            ("src/main.rs", override_dir / "src" / "main.rs"),
        ],
        [("main.c", override_dir / "main.c")],
        [("main.cpp", override_dir / "main.cpp")],
        [("main.cc", override_dir / "main.cc")],
    ]
    for group in native_sets:
        existing = [(rel, path) for rel, path in group if path.is_file()]
        if any(
            rel in {"main.go", "src/main.rs", "main.c", "main.cpp", "main.cc"}
            for rel, _ in existing
        ):
            return existing
    if (override_dir / "main.py").is_file():
        return [("main.py", override_dir / "main.py")]
    # Last resort: capture likely small source files, excluding generated/binary
    # artifacts and Python bytecode.
    out: list[tuple[str, Path]] = []
    for p in sorted(override_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(override_dir).as_posix()
        if "__pycache__" in rel or rel.endswith((".pyc", ".tar.gz")):
            continue
        if p.suffix.lower() in {".py", ".go", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp"}:
            out.append((rel, p))
        if len(out) >= 4:
            break
    return out


def _read_override(slug: str) -> dict[str, Any]:
    """Return implementation + compile script contents for the slug override."""
    out: dict[str, Any] = {
        "compile_sh": "",
        "override_dir": "",
        "implementation_files": [],
        "implementation_language": "unknown",
    }
    candidates = []
    exact = OVERRIDES_DIR / slug
    if exact.is_dir():
        candidates.append(exact)
    else:
        # Tolerate missing .HASH suffix (callers sometimes strip it).
        base = slug.rsplit(".", 1)[0] if "." in slug else slug
        for d in OVERRIDES_DIR.iterdir():
            if d.is_dir() and (d.name == slug or d.name.startswith(base + ".")):
                candidates.append(d)
                break
    if not candidates:
        return out
    od = candidates[0]
    out["override_dir"] = str(od)
    compile_sh = od / "compile.sh"
    if compile_sh.is_file():
        out["compile_sh"] = _read_text_truncated(compile_sh)

    impl_files: list[dict[str, str]] = []
    for rel, p in _pick_implementation_files(od):
        impl_files.append(
            {
                "path": rel,
                "language": _source_language_for_path(rel),
                "content": _read_text_truncated(p),
            }
        )
    out["implementation_files"] = impl_files
    langs = [f["language"] for f in impl_files if f.get("language") not in {"toml", "bash", "text"}]
    if langs:
        out["implementation_language"] = (
            langs[-1]
            if "rust" in langs and "src/main.rs" in [f["path"] for f in impl_files]
            else langs[0]
        )
    return out


def _build_human_turn(slug: str, test_name: str, fail_message: str | None) -> str:
    """User-side prompt for a verdict row.

    Carries enough context for a trainer to learn from: which tool, which test,
    and (on failures) the compiler-oracle error so the model sees the negative
    feedback paired with the bad output.
    """
    lines = [
        f"Implement the upstream CLI tool {slug.rsplit('.', 1)[0]} so that the "
        f"ProgramBench test `{test_name}` passes against the candidate executable.",
    ]
    if fail_message:
        msg = fail_message[:_MAX_FAIL_MESSAGE_BYTES]
        lines.append("")
        lines.append("Previous attempt failed. Compiler oracle reported:")
        lines.append("```")
        lines.append(msg)
        lines.append("```")
        lines.append(
            "Adjust the implementation so that the next run passes this test "
            "without regressing any previously-passing test."
        )
    return "\n".join(lines)


def _build_gpt_turn(override: dict[str, Any]) -> str:
    """Assistant-side response: the override implementation that produced the verdict."""
    parts: list[str] = []
    if override.get("compile_sh"):
        parts.append("```bash")
        parts.append("# compile.sh")
        parts.append(override["compile_sh"].rstrip())
        parts.append("```")
    for impl in override.get("implementation_files") or []:
        path = impl.get("path") or "implementation"
        lang = impl.get("language") or "text"
        content = impl.get("content") or ""
        if not content:
            continue
        parts.append("")
        parts.append(f"```{lang}")
        parts.append(f"# {path}")
        parts.append(content.rstrip())
        parts.append("```")
    if not parts:
        parts.append("(override files not found at ingest time)")
    return "\n".join(parts)


def ingest_gate_result(
    gate_path: Path,
    corpus_path: Path = DEFAULT_CORPUS,
    seen_path: Path = DEFAULT_SEEN,
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Read a single gate_result.json and append verdict rows to the corpus.

    Returns a summary dict. Idempotent: rows already present (by row_hash)
    are skipped. Non-fatal: any IO failure is caught and reported in the
    summary, never raised.

    The caller (apply_gate_decision) is expected to log the summary and
    proceed regardless.
    """
    summary: dict[str, Any] = {
        "gate_result_path": str(gate_path),
        "corpus_path": str(corpus_path),
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows_emitted": 0,
        "rows_skipped_dup": 0,
        "rows_with_fixture_attached": 0,
        "rows_fail": 0,
        "rows_pass": 0,
        "errors": [],
    }
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        summary["errors"].append(f"read gate_result: {type(e).__name__}: {e}")
        return summary

    # We ingest EVERY gate run — accept OR reject. The compiler verdict on each
    # test is ground truth regardless of whether the score gate accepted the
    # candidate. Rejected runs typically have a few regressions paired with a
    # mountain of real passes; that asymmetry is signal the trainer needs.
    # The metadata.gate_decision field lets a downstream filter discriminate
    # if desired, but we never silently drop compiler-verified data.
    gate_decision = str(gate.get("decision", "")).lower()
    slug = gate.get("slug", "")
    decision_rule = gate.get("decision_rule")
    candidate = gate.get("candidate") or {}
    eval_path = candidate.get("eval_path") or ""
    if not slug or not eval_path:
        summary["errors"].append("gate_result missing slug or candidate.eval_path")
        return summary

    # Pull the full per-test results + fail messages from the candidate eval JSON.
    try:
        eval_doc = json.loads(Path(eval_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        summary["errors"].append(f"read candidate eval: {type(e).__name__}: {e}")
        return summary
    test_results = eval_doc.get("test_results") or []
    if not isinstance(test_results, list):
        summary["errors"].append("candidate eval test_results not a list")
        return summary

    override = _read_override(slug)
    if not override.get("override_dir"):
        summary["errors"].append(f"override dir not found for slug {slug}")
        # We still emit rows — the metadata captures the absence — but the gpt
        # turn will be a stub. This is intentional: even without the source,
        # the verdict + test_name is useful signal.

    seen = _load_seen(seen_path)
    gpt_turn = _build_gpt_turn(override)

    new_rows: list[dict[str, Any]] = []
    new_hashes: list[str] = []

    for idx, t in enumerate(test_results):
        if limit is not None and idx >= limit:
            break
        if not isinstance(t, dict):
            continue
        name = str(t.get("name", "") or "").strip()
        status = str(t.get("status", "") or "").strip().lower()
        if not name or status not in ("passed", "failure", "failed", "error"):
            continue
        verdict = "pass" if status == "passed" else "fail"
        rh = _row_hash(slug, eval_path, name, decision_rule)
        if rh in seen:
            summary["rows_skipped_dup"] += 1
            continue
        fail_msg = None
        if verdict == "fail":
            fail_msg = ((t.get("extra") or {}).get("message") or "")[
                :_MAX_FAIL_MESSAGE_BYTES
            ] or None
        row = {
            "conversations": [
                {"from": "system", "value": _SYSTEM_PROMPT},
                {"from": "human", "value": _build_human_turn(slug, name, fail_msg)},
                {"from": "gpt", "value": gpt_turn},
            ],
            "metadata": {
                "slug": slug,
                "module": name.rsplit(".", 1)[0] if "." in name else name,
                "test_id": name,
                "verdict": verdict,
                "decision_rule": decision_rule,
                "gate_decision": gate_decision,
                "eval_json": eval_path,
                "gate_result_path": str(gate_path),
                "override_dir": override.get("override_dir", ""),
                "implementation_language": override.get("implementation_language", "unknown"),
                "implementation_files": [
                    {"path": f.get("path"), "language": f.get("language")}
                    for f in (override.get("implementation_files") or [])
                ],
                "captured_at": summary["started"],
                "row_hash": rh,
            },
        }
        new_rows.append(row)
        new_hashes.append(rh)
        if verdict == "pass":
            summary["rows_pass"] += 1
        else:
            summary["rows_fail"] += 1

    summary["rows_emitted"] = len(new_rows)

    if dry_run or not new_rows:
        return summary

    try:
        corpus_path.parent.mkdir(parents=True, exist_ok=True)
        with corpus_path.open("a", encoding="utf-8") as fh:
            for row in new_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        with seen_path.open("a", encoding="utf-8") as fh:
            for rh in new_hashes:
                fh.write(rh + "\n")
    except OSError as e:
        # Non-fatal: surface the failure in the summary but don't raise.
        summary["errors"].append(f"corpus write failed: {type(e).__name__}: {e}")
        summary["rows_emitted"] = 0

    # Side-write to CorpusManager: HMAC-signed copies on T: drive.
    # This is non-fatal — the local pb_verdict_corpus.jsonl is authoritative for
    # the existing PB pipeline; T: is the signed archive for the training flywheel.
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).parent))
        from agents.base_agent import CorpusType
        from corpus.corpus_manager import get_manager
        from verified_task.bench_to_corpus_eligibility import complete_benchmark_payload

        _cm = get_manager()
        signed_records = []
        for row, _rh in zip(new_rows, new_hashes):
            meta = row.get("metadata", {})
            spec_text = next(
                (c["value"] for c in row.get("conversations", []) if c.get("from") == "human"),
                "",
            )[:4096]
            patch = next(
                (c["value"] for c in row.get("conversations", []) if c.get("from") == "gpt"),
                "",
            )[:12000]
            verdict = meta.get("verdict", "fail")
            lang = meta.get("implementation_language", "unknown")
            task_id = f"pb_{slug}_{meta.get('test_id', _rh[:12])}"
            payload = {
                "language": lang,
                "lang": lang,
                "spec_text": spec_text,
                "patch": patch,
                "compile_result": verdict,
                "compile_errors": [],
                "test_result": verdict,
                "test_errors": [],
                "failure_class": "none" if verdict == "pass" else "programbench_failure",
                "failure_type": "none" if verdict == "pass" else "programbench_failure",
                "validator": "programbench eval",
                "verifier_command": "programbench eval",
                "verifier_result": verdict,
                "source_benchmark": "programbench",
                "source_kind": "benchmark_verdict",
                "license_gate": "unknown",
                "license_provenance": "unknown",
                "safety_gate": "unknown",
                "supply_chain_gate": "unknown",
                "repair_outcome": verdict,
                "model_router": lang,
                "attempt": 1,
                "model_builder": lang,
                "row_hash": _rh,
                "trace_hash": _rh,
                "metadata": meta,
            }
            payload = complete_benchmark_payload(payload)
            signed_records.append(
                _cm._normalize_record(
                    corpus_type=CorpusType.CODE_VERDICT,
                    task_id=task_id,
                    input_hash=hashlib.sha256((spec_text + lang).encode()).hexdigest(),
                    output_hash=hashlib.sha256(patch.encode()).hexdigest(),
                    source_benchmark="programbench",
                    payload=payload,
                )
            )
        _cm._write_records(CorpusType.CODE_VERDICT, signed_records)
    except Exception as _e:
        # Non-fatal: CorpusManager may not be available on all runners
        summary.setdefault("corpus_manager_errors", []).append(str(_e))

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "gate_result", type=Path, help="path to a gate_result.json produced by pb_candidate_gate.py"
    )
    ap.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS,
        help="output verdict corpus (default: corpus/programbench/training_corpus/pb_verdict_corpus.jsonl)",
    )
    ap.add_argument(
        "--seen",
        type=Path,
        default=DEFAULT_SEEN,
        help="seen-hash index (default: alongside corpus)",
    )
    ap.add_argument(
        "--limit", type=int, default=None, help="process only first N tests (for smoke tests)"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="compute rows but do not write to corpus"
    )
    args = ap.parse_args()
    summary = ingest_gate_result(
        args.gate_result,
        corpus_path=args.corpus,
        seen_path=args.seen,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if not summary.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
