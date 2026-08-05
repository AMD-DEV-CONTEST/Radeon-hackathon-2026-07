#!/usr/bin/env python3
"""Build the ProgramBench best-known-state index.

The output is regenerated state, not campaign truth. It crawls known artifact
surfaces, ranks eval reports by (passed DESC, failed ASC, not_run ASC, recency),
and points each tool at its best known report/tarball/override state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.pb_eval_conveyor import load_eval_packet

ROOT = Path(__file__).resolve().parents[1]
EVAL_INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"
DEFAULT_OUT = ROOT / "corpus" / "programbench" / "best_known_state.json"


REPORT_NAMES = {"eval_report.json"}
REPORT_SUFFIXES = (".eval.json",)
TARBALL_SUFFIXES = (".tar.gz", ".tgz")
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
}


@dataclass(frozen=True)
class ToolRow:
    slug: str
    aliases: tuple[str, ...]
    eval_index_status: str | None
    eval_index_report: str | None


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def load_tools(index_path: Path | None = None) -> dict[str, ToolRow]:
    index_path = index_path or EVAL_INDEX
    data = json.loads(index_path.read_text(encoding="utf-8"))
    canonical: dict[str, dict[str, Any]] = {}
    aliases: dict[str, list[str]] = {}
    for entry in data:
        slug = entry.get("slug") or entry.get("tool")
        if not slug:
            continue
        target = entry.get("canonical_slug")
        if target:
            aliases.setdefault(str(target), []).append(str(slug))
            continue
        canonical[str(slug)] = entry
    rows: dict[str, ToolRow] = {}
    for slug, entry in canonical.items():
        rows[slug] = ToolRow(
            slug=slug,
            aliases=tuple(sorted(aliases.get(slug, []))),
            eval_index_status=entry.get("status"),
            eval_index_report=entry.get("eval_report_path"),
        )
    return rows


def iter_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
            base = Path(dirpath)
            for name in filenames:
                yield base / name


def iter_candidate_files(roots: Iterable[Path]) -> Iterable[Path]:
    """Yield only artifact paths relevant to the best-state index."""
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            resolved = root.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield root
            continue

        max_depth = 6 if str(root).lower().startswith("t:") else 9
        for dirpath, dirnames, filenames in os.walk(root):
            base = Path(dirpath)
            try:
                depth = len(base.relative_to(root).parts)
            except ValueError:
                depth = 0
            if depth >= max_depth:
                dirnames[:] = []
            pruned = []
            for dirname in dirnames:
                if dirname in SKIP_DIR_NAMES:
                    continue
                if dirname in {"source", "target", "tmp", "tmp_downloads"}:
                    continue
                if base.name == "per_tool_overrides":
                    child = base / dirname
                    resolved = child.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield child
                    continue
                if "per_tool_overrides" in base.parts:
                    continue
                pruned.append(dirname)
            dirnames[:] = pruned

            for name in filenames:
                lower = name.lower()
                path = base / name
                if (
                    lower.endswith(".eval.json")
                    or lower == "eval_report.json"
                    or lower.endswith(TARBALL_SUFFIXES)
                    or ("programbench_conveyor" in path.parts and lower.endswith(".md"))
                ):
                    resolved = path.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield path


def is_report(path: Path) -> bool:
    return path.name in REPORT_NAMES or path.name.endswith(REPORT_SUFFIXES)


def is_tarball(path: Path) -> bool:
    return path.name.endswith(TARBALL_SUFFIXES)


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def file_hash(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def mtime(path: Path) -> str | None:
    try:
        return (
            dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC)
            .replace(microsecond=0)
            .isoformat()
        )
    except OSError:
        return None


def slug_candidates(slug: str) -> tuple[str, ...]:
    base = slug.split(".")[0]
    pieces = [slug, base]
    if "__" in base:
        pieces.append(base.split("__", 1)[1])
    return tuple(dict.fromkeys(p for p in pieces if p))


def match_tool(path_text: str, report_slug: str | None, tools: dict[str, ToolRow]) -> str | None:
    normalized_path = path_text.lower().replace("\\", "/")
    path_segments = [s for s in re.split(r"[/\s]+", normalized_path) if s]
    report = (report_slug or "").lower()
    matches: list[tuple[int, str]] = []
    for slug, row in tools.items():
        candidates: list[tuple[str, bool]] = []
        for value in (slug, *row.aliases):
            parts = slug_candidates(value)
            for i, candidate in enumerate(parts):
                candidates.append((candidate.lower(), i == 0))
        best_len = 0
        for c, is_full_slug in candidates:
            if not c:
                continue
            if report and (report == c or report.startswith(c + ".") or c.startswith(report + ".")):
                best_len = max(best_len, len(c))
                continue
            for segment in path_segments:
                if segment == c or segment.startswith(c + "."):
                    best_len = max(best_len, len(c))
                elif is_full_slug and c in segment:
                    best_len = max(best_len, len(c))
        if best_len:
            matches.append((best_len, slug))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def report_state(path: Path, tools: dict[str, ToolRow]) -> tuple[str | None, dict[str, Any] | None]:
    try:
        packet = load_eval_packet(path)
    except Exception:
        return None, None
    tool = match_tool(rel(path), packet.slug, tools)
    if tool is None:
        return None, None
    failing_ids = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        for row in raw.get("test_results") or raw.get("results") or []:
            if isinstance(row, dict) and str(row.get("status", "")).lower() not in {
                "passed",
                "pass",
            }:
                name = row.get("name")
                if name:
                    failing_ids.append(str(name))
    except Exception:
        pass
    failed = packet.counts["failure"] + packet.counts["failed"]
    state = {
        "kind": "eval_report",
        "path": rel(path),
        "exists": path.exists(),
        "sha256": file_hash(path),
        "mtime": mtime(path),
        "report_slug": packet.slug,
        "passed": packet.counts["passed"],
        "failed": failed,
        "errors": packet.counts["error"],
        "skipped": packet.counts["skipped"],
        "not_run": packet.counts["not_run"],
        "total": packet.total,
        "delta_to_lock": failed
        + packet.counts["error"]
        + packet.counts["skipped"]
        + packet.counts["not_run"],
        "failing_test_ids": sorted(dict.fromkeys(failing_ids)),
        "verdict": packet.verdict,
        "failure_class": packet.failure_class,
        "pattern_signatures": list(packet.pattern_signatures),
    }
    return tool, state


def artifact_record(path: Path, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": rel(path),
        "exists": path.exists(),
        "sha256": file_hash(path),
        "mtime": mtime(path),
    }


def rank_key(state: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        int(state.get("passed") or 0),
        -int(state.get("failed") or 0) - int(state.get("errors") or 0),
        -int(state.get("not_run") or 0),
        str(state.get("mtime") or ""),
    )


def build_index(roots: list[Path], *, include_hashes: bool = True) -> dict[str, Any]:
    tools = load_tools()
    by_tool: dict[str, dict[str, Any]] = {
        slug: {
            "tool": slug,
            "aliases": list(row.aliases),
            "eval_index_status": row.eval_index_status,
            "states": [],
            "tarballs": [],
            "overrides": [],
            "conveyor_packets": [],
            "best_report": None,
            "best_tarball": None,
            "best_overrides": None,
            "passed": None,
            "total": None,
            "failed": None,
            "errors": None,
            "skipped": None,
            "not_run": None,
            "failing_test_ids": [],
            "delta_to_lock": None,
            "state_lineage": [],
        }
        for slug, row in tools.items()
    }

    discovered = {"reports": 0, "tarballs": 0, "overrides": 0, "conveyor_packets": 0}

    seed_paths = []
    for row in tools.values():
        if row.eval_index_report:
            seed_paths.append(Path(row.eval_index_report))

    for path in list(iter_candidate_files(roots)) + seed_paths:
        if not path.exists():
            continue
        path_text = rel(path)
        if is_report(path):
            tool, state = report_state(path, tools)
            if tool and state:
                if not include_hashes:
                    state["sha256"] = None
                by_tool[tool]["states"].append(state)
                discovered["reports"] += 1
        elif is_tarball(path):
            tool = match_tool(path_text, None, tools)
            if tool:
                rec = artifact_record(path, "tarball")
                if not include_hashes:
                    rec["sha256"] = None
                by_tool[tool]["tarballs"].append(rec)
                discovered["tarballs"] += 1
        elif "per_tool_overrides" in path_text.replace("\\", "/"):
            tool = match_tool(path_text, None, tools)
            if tool:
                override_root = nearest_override_root(path)
                rec = artifact_record(override_root, "override_dir")
                rec["sha256"] = None
                if rec not in by_tool[tool]["overrides"]:
                    by_tool[tool]["overrides"].append(rec)
                    discovered["overrides"] += 1
        elif (
            "programbench_conveyor" in path_text.replace("\\", "/") and path.suffix.lower() == ".md"
        ):
            text = path.read_text(encoding="utf-8", errors="replace")
            for tool in tools:
                if tool in text or any(alias in text for alias in tools[tool].aliases):
                    by_tool[tool]["conveyor_packets"].append(
                        artifact_record(path, "conveyor_packet")
                    )
                    discovered["conveyor_packets"] += 1

    for slug, row in by_tool.items():
        row["states"].sort(key=rank_key, reverse=True)
        row["tarballs"].sort(key=lambda r: str(r.get("mtime") or ""), reverse=True)
        row["overrides"].sort(key=lambda r: str(r.get("mtime") or ""), reverse=True)
        row["conveyor_packets"].sort(key=lambda r: str(r.get("mtime") or ""), reverse=True)
        if row["states"]:
            best = row["states"][0]
            row["best_report"] = best["path"]
            row["passed"] = best["passed"]
            row["total"] = best["total"]
            row["failed"] = best["failed"]
            row["errors"] = best["errors"]
            row["skipped"] = best["skipped"]
            row["not_run"] = best["not_run"]
            row["failing_test_ids"] = best["failing_test_ids"]
            row["delta_to_lock"] = best["delta_to_lock"]
            row["state_lineage"] = [
                {
                    "path": s["path"],
                    "passed": s["passed"],
                    "failed": s["failed"],
                    "errors": s["errors"],
                    "skipped": s["skipped"],
                    "not_run": s["not_run"],
                    "total": s["total"],
                    "delta_to_lock": s["delta_to_lock"],
                    "mtime": s["mtime"],
                    "verdict": s["verdict"],
                    "failure_class": s["failure_class"],
                }
                for s in row["states"][:20]
            ]
        if row["tarballs"]:
            row["best_tarball"] = row["tarballs"][0]["path"]
        if row["overrides"]:
            row["best_overrides"] = row["overrides"][0]["path"]

    ranked = sorted(
        (
            {
                "tool": slug,
                "eval_index_status": row.get("eval_index_status"),
                "delta_to_lock": row.get("delta_to_lock"),
                "passed": row.get("passed"),
                "total": row.get("total"),
                "best_report": row.get("best_report"),
            }
            for slug, row in by_tool.items()
            if row.get("delta_to_lock") not in (None, 0)
            and row.get("eval_index_status") != "strict_lock"
        ),
        key=lambda r: (int(r["delta_to_lock"]), -(int(r["passed"] or 0)), str(r["tool"])),
    )

    return {
        "schema_version": "determinex-pb-best-state-v1",
        "generated_at": utc_now(),
        "tool_count": len(by_tool),
        "expected_campaign_tool_count": 200,
        "tool_count_note": "eval_index non-alias canonical rows are indexed; mismatch is surfaced, not hidden",
        "roots_scanned": [str(p) for p in roots],
        "discovered": discovered,
        "top_10_smallest_delta": ranked[:10],
        "tools": by_tool,
    }


def nearest_override_root(path: Path) -> Path:
    parts = path.parts
    try:
        idx = parts.index("per_tool_overrides")
    except ValueError:
        return path
    if len(parts) > idx + 1:
        return Path(*parts[: idx + 2])
    return path


def default_roots() -> list[Path]:
    return [
        ROOT / "corpus" / "programbench",
        ROOT / "logs",
        ROOT / "assurance" / "evidence",
        ROOT / "docs" / "campaign",
        ROOT / "scratch",
    ]


def external_roots() -> list[Path]:
    roots: list[Path] = []
    for extra in (Path("T:/determinex-programbench"), Path("T:/determinex-staging")):
        if extra.exists():
            roots.append(extra)
    return roots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help="Additional/override scan root; may be repeated.",
    )
    parser.add_argument(
        "--include-external",
        action="store_true",
        help="Also scan T:/determinex-programbench and T:/determinex-staging if present.",
    )
    parser.add_argument(
        "--no-hashes", action="store_true", help="Skip file hashing for faster exploratory runs."
    )
    parser.add_argument("--print-top", type=int, default=10)
    args = parser.parse_args()

    roots = [Path(p) for p in args.roots] if args.roots else default_roots()
    if args.include_external:
        roots.extend(external_roots())
    index = build_index(roots, include_hashes=not args.no_hashes)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    for row in index["top_10_smallest_delta"][: args.print_top]:
        print(
            f"{row['tool']}: delta={row['delta_to_lock']} passed={row['passed']}/{row['total']} report={row['best_report']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
