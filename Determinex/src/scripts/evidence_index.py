#!/usr/bin/env python3
"""Generate and validate Determinex's evidence index.

The evidence index is the preview/release proof table. Every named lock or
drain result must point to a manifest, test counts, a reproduction command, and
plain-language claim boundaries.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "assurance" / "evidence" / "evidence_index.json"


@dataclass
class EvidenceEntry:
    evidence_id: str
    kind: str
    manifest_path: str
    test_count: int
    full_suite_count: int
    reproduction_command: str
    commit: str
    proves: str
    does_not_prove: str


def generate_index(root: Path = ROOT) -> dict[str, Any]:
    entries: list[EvidenceEntry] = []
    for path in _manifest_paths(root, "locks/sentinel"):
        data = _read_json(path)
        evidence_id = str(data.get("lock_id") or path.stem)
        entries.append(_lock_entry(root, path, data, evidence_id))
    for path in _manifest_paths(root, "locks/drain"):
        data = _read_json(path)
        evidence_id = str(data.get("artifact_id") or path.stem)
        entries.append(_drain_entry(root, path, data, evidence_id))

    payload = {
        "schema_version": "determinex-evidence-index-v1",
        "generated_from": [
            "locks/sentinel/*.json",
            "locks/drain/*.json",
        ],
        "entry_count": len(entries),
        "entries": [asdict(entry) for entry in entries],
    }
    errors = validate_index(payload, root=root)
    payload["validation_errors"] = errors
    return payload


def validate_index(index: dict[str, Any], *, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    entries = index.get("entries")
    if not isinstance(entries, list) or not entries:
        return ["entries_missing_or_empty"]

    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("entry_not_object")
            continue
        evidence_id = str(entry.get("evidence_id") or "")
        if not evidence_id:
            errors.append("missing_evidence_id")
        elif evidence_id in seen:
            errors.append(f"duplicate_evidence_id:{evidence_id}")
        seen.add(evidence_id)

        for field in (
            "kind",
            "manifest_path",
            "test_count",
            "full_suite_count",
            "reproduction_command",
            "commit",
            "proves",
            "does_not_prove",
        ):
            value = entry.get(field)
            if value is None or value == "":
                errors.append(f"{evidence_id}:missing_{field}")

        manifest = root / str(entry.get("manifest_path") or "")
        if not manifest.is_file():
            errors.append(f"{evidence_id}:manifest_not_found:{entry.get('manifest_path')}")
        if int(entry.get("test_count") or 0) <= 0:
            errors.append(f"{evidence_id}:test_count_not_positive")
        if int(entry.get("full_suite_count") or 0) <= 0:
            errors.append(f"{evidence_id}:full_suite_count_not_positive")

    expected = {p.stem for p in _manifest_paths(root, "locks/sentinel")} | {
        p.stem for p in _manifest_paths(root, "locks/drain")
    }
    indexed = {str(entry.get("evidence_id") or "") for entry in entries if isinstance(entry, dict)}
    missing = sorted(expected - indexed)
    for evidence_id in missing:
        errors.append(f"missing_manifest_entry:{evidence_id}")
    return errors


def _lock_entry(root: Path, path: Path, data: dict[str, Any], evidence_id: str) -> EvidenceEntry:
    test_modules = _test_modules(data)
    command = (
        f".\\.venv\\Scripts\\python.exe -m pytest {' '.join(test_modules)} -q --tb=short"
        if test_modules
        else ".\\.venv\\Scripts\\python.exe -m pytest tests -q --tb=short"
    )
    return EvidenceEntry(
        evidence_id=evidence_id,
        kind="sentinel_lock",
        manifest_path=_rel(root, path),
        test_count=_focused_test_count(data),
        full_suite_count=_full_suite_count(data),
        reproduction_command=command,
        commit=str(data.get("commit") or "unrecorded"),
        proves=str(data.get("purpose") or data.get("lock_id") or evidence_id),
        does_not_prove=_lock_boundary(evidence_id),
    )


def _drain_entry(root: Path, path: Path, data: dict[str, Any], evidence_id: str) -> EvidenceEntry:
    gate = str(data.get("gate_result") or "")
    command = (
        f".\\.venv\\Scripts\\python.exe scripts\\pb_candidate_gate.py {data.get('slug')} {data.get('run_root')} --baseline-eval <baseline> --skip-eval"
        if gate
        else ".\\.venv\\Scripts\\python.exe scripts\\pb_native_eval_queue.py --top 20"
    )
    candidate = data.get("candidate") or {}
    baseline = data.get("baseline") or {}
    test_count = int(
        candidate.get("runnable") or candidate.get("total") or baseline.get("runnable") or 1
    )
    return EvidenceEntry(
        evidence_id=evidence_id,
        kind="drain_result",
        manifest_path=_rel(root, path),
        test_count=test_count,
        full_suite_count=test_count,
        reproduction_command=command,
        commit=str(data.get("commit") or "unrecorded"),
        proves=f"{data.get('slug', evidence_id)} {data.get('decision', 'decision')} result: {data.get('reason', '')}",
        does_not_prove="Does not prove a tool lock unless decision is accept at the official gate; rejected runs are failure evidence.",
    )


def _test_modules(data: dict[str, Any]) -> list[str]:
    direct = data.get("test_modules")
    if isinstance(direct, list):
        return [str(x) for x in direct]
    for key in ("focused_tests", "coverage_tests", "related_tests"):
        section = data.get(key)
        if isinstance(section, dict):
            module = section.get("module")
            if module:
                return [str(module)]
            modules = section.get("modules")
            if isinstance(modules, list):
                return [str(x) for x in modules]
    return []


def _focused_test_count(data: dict[str, Any]) -> int:
    for key in ("focused_tests", "coverage_tests", "related_tests"):
        section = data.get(key)
        if isinstance(section, dict) and section.get("passed") is not None:
            return int(section["passed"])
    if data.get("passed") is not None:
        return int(data["passed"])
    if data.get("tests") is not None:
        return int(data["tests"])
    return 1


def _full_suite_count(data: dict[str, Any]) -> int:
    section = data.get("full_suite")
    if isinstance(section, dict):
        return int(section.get("passed") or section.get("tests") or 1)
    return _focused_test_count(data)


def _lock_boundary(evidence_id: str) -> str:
    _BOUNDARIES: dict[str, str] = {
        "ACTION_GOVERNOR_LOCK_001": "Does not prove the governor is wired into every agent controller. The lock proves the gate logic is correct; call-site coverage must be verified separately.",
        "WORKSPACE_ESCAPE_LOCK_001": "Symlink creation tests skip on Windows without Developer Mode. Junction escape coverage is OS-dependent. The path traversal and absolute path tests run everywhere.",
        "CI_LOCK_001": "Does not prove all test paths run in CI. Only the paths listed in test.yml trigger; the filter may miss novel file locations.",
        "CORPUS_MIGRATION_LOCK_001": "Does not prove v2/v3 migrations are correct (they are not yet written). Proves the registry rejects unknown versions and the v1 schema is stable.",
        "CLOAK_LOCK_001": "Does not prove zero leakage across all 10 languages — smoke tests cover Python only. Full multi-language privacy audit requires the B-Uncloaked clean rerun.",
        "HIVE_LOCK_001": "Does not prove end-to-end session correctness at scale. Tests cover DAG, WAL, and workspace isolation primitives. Full session tests require live compilers.",
        "ROSETTA_LOCK_001": "Smoke tests cover the pure-Python layer only (no PyTorch). Projection accuracy and semantic preservation tests require rosetta_v1.pt and GPU.",
        "OBSERVABILITY_LOCK_001": "Does not prove event consumers exist. Proves the emitter works correctly and is fail-silent. UI / tail tooling is a future surface.",
    }
    if evidence_id in _BOUNDARIES:
        return _BOUNDARIES[evidence_id]
    if "CORPUS" in evidence_id:
        return "Does not prove corpus balance, training effectiveness, or public benchmark dominance by itself."
    if "REPAIR_LOCK" in evidence_id or "ORACLE" in evidence_id:
        return "Does not prove broad real-world repair coverage beyond the locked acceptance tests."
    if "DISTILLATION" in evidence_id:
        return (
            "Does not prove a deployed specialist model beats baseline without a later eval card."
        )
    return "Does not prove claims outside the manifest's tested control surface."


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _manifest_paths(root: Path, rel_dir: str) -> list[Path]:
    tracked = _indexed_manifest_paths(root, rel_dir)
    if tracked:
        return tracked
    return sorted((root / rel_dir).glob("*.json"))


def _indexed_manifest_paths(root: Path, rel_dir: str) -> list[Path]:
    index = root / ".git" / "index"
    if not index.is_file():
        return []
    data = index.read_bytes()
    if len(data) < 12 or data[:4] != b"DIRC":
        return []
    version = int.from_bytes(data[4:8], "big")
    if version not in {2, 3}:
        return []
    count = int.from_bytes(data[8:12], "big")
    offset = 12
    prefix = f"{rel_dir.rstrip('/')}/"
    paths: list[Path] = []
    for _ in range(count):
        entry_start = offset
        if offset + 62 > len(data):
            return []
        flags = int.from_bytes(data[offset + 60 : offset + 62], "big")
        offset += 62
        if version >= 3 and flags & 0x4000:
            offset += 2
        name_length = flags & 0x0FFF
        if name_length < 0x0FFF:
            raw_name = data[offset : offset + name_length]
            offset += name_length
            if offset < len(data) and data[offset] == 0:
                offset += 1
        else:
            end = data.find(b"\0", offset)
            if end == -1:
                return []
            raw_name = data[offset:end]
            offset = end + 1
        while (offset - entry_start) % 8:
            offset += 1
        name = raw_name.decode("utf-8", errors="replace")
        if name.startswith(prefix) and name.endswith(".json"):
            paths.append(root / name)
    return sorted(paths)


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def generate_markdown(
    index: dict[str, Any],
    root: Path = ROOT,
    markdown_path: Path | None = None,
) -> str:
    """Generate docs/EVIDENCE_INDEX.md — the human-readable proof table."""
    lines: list[str] = [
        "# Determinex Evidence Index",
        "",
        "> Machine-generated from `locks/sentinel/` and `locks/drain/` manifests.",
        "> Regenerate with: `python scripts/evidence_index.py --md docs/EVIDENCE_INDEX.md`",
        "",
        f"**{index['entry_count']} entries** | Schema: `{index['schema_version']}`",
        "",
    ]

    locks = [e for e in index["entries"] if e.get("kind") == "sentinel_lock"]
    drains = [e for e in index["entries"] if e.get("kind") == "drain_result"]

    if locks:
        lines += [
            "## Sentinel Locks",
            "",
            "| Lock | Tests | Full Suite | Commit | Reproduction |",
            "|------|------:|----------:|--------|-------------|",
        ]
        for e in sorted(locks, key=lambda x: x["evidence_id"]):
            eid = e["evidence_id"]
            manifest = _markdown_manifest_link(root, e["manifest_path"], markdown_path)
            tests = e["test_count"]
            full = e["full_suite_count"]
            commit = str(e["commit"])[:10]
            cmd = e["reproduction_command"].replace("|", "\\|")
            lines.append(f"| [{eid}]({manifest}) | {tests} | {full} | `{commit}` | `{cmd[:70]}…` |")
        lines.append("")

        lines += ["### What Each Lock Proves", ""]
        for e in sorted(locks, key=lambda x: x["evidence_id"]):
            eid = e["evidence_id"]
            proves = e["proves"]
            does_not_prove = e["does_not_prove"]
            lines += [
                f"#### {eid}",
                "",
                f"**Proves:** {proves}",
                "",
                f"**Does not prove:** {does_not_prove}",
                "",
            ]

    if drains:
        lines += [
            "## Drain Results (ProgramBench)",
            "",
            "| Artifact | Tests | Decision | Commit |",
            "|----------|------:|---------|--------|",
        ]
        for e in sorted(drains, key=lambda x: x["evidence_id"]):
            eid = e["evidence_id"]
            manifest = _markdown_manifest_link(root, e["manifest_path"], markdown_path)
            tests = e["test_count"]
            commit = str(e["commit"])[:10]
            proves_short = str(e["proves"])[:80]
            lines.append(f"| [{eid}]({manifest}) | {tests} | {proves_short} | `{commit}` |")
        lines.append("")

    errors = index.get("validation_errors") or []
    if errors:
        lines += [
            "## Validation Errors",
            "",
            "The following entries failed validation — investigate before release:",
            "",
        ]
        for err in errors:
            lines.append(f"- `{err}`")
        lines.append("")
    else:
        lines += ["## Validation", "", "> All entries passed validation.", ""]

    return "\n".join(lines) + "\n"


def _markdown_manifest_link(root: Path, manifest_path: str, markdown_path: Path | None) -> str:
    if markdown_path is None:
        return manifest_path
    md_path = markdown_path if markdown_path.is_absolute() else root / markdown_path
    target = (root / manifest_path).resolve()
    return Path(os.path.relpath(target, start=md_path.resolve().parent)).as_posix()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument(
        "--md",
        type=Path,
        default=None,
        help="Also write a Markdown version (e.g. docs/EVIDENCE_INDEX.md)",
    )
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    index = generate_index(ROOT)
    if args.check:
        print(json.dumps({"validation_errors": index["validation_errors"]}, indent=2))
        return 1 if index["validation_errors"] else 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)

    if args.md:
        md = generate_markdown(index, ROOT, args.md)
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(md, encoding="utf-8")
        print(args.md)

    if index["validation_errors"]:
        print(json.dumps({"validation_errors": index["validation_errors"]}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
