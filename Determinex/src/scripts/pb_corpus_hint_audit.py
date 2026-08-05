#!/usr/bin/env python3
"""Map ProgramBench failures to reusable corpus lessons.

This is a read-only drain tool. It takes current failure JSONs, gate results,
eval JSONs, or raw logs, detects known cross-tool failure patterns, checks the
candidate/override source for the expected hook, and writes a short report.

Examples:
  python scripts/pb_corpus_hint_audit.py --all-current
  python scripts/pb_corpus_hint_audit.py --slug kyoh86__richgo.313114f \
      --input logs/programbench_factory/richgo_failures_current.json
  python scripts/pb_corpus_hint_audit.py --slug doxygen__doxygen.966d98e \
      --input logs/programbench_factory/hetzner_foo/doxygen__doxygen_966d98e.err.log
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "logs" / "programbench_factory"
PB_STAGING_ROOT = Path(os.environ.get("DETERMINEX_PB_STAGING_ROOT", "T:/determinex-staging"))
OUT_MD = FACTORY / "CORPUS_HINT_AUDIT.md"
OUT_JSON = FACTORY / "CORPUS_HINT_AUDIT.json"
REJECT_NOTES = ROOT / "corpus" / "programbench" / "training_corpus" / "reject_notes"


@dataclasses.dataclass(frozen=True)
class Pattern:
    key: str
    title: str
    lesson: str
    failure_rx: tuple[re.Pattern[str], ...]
    hook_rx: tuple[re.Pattern[str], ...]
    next_action: str
    severity: str = "medium"


def _rx(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns)


PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        key="wrong_binary_or_scaffold",
        title="wrong binary / bootstrap scaffold running",
        lesson="A fallback scaffold or stale bundled binary can look like many behavior failures; first prove the candidate is the real upstream binary.",
        failure_rx=_rx(
            r"bootstrap scaffold",
            r"unknown option: -(?:n|s|o)\b",
            r"unknown option: --(?:output|background|fill-color|font-family)",
            r"Usage: [A-Za-z0-9_.+-]+ \[OPTIONS\] \[ARGS\]",
        ),
        hook_rx=_rx(
            r"bootstrap scaffold",
            r"using bundled binary",
            r"build failed",
            r"fallback",
            r"pre-built one",
            r"canonical upstream",
        ),
        next_action="Replace the fallback scaffold/stale binary with a real upstream build or known-good native binary before tuning output details.",
        severity="high",
    ),
    Pattern(
        key="harness_test_suppression",
        title="candidate suppresses or rewrites harness test collection",
        lesson="Injected pytest collection filters can turn timeouts into missing-test failures; use runner resource controls instead of hiding tests.",
        failure_rx=_rx(
            r"expected tests missing from JUnit XML",
            r"test\(s\) in JUnit XML not in tests\.json",
            r"missing from JUnit",
        ),
        hook_rx=_rx(
            r"collect_ignore_glob",
            r"pytest_collection_modifyitems",
            r"del items\[\d+:\]",
            r"pytest\.ini",
        ),
        next_action="Remove candidate-side test suppression/truncation and solve resource issues through the guarded runner.",
        severity="high",
    ),
    Pattern(
        key="argv0_preservation",
        title="argv[0] / executable path preservation",
        lesson="Help/version/error goldens often assert ./executable or /workspace/executable, not the real installed binary path.",
        failure_rx=_rx(
            r"/usr/local/bin/[A-Za-z0-9_.+-]+",
            r"/workspace/executable",
            r"\./executable",
            r"argv\[0\]",
            r"program name",
        ),
        hook_rx=_rx(
            r"\bexec\s+-a\s+\"\$0\"", r"\bexec\s+-a\s+\$0", r"argv\[0\]", r"sys\.argv\[0\]"
        ),
        next_action="Preserve the harness-visible program name in the wrapper before the native binary runs.",
        severity="high",
    ),
    Pattern(
        key="stderr_stdout_normalization",
        title="stdout/stderr normalization",
        lesson="Many near-locks fail on noisy progress, warnings, or one extra newline rather than behavior.",
        failure_rx=_rx(
            r"stderr\s*==\s*['\"]['\"]",
            r"stdout",
            r"warning:",
            r"Progress:",
            r"No files to be processed",
            r"ignoring unknown",
            r"Strings contain only whitespace",
            r"Full diff:",
        ),
        hook_rx=_rx(
            r"mktemp",
            r"sed\b",
            r"stderr",
            r"stdout",
            r"filter",
            r"replace\(",
            r"Progress:",
            r"No files to be processed",
        ),
        next_action="Capture output, normalize only the known noisy lines/bytes, and avoid broad filtering that can regress passing cases.",
        severity="high",
    ),
    Pattern(
        key="fixed_time_date",
        title="fixed date/time/environment pinning",
        lesson="Git/history/report tools frequently need deterministic dates, authors, timezone, or SOURCE_DATE_EPOCH.",
        failure_rx=_rx(
            r"20\d\d-\d\d-\d\d",
            r"timestamp",
            r"date",
            r"TIMEZONE",
            r"SOURCE_DATE_EPOCH",
            r"GIT_AUTHOR_DATE",
            r"GIT_COMMITTER_DATE",
        ),
        hook_rx=_rx(
            r"SOURCE_DATE_EPOCH",
            r"GIT_AUTHOR_DATE",
            r"GIT_COMMITTER_DATE",
            r"TZ=",
            r"2026-04-13",
            r"FAKETIME",
        ),
        next_action="Pin the environment or postprocess date fields to the upstream-observed golden date; verify against the real binary first.",
        severity="high",
    ),
    Pattern(
        key="umask_file_modes",
        title="umask/file mode pinning",
        lesson="Copy/archive tools can miss dozens of tests if the cleanroom umask differs from golden file-mode assumptions.",
        failure_rx=_rx(
            r"umask", r"permission", r"mode", r"0o[0-7]{3,4}", r"0755", r"0775", r"executable bit"
        ),
        hook_rx=_rx(r"umask\s*\(", r"os\.umask", r"chmod", r"0o022", r"0o755"),
        next_action="Pin umask or chmod generated outputs at the narrow boundary that owns file creation.",
        severity="high",
    ),
    Pattern(
        key="bash_path_dependency",
        title="bash/path dependency under constrained PATH",
        lesson="Some tests deliberately remove bash/go/git from PATH and assert native panic/error text.",
        failure_rx=_rx(
            r"/usr/bin/env: .*bash.*No such file",
            r"bash.*No such file",
            r"executable file not found in \$PATH",
            r"command not found",
        ),
        hook_rx=_rx(r"#!/usr/bin/env bash", r"#!/bin/bash", r"\bbash\b", r"PATH=", r"exec: \"go\""),
        next_action="Avoid a bash wrapper for paths where tests intentionally remove bash; use /bin/sh or a compiled/native wrapper.",
        severity="high",
    ),
    Pattern(
        key="native_required",
        title="native semantics required",
        lesson="Native signals mean Python wrappers usually hit a ceiling: overflow, signals, mmap, file magic, invalid UTF-8, byte-level behavior.",
        failure_rx=_rx(
            r"SIGPIPE|SIGTERM|SIGINT",
            r"overflow|c_atoi|size_t|off_t",
            r"mmap|null byte|invalid utf-?8",
            r"file magic|endianness|byte[- ]level",
            r"panic:|goroutine \d+|thread 'main' panicked",
            r"timing|performance",
        ),
        hook_rx=_rx(
            r"cargo build", r"go build", r"gcc\b", r"g\+\+", r"make\b", r"cmake", r"/usr/local/bin"
        ),
        next_action="Route to native source or a compiled shim before more wrapper patching.",
        severity="high",
    ),
    Pattern(
        key="serializer_exactness",
        title="byte-exact serializer/parser behavior",
        lesson="Converters need exact attribute order, escaping, URL normalization, encoding, and newline behavior.",
        failure_rx=_rx(
            r"JSONDecodeError",
            r"yaml|toml|html|xml|url",
            r"escape",
            r"encoding",
            r"attribute",
            r"newline",
            r"mojibake",
        ),
        hook_rx=_rx(
            r"json",
            r"yaml",
            r"toml",
            r"html5lib|BeautifulSoup",
            r"urllib|urlparse",
            r"from_encoding",
            r"sort",
        ),
        next_action="Compare against the upstream binary for the exact serializer rule before adding local special cases.",
        severity="medium",
    ),
    Pattern(
        key="clap_error_format",
        title="clap-style error formatting",
        lesson="CLI goldens often assert exact error:, USAGE:, and help trailer formatting.",
        failure_rx=_rx(
            r"USAGE:",
            r"For more information try --help",
            r"error:",
            r"Found argument .* wasn't expected",
            r"unknown option|unrecognized option",
        ),
        hook_rx=_rx(r"USAGE:", r"For more information try --help", r"argparse", r"clap", r"error:"),
        next_action="Patch the error formatter, not every individual failing assertion.",
        severity="medium",
    ),
    Pattern(
        key="harness_plumbing",
        title="eval harness/image/executable plumbing",
        lesson="0/0, hash_executable_failed, symlink executables, or missing /workspace/executable are not behavioral failures.",
        failure_rx=_rx(
            r"0/0",
            r"hash_executable_failed",
            r"/workspace/executable",
            r"stashed-executable",
            r"symlink",
            r"task_cleanroom",
        ),
        hook_rx=_rx(r"submission\.tar\.gz", r"\bexecutable\b", r"ln -s", r"cp\b", r"chmod \+x"),
        next_action="Run image preflight and make compile.sh produce a real executable file, not a symlink.",
        severity="medium",
    ),
    Pattern(
        key="xdist_dependency",
        title="xdist/pytest-dependency limitation",
        lesson="Some skipped dependency tests are harness artifacts across xdist workers and should not drive behavior patches.",
        failure_rx=_rx(r"pytest-dependency", r"xdist", r"depends on", r"skipped"),
        hook_rx=_rx(r"pytest", r"xdist", r"dependency"),
        next_action="Mark as harness limitation unless it changes runnable/pass counts.",
        severity="low",
    ),
)


def _safe_read(path: Path, max_chars: int = 2_000_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[:max_chars]


def _load_json(path: Path) -> Any | None:
    text = _safe_read(path)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _slug_from_path(path: Path) -> str | None:
    text = str(path)
    m = re.search(r"([A-Za-z0-9_.-]+)__([A-Za-z0-9_.-]+)[._]([0-9a-f]{7,})", text)
    if m:
        return f"{m.group(1)}__{m.group(2)}.{m.group(3)}"
    name = path.name.lower()
    known = {
        "fasttext": "facebookresearch__fasttext.1142dc4",
        "richgo": "kyoh86__richgo.313114f",
        "keifu": "trasta298__keifu.3331426",
        "doxygen": "doxygen__doxygen.966d98e",
        "xcp": "tarka__xcp.5e5b448",
    }
    for needle, slug in known.items():
        if needle in name:
            return slug
    return None


def _failure_records_from_json(data: Any) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                records.append(
                    {
                        "name": str(item.get("name") or item.get("test_name") or ""),
                        "status": str(item.get("status") or ""),
                        "message": "\n".join(
                            str(item.get(k) or "")
                            for k in ("msg", "text", "message", "message_head")
                        ),
                    }
                )
        return records

    if not isinstance(data, dict):
        return records

    # ProgramBench eval JSON.
    for item in data.get("test_results") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        if status not in {"failure", "failed", "error"}:
            continue
        records.append(
            {
                "name": str(item.get("name") or ""),
                "status": status,
                "message": str((item.get("extra") or {}).get("message") or ""),
            }
        )

    # Gate result normalized summaries.
    cand = data.get("candidate") if isinstance(data.get("candidate"), dict) else {}
    for name, msg in (cand.get("fail_messages") or {}).items():
        records.append({"name": str(name), "status": "failure", "message": str(msg)})

    # Apply-gate command output can still contain the only visible failure.
    for cmd in data.get("commands") or []:
        if not isinstance(cmd, dict):
            continue
        tail = "\n".join(str(cmd.get(k) or "") for k in ("stdout_tail", "stderr_tail"))
        if tail.strip():
            records.append(
                {"name": str(cmd.get("step") or "command"), "status": "log", "message": tail}
            )

    return records


def _records_from_path(path: Path) -> list[dict[str, str]]:
    data = _load_json(path)
    if data is not None:
        recs = _failure_records_from_json(data)
        if recs:
            return recs
    text = _safe_read(path)
    return [{"name": path.name, "status": "log", "message": text}] if text.strip() else []


def _find_source_roots(slug: str | None, explicit: Iterable[Path]) -> list[Path]:
    roots: list[Path] = [p for p in explicit if p.exists()]
    if not slug:
        return roots
    candidates = [
        ROOT / "corpus" / "programbench" / "per_tool_overrides" / slug,
        ROOT / "logs" / "programbench_factory" / slug,
    ]
    for p in candidates:
        if p.exists():
            roots.append(p)
    stem = slug.replace("__", "_").replace(".", "_")
    for staging in (PB_STAGING_ROOT, ROOT / ".determinex_staging"):
        if not staging.exists():
            continue
        for p in sorted(staging.glob(f"pb_*{stem.split('_')[1] if '_' in stem else stem}*"))[-5:]:
            candidate = p / slug / "source"
            if candidate.exists():
                roots.append(candidate)
            elif p.exists():
                roots.append(p)
    seen: set[str] = set()
    out: list[Path] = []
    for p in roots:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _source_text(
    roots: list[Path], max_files: int = 80, max_chars: int = 500_000
) -> tuple[str, list[str]]:
    chunks: list[str] = []
    files: list[str] = []
    suffixes = {
        ".py",
        ".sh",
        ".bash",
        ".go",
        ".rs",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".js",
        ".ts",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        "",
    }
    for root in roots:
        if root.is_file():
            paths = [root]
        else:
            paths = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes]
        for path in paths:
            if len(files) >= max_files:
                break
            if any(
                part in {"target", "node_modules", ".git", "__pycache__"} for part in path.parts
            ):
                continue
            txt = _safe_read(path, max_chars=80_000)
            if not txt:
                continue
            files.append(str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path))
            chunks.append(f"\n### {path}\n{txt}")
            if sum(len(c) for c in chunks) >= max_chars:
                break
    return "\n".join(chunks)[:max_chars], files


def _match_patterns(records: list[dict[str, str]], source: str) -> list[dict[str, Any]]:
    corpus = "\n".join(f"{r.get('name', '')}\n{r.get('message', '')}" for r in records)
    matches: list[dict[str, Any]] = []
    for pattern in PATTERNS:
        failure_hits: list[str] = []
        for rx in pattern.failure_rx:
            for m in rx.finditer(corpus):
                hit = m.group(0).replace("\n", "\\n")
                if hit not in failure_hits:
                    failure_hits.append(hit[:180])
                if len(failure_hits) >= 8:
                    break
            if len(failure_hits) >= 8:
                break
        if not failure_hits:
            continue
        hook_hits: list[str] = []
        for rx in pattern.hook_rx:
            for m in rx.finditer(source):
                hit = m.group(0).replace("\n", "\\n")
                if hit not in hook_hits:
                    hook_hits.append(hit[:120])
                if len(hook_hits) >= 8:
                    break
            if len(hook_hits) >= 8:
                break
        if hook_hits:
            status = "present-check-specificity"
            if pattern.key in {
                "stderr_stdout_normalization",
                "fixed_time_date",
                "argv0_preservation",
            }:
                status = "present-but-failing"
        else:
            status = "missing"
        matches.append(
            {
                "key": pattern.key,
                "title": pattern.title,
                "severity": pattern.severity,
                "status": status,
                "failure_hits": failure_hits,
                "hook_hits": hook_hits,
                "lesson": pattern.lesson,
                "next_action": pattern.next_action,
            }
        )
    return matches


def _summarize_records(records: list[dict[str, str]]) -> dict[str, Any]:
    names = [r.get("name", "") for r in records if r.get("name")]
    statuses = Counter(r.get("status", "") for r in records)
    modules = Counter(n.rsplit(".", 1)[0] if "." in n else n for n in names)
    return {
        "record_count": len(records),
        "statuses": dict(statuses.most_common()),
        "top_modules": dict(modules.most_common(8)),
    }


def _write_reports(rows: list[dict[str, Any]], md_path: Path, json_path: Path) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# ProgramBench Corpus Hint Audit")
    lines.append("")
    lines.append(
        "Read-only audit. It maps current failures to known corpus lessons and checks whether the candidate source appears to contain the expected hook."
    )
    lines.append("")
    for row in rows:
        lines.append(f"## {row['slug']}")
        lines.append("")
        lines.append(f"- Inputs: {', '.join(f'`{p}`' for p in row['inputs'])}")
        lines.append(f"- Failure records: {row['summary']['record_count']}")
        if row["source_files"]:
            lines.append(f"- Source inspected: {len(row['source_files'])} files")
        else:
            lines.append("- Source inspected: none")
        if row["summary"].get("top_modules"):
            mods = ", ".join(f"`{k}` ({v})" for k, v in row["summary"]["top_modules"].items() if k)
            lines.append(f"- Top modules: {mods}")
        lines.append("")
        if not row["matches"]:
            lines.append(
                "No known corpus pattern matched. Next step: inspect raw failures and add a new pattern if this repeats."
            )
            lines.append("")
            continue
        lines.append("| Severity | Pattern | Status | Next action |")
        lines.append("|---|---|---|---|")
        for m in row["matches"]:
            lines.append(
                f"| {m['severity']} | {m['title']} | `{m['status']}` | {m['next_action']} |"
            )
        lines.append("")
        for m in row["matches"]:
            lines.append(f"### {m['title']}")
            lines.append("")
            lines.append(m["lesson"])
            lines.append("")
            lines.append(f"Status: `{m['status']}`")
            lines.append("")
            lines.append("Failure evidence:")
            for hit in m["failure_hits"][:5]:
                lines.append(f"- `{hit}`")
            if m["hook_hits"]:
                lines.append("")
                lines.append("Hook evidence in source:")
                for hit in m["hook_hits"][:5]:
                    lines.append(f"- `{hit}`")
            lines.append("")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _priority(matches: list[dict[str, Any]]) -> str:
    if not matches:
        return "low"
    if any(m["status"] == "missing" and m["severity"] == "high" for m in matches):
        return "high"
    if any(m["status"] == "present-but-failing" and m["severity"] == "high" for m in matches):
        return "high"
    if any(m["severity"] == "high" for m in matches):
        return "medium"
    return "low"


def _likely_cause(matches: list[dict[str, Any]]) -> str:
    if not matches:
        return "new behavior class or sparse failure evidence"
    for key in ("wrong_binary_or_scaffold", "harness_test_suppression"):
        for m in matches:
            if m["key"] == key:
                return f"known pattern needs specificity check: {m['key']}"
    missing = [m for m in matches if m["status"] == "missing"]
    broken = [m for m in matches if m["status"] == "present-but-failing"]
    if missing:
        return f"known pattern missing: {missing[0]['key']}"
    if broken:
        return f"known pattern present but broken: {broken[0]['key']}"
    return f"known pattern needs specificity check: {matches[0]['key']}"


def _next_action(matches: list[dict[str, Any]]) -> str:
    if not matches:
        return "write a new corpus pattern from raw failure evidence before requeue"
    for key in ("wrong_binary_or_scaffold", "harness_test_suppression"):
        for m in matches:
            if m["key"] == key:
                return str(m["next_action"])
    ordered = sorted(matches, key=lambda m: (m["severity"] != "high", m["status"] != "missing"))
    return str(ordered[0]["next_action"])


def _write_notes(rows: list[dict[str, Any]]) -> list[Path]:
    written: list[Path] = []
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for row in rows:
        slug = row["slug"]
        priority = _priority(row["matches"])
        cause = _likely_cause(row["matches"])
        action = _next_action(row["matches"])
        note = {
            "slug": slug,
            "captured_at": ts,
            "matched_patterns": [m["key"] for m in row["matches"]],
            "hook_status": {m["key"]: m["status"] for m in row["matches"]},
            "likely_cause": cause,
            "next_action": action,
            "requeue_priority": priority,
            "inputs": row["inputs"],
            "summary": row["summary"],
        }
        out_dir = REJECT_NOTES
        out_dir.mkdir(parents=True, exist_ok=True)
        jsonl = out_dir / f"{slug}.jsonl"
        with jsonl.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(note, ensure_ascii=False, sort_keys=True) + "\n")
        in_progress = ROOT / "corpus" / "programbench" / "in_progress" / slug
        in_progress.mkdir(parents=True, exist_ok=True)
        md = in_progress / f"hint_audit_{ts}.md"
        lines = [
            f"# Hint audit - {slug}",
            "",
            f"- Requeue priority: `{priority}`",
            f"- Likely cause: {cause}",
            f"- Next action: {action}",
            f"- Inputs: {', '.join(f'`{p}`' for p in row['inputs'])}",
            "",
            "## Matched patterns",
            "",
        ]
        if row["matches"]:
            for m in row["matches"]:
                lines.append(f"### {m['title']}")
                lines.append("")
                lines.append(f"- Key: `{m['key']}`")
                lines.append(f"- Severity: `{m['severity']}`")
                lines.append(f"- Hook status: `{m['status']}`")
                lines.append(f"- Lesson: {m['lesson']}")
                lines.append(f"- Next action: {m['next_action']}")
                if m["failure_hits"]:
                    lines.append("- Failure evidence:")
                    for hit in m["failure_hits"][:5]:
                        lines.append(f"  - `{hit}`")
                if m["hook_hits"]:
                    lines.append("- Hook evidence:")
                    for hit in m["hook_hits"][:5]:
                        lines.append(f"  - `{hit}`")
                lines.append("")
        else:
            lines.append(
                "No known pattern matched. Add a new pattern if this failure shape repeats."
            )
            lines.append("")
        md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        written.extend([jsonl, md])
    return written


def _default_inputs() -> list[Path]:
    names = [
        "fasttext_failures_current.json",
        "richgo_failures_current.json",
        "keifu_failures_current.json",
    ]
    paths = [FACTORY / name for name in names if (FACTORY / name).is_file()]
    for path in FACTORY.glob("*/apply_gate_result.json"):
        if any(s in str(path).lower() for s in ("doxygen", "xcp", "fasttext", "richgo", "keifu")):
            paths.append(path)
    return sorted(set(paths), key=lambda p: str(p))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="Tool slug. Inferred from input path when omitted.")
    ap.add_argument(
        "--input",
        action="append",
        type=Path,
        default=[],
        help="Failure/eval/gate/log file. Repeatable.",
    )
    ap.add_argument(
        "--eval",
        dest="input",
        action="append",
        type=Path,
        help="Alias for --input; usually candidate eval JSON.",
    )
    ap.add_argument(
        "--source-dir",
        action="append",
        type=Path,
        default=[],
        help="Extra source root to inspect. Repeatable.",
    )
    ap.add_argument(
        "--source",
        dest="source_dir",
        action="append",
        type=Path,
        help="Alias for --source-dir; candidate source or run root.",
    )
    ap.add_argument(
        "--all-current",
        action="store_true",
        help="Audit known *_failures_current.json files and recent gate results.",
    )
    ap.add_argument(
        "--write-note",
        action="store_true",
        help="Append reject-note JSONL and per-tool in_progress markdown.",
    )
    ap.add_argument("--out-md", type=Path, default=OUT_MD)
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = ap.parse_args(argv)

    inputs = list(args.input)
    if args.all_current or not inputs:
        inputs.extend(_default_inputs())
    inputs = [p for p in inputs if p.exists()]
    if not inputs:
        sys.stderr.write("no input files found\n")
        return 2

    grouped: dict[str, list[Path]] = {}
    for path in inputs:
        slug = args.slug or _slug_from_path(path) or "unknown"
        grouped.setdefault(slug, []).append(path)

    rows: list[dict[str, Any]] = []
    for slug, paths in sorted(grouped.items()):
        records: list[dict[str, str]] = []
        for path in paths:
            records.extend(_records_from_path(path))
        roots = _find_source_roots(slug if slug != "unknown" else None, args.source_dir)
        source, source_files = _source_text(roots)
        matches = _match_patterns(records, source)
        rows.append(
            {
                "slug": slug,
                "inputs": [str(p) for p in paths],
                "summary": _summarize_records(records),
                "source_roots": [str(p) for p in roots],
                "source_files": source_files,
                "matches": matches,
            }
        )

    _write_reports(rows, args.out_md, args.out_json)
    note_paths = _write_notes(rows) if args.write_note else []
    print(f"wrote {args.out_md}")
    print(f"wrote {args.out_json}")
    for path in note_paths:
        print(f"wrote {path}")
    for row in rows:
        counts = Counter(m["status"] for m in row["matches"])
        hook_summary = ", ".join(f"{m['key']}: {m['status']}" for m in row["matches"])
        print(f"{row['slug']}: {len(row['matches'])} patterns {dict(counts)}")
        print("HINT_AUDIT:")
        print(f"  slug: {row['slug']}")
        print(f"  matched_patterns: {[m['key'] for m in row['matches']]}")
        print(f"  hook_status: {{ {hook_summary} }}")
        print(f"  likely_cause: {_likely_cause(row['matches'])}")
        print(f"  next_action: {_next_action(row['matches'])}")
        print(f"  requeue_priority: {_priority(row['matches'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
