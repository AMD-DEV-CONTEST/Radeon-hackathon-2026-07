#!/usr/bin/env python3
"""Build ProgramBench reference-parity evidence artifacts.

The script is intentionally artifact-first: it parses a raw eval report,
classifies skipped tests from upstream test source, and writes a markdown
packet. It does not edit eval_index.json or publish counts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import tarfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BEST_INDEX = ROOT / "corpus" / "programbench" / "best_known_state.json"
EVAL_INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"
PB_TASKS = Path("T:/Dev/ProgramBench/src/programbench/data/tasks")
DEFAULT_OUT_ROOT = ROOT / "corpus" / "programbench" / "parity_artifacts"


@dataclass(frozen=True)
class SkipEvidence:
    test_id: str
    tier: str
    condition: str
    location: str


@dataclass(frozen=True)
class ArtifactResult:
    tool: str
    verdict: str
    artifact_path: Path
    skipped: int
    failed_errors: int
    not_run: int


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def resolve_path(raw: str | Path | None) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw))
    if path.is_absolute():
        return path
    return ROOT / path


def load_report(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    rows = data.get("test_results") or data.get("results") or []
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected test_results list")
    return [row for row in rows if isinstance(row, dict)]


def status_of(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "unknown").lower()
    if status == "failed":
        return "failure"
    return status


def test_key(row: dict[str, Any]) -> str:
    return f"{row.get('branch') or 'unknown'}/{row.get('name') or '?'}"


def report_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    return Counter(status_of(row) for row in rows)


def skipped_keys(path: Path) -> list[str]:
    rows = load_report(path)
    return sorted(test_key(row) for row in rows if status_of(row) == "skipped")


def diff_reference(candidate_report: Path, reference_report: Path) -> dict[str, Any]:
    candidate = set(skipped_keys(candidate_report))
    reference = set(skipped_keys(reference_report))
    verdict = "REFERENCE_PARITY_CONFIRMED" if candidate == reference else "INELIGIBLE"
    return {
        "verdict": verdict,
        "candidate_only_skips": sorted(candidate - reference),
        "reference_only_skips": sorted(reference - candidate),
        "shared_skips": sorted(candidate & reference),
    }


def iter_source_files(paths: Iterable[Path]) -> Iterable[tuple[str, str]]:
    for path in paths:
        if not path.exists():
            continue
        if path.is_dir():
            for child in path.rglob("*.py"):
                try:
                    yield rel(child), child.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
        elif path.name.endswith((".tar.gz", ".tgz")):
            try:
                with tarfile.open(path, "r:gz") as tf:
                    for member in tf.getmembers():
                        if not member.isfile() or not member.name.endswith(".py"):
                            continue
                        f = tf.extractfile(member)
                        if not f:
                            continue
                        yield (
                            f"{rel(path)}!{member.name}",
                            f.read().decode("utf-8", errors="replace"),
                        )
            except (tarfile.TarError, OSError):
                continue
        elif path.suffix == ".py":
            try:
                yield rel(path), path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue


def function_name(test_id: str) -> str:
    name = test_id.split("/", 1)[-1]
    # Strip parametrize suffix before splitting — split on "[" gave "True-True]" not the fn name
    if "[" in name:
        name = name[: name.index("[")]
    tail = name.split(".")[-1]
    if "::" in tail:
        tail = tail.split("::")[-1]
    return tail


def decorator_block(lines: list[str], def_index: int) -> tuple[int, list[str]]:
    start = def_index
    while start > 0:
        prev = lines[start - 1]
        stripped = prev.strip()
        if not stripped:
            start -= 1
            continue
        if stripped.startswith("@") or stripped.startswith((")", "(", "reason=", "condition=")):
            start -= 1
            continue
        break
    return start, lines[start:def_index]


def runtime_skip_evidence(test_id: str, row: dict[str, Any]) -> SkipEvidence | None:
    extra = row.get("extra") or {}
    text = "\n".join(str(extra.get(k) or "") for k in ("output", "message", "text"))
    # JUnit XML <skipped> element format
    match = re.search(
        r'<skipped[^>]*message="([^"]*)"[^>]*>([^<:]+\.py:\d+):?\s*([^<]*)</skipped>',
        text,
        re.IGNORECASE,
    )
    if match:
        message = match.group(1).strip()
        detail = match.group(3).strip()
        condition = detail or message or "runtime pytest skip"
        return SkipEvidence(test_id, "TIER B", condition, match.group(2).strip())
    # Pytest verbose SKIPPED[...] format
    match = re.search(r"SKIPPED\s*\[[^\]]+\].{0,200}", text, re.IGNORECASE)
    if match:
        return SkipEvidence(test_id, "TIER B", match.group(0).strip(), "raw_report_output")
    # Plain text format: /path/to/file.py:linenum: message  (extra.text from PB eval reports)
    msg = str(extra.get("message") or "").strip()
    raw_text = str(extra.get("text") or "").strip()
    loc_match = re.match(r"(/[^\s]+\.py:\d+):\s*(.*)", raw_text)
    if loc_match:
        location = loc_match.group(1)
        condition = loc_match.group(2).strip() or msg or "runtime pytest skip"
        return SkipEvidence(test_id, "TIER B", condition, location)
    if msg:
        return SkipEvidence(test_id, "TIER B", msg, "extra.message")
    return None


def classify_skip_from_source(
    test_id: str, source_paths: list[Path], row: dict[str, Any] | None = None
) -> SkipEvidence:
    func = function_name(test_id)
    def_pat = re.compile(rf"^\s*def\s+{re.escape(func)}\s*\(")
    for location, text in iter_source_files(source_paths):
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not def_pat.search(line):
                continue
            block_start, decorators = decorator_block(lines, i)
            joined = "\n".join(d.strip() for d in decorators)
            if "@pytest.mark.skipif" in joined or "@unittest.skipIf" in joined:
                return SkipEvidence(
                    test_id, "TIER B", joined or "skipif decorator", f"{location}:{block_start + 1}"
                )
            if "@pytest.mark.skip" in joined or "@unittest.skip" in joined:
                return SkipEvidence(
                    test_id, "TIER A", joined or "skip decorator", f"{location}:{block_start + 1}"
                )
            body = "\n".join(lines[i : min(len(lines), i + 40)])
            if "pytest.skip(" in body or "SkipTest" in body:
                return SkipEvidence(
                    test_id, "TIER B", "runtime skip inside test body", f"{location}:{i + 1}"
                )
            return SkipEvidence(
                test_id,
                "TIER B",
                "skipped in report; no skip decorator at test definition",
                f"{location}:{i + 1}",
            )
    if row:
        runtime = runtime_skip_evidence(test_id, row)
        if runtime:
            return runtime
    return SkipEvidence(
        test_id, "TIER B", "source location not found; reference run required", "NOT_FOUND"
    )


def render_artifact(
    tool: str,
    report_path: Path,
    report_hash: str,
    counts: Counter[str],
    evidence: list[SkipEvidence],
    verdict: str,
    upstream_commit: str,
    ineligible_reason: str | None = None,
) -> str:
    total = sum(counts.values())
    lines = [
        f"# ProgramBench Parity Evidence - {tool}",
        "",
        f"- generated_at: `{dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()}`",
        f"- raw_report: `{rel(report_path)}`",
        f"- raw_report_sha256: `{report_hash}`",
        f"- upstream_commit: `{upstream_commit}`",
        f"- verdict: `{verdict}`",
        f"- counts: passed `{counts['passed']}`, skipped `{counts['skipped']}`, failed/error `{counts['failure'] + counts['error']}`, not_run `{counts['not_run']}`, total `{total}`",
    ]
    if ineligible_reason:
        lines.append(f"- ineligible_reason: `{ineligible_reason}`")
    lines.extend(
        [
            "",
            "## Skip Census",
            "",
            "| test id | condition | file:line | tier |",
            "|---|---|---|---|",
        ]
    )
    if evidence:
        for item in evidence:
            condition = item.condition.replace("\n", "<br>").replace("|", "\\|")
            lines.append(f"| `{item.test_id}` | {condition} | `{item.location}` | {item.tier} |")
    else:
        lines.append("| none | none | none | none |")
    return "\n".join(lines) + "\n"


def build_artifact(
    tool: str,
    *,
    report_path: Path,
    source_paths: list[Path],
    out_root: Path = DEFAULT_OUT_ROOT,
    upstream_commit: str = "unknown",
) -> ArtifactResult:
    rows = load_report(report_path)
    counts = report_counts(rows)
    failed_errors = counts["failure"] + counts["error"]
    not_run = counts["not_run"]
    skipped = counts["skipped"]
    skip_rows = [row for row in rows if status_of(row) == "skipped"]
    evidence = [classify_skip_from_source(test_key(row), source_paths, row) for row in skip_rows]

    ineligible_reason = None
    if failed_errors or not_run:
        verdict = "INELIGIBLE"
        ineligible_reason = f"failed/error count: {failed_errors}; not_run count: {not_run}"
    elif not skipped:
        verdict = "INELIGIBLE"
        ineligible_reason = "report has no skipped tests; this is not a parity artifact"
    elif any(item.tier == "TIER B" for item in evidence):
        verdict = "TIER_B_NEEDS_REFERENCE_RUN"
    else:
        verdict = "TIER_A_COMPLETE"

    out_dir = out_root / tool
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = out_dir / "parity_evidence.md"
    artifact_path.write_text(
        render_artifact(
            tool,
            report_path,
            sha256(report_path),
            counts,
            evidence,
            verdict,
            upstream_commit,
            ineligible_reason,
        ),
        encoding="utf-8",
    )
    return ArtifactResult(tool, verdict, artifact_path, skipped, failed_errors, not_run)


def build_missing_report_artifact(
    tool: str,
    *,
    out_root: Path = DEFAULT_OUT_ROOT,
    missing_report: str = "unknown",
) -> ArtifactResult:
    out_dir = out_root / tool
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = out_dir / "parity_evidence.md"
    lines = [
        f"# ProgramBench Parity Evidence - {tool}",
        "",
        f"- generated_at: `{dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()}`",
        f"- raw_report: `{missing_report}`",
        "- raw_report_sha256: `MISSING`",
        "- upstream_commit: `unknown`",
        "- verdict: `INELIGIBLE`",
        "- counts: passed `0`, skipped `0`, failed/error `0`, not_run `0`, total `0`",
        "- ineligible_reason: `raw report missing`",
        "",
        "## Skip Census",
        "",
        "| test id | condition | file:line | tier |",
        "|---|---|---|---|",
        "| none | none | none | none |",
    ]
    artifact_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ArtifactResult(tool, "INELIGIBLE", artifact_path, 0, 0, 0)


def load_best_index(path: Path = BEST_INDEX) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_tool(tool: str, index: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tools = index.get("tools", {})
    if tool in tools:
        return tool, tools[tool]
    needle = tool.lower()
    matches: list[str] = []
    for slug, row in tools.items():
        candidates = [slug, *list(row.get("aliases") or []), slug.split(".")[0]]
        if "__" in slug:
            candidates.append(slug.split("__", 1)[1].split(".", 1)[0])
        if any(needle == c.lower() for c in candidates):
            matches.append(slug)
    if not matches:
        raise SystemExit(f"tool not found in {BEST_INDEX}: {tool}")
    matches.sort(key=lambda s: (len(s), s))
    return matches[0], tools[matches[0]]


def task_commit(tool: str) -> str:
    candidates = [tool]
    if "__" not in tool:
        for task in PB_TASKS.glob(f"*__{tool}.*"):
            candidates.append(task.name)
    for candidate in candidates:
        task = PB_TASKS / candidate / "task.yaml"
        if not task.exists():
            continue
        match = re.search(
            r"^commit:\s*(\S+)", task.read_text(encoding="utf-8", errors="replace"), re.MULTILINE
        )
        if match:
            return match.group(1)
    return "unknown"


def source_paths_from_row(tool: str, row: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for key in ("best_tarball", "best_overrides"):
        path = resolve_path(row.get(key))
        if path:
            paths.append(path)
    locked_source = ROOT / "corpus" / "programbench" / "locked" / tool / "source"
    if locked_source.exists():
        paths.append(locked_source)
    return paths


def command_build(args: argparse.Namespace) -> int:
    index = load_best_index(Path(args.index))
    tool, row = resolve_tool(args.tool, index)
    report = resolve_path(args.report) if args.report else resolve_path(row.get("best_report"))
    if not report or not report.exists():
        result = build_missing_report_artifact(
            tool,
            out_root=Path(args.out_root),
            missing_report=str(report or row.get("best_report") or "None"),
        )
        print(f"{tool}: {result.verdict} skipped=0 artifact={result.artifact_path}")
        return 2
    sources = (
        [resolve_path(p) for p in args.source] if args.source else source_paths_from_row(tool, row)
    )
    source_paths = [p for p in sources if p]
    result = build_artifact(
        tool,
        report_path=report,
        source_paths=source_paths,
        out_root=Path(args.out_root),
        upstream_commit=args.commit or task_commit(tool),
    )
    print(f"{tool}: {result.verdict} skipped={result.skipped} artifact={result.artifact_path}")
    return 0 if result.verdict != "INELIGIBLE" else 2


def command_diff(args: argparse.Namespace) -> int:
    diff = diff_reference(Path(args.candidate_report), Path(args.reference_report))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(diff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{diff['verdict']}: {out}")
    return 0 if diff["verdict"] == "REFERENCE_PARITY_CONFIRMED" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    build = sub.add_parser("build")
    build.add_argument("tool")
    build.add_argument("--index", default=str(BEST_INDEX))
    build.add_argument("--report")
    build.add_argument("--source", action="append", default=[])
    build.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    build.add_argument("--commit")
    build.set_defaults(func=command_build)

    diff = sub.add_parser("diff")
    diff.add_argument("candidate_report")
    diff.add_argument("reference_report")
    diff.add_argument("--out", required=True)
    diff.set_defaults(func=command_diff)

    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        args = parser.parse_args(["build", *(argv or [])])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
