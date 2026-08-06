#!/usr/bin/env python3
"""Build a strict allowlisted AMD Track 1 public repository export."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Iterable

from validate_amd_public_export import sha256_file, validate


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = (ROOT / "dist" / "amd-track1").resolve()
DEFAULT_OUTPUT = DIST_ROOT / "prooflaunch"

ROOT_FILES = {
    ".env.example",
    ".gitignore",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "JUDGE_START_HERE.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "SUBMISSION_GATE.json",
    "SUPPORT.md",
    "THIRD_PARTY.md",
    "openapi_letta.json",
    "pyproject.toml",
    "requirements-radeon.txt",
    "uv.lock",
}

TREE_SUFFIXES = {
    ".github": {".md", ".yml", ".yaml", ""},
    "src": {".py", ".json"},
    "demos": {".py"},
    "scripts": {".py", ".mjs", ".cjs", ".sh"},
    "tests": {".py", ".mjs"},
    "web": {
        ".css",
        ".html",
        ".js",
        ".json",
        ".mjs",
        ".png",
        ".jpg",
        ".jpeg",
        ".svg",
        ".txt",
        ".woff",
        ".woff2",
    },
    "config": {".json", ".yml", ".yaml"},
    "configs": {".json", ".yml", ".yaml"},
    "workflows": {".json", ".md", ".yml", ".yaml"},
    "notebooks": {".ipynb"},
    "docs": {".csv", ".jpg", ".json", ".md", ".mp4", ".pdf", ".png", ".pptx", ".txt"},
    "submission": {".json", ".md"},
    "upstream_patches": {".diff", ".md", ".patch"},
    "demo": {".blend", ".md", ".py", ".scd"},
}

EXCLUDED_COMPONENTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}

EXCLUDED_PREFIXES = {
    Path("web/qa"),
    Path("src/prooflaunch_agent_remix.egg-info"),
}

EXCLUDED_FILES = {
    Path("docs/FINAL_PRODUCT_CLOSURE_AND_RESULTS_RECORD_2026-08-05.md"),
    Path("docs/product/AUG3_DEMO_RUNBOOK.md"),
    Path("docs/product/GTM_ONE_HOUR_FINAL_EXECUTION_PLAN_2026-08-06.md"),
}

REPLAY_EVIDENCE = {
    Path("evidence/OFFICIAL_TRACK1_RULES_AUDIT_2026-07-30.json"),
    Path("evidence/RADEON_BROWSER_SESSION_2026-07-29.json"),
    Path("evidence/RADEON_BROWSER_SESSION_V10.json"),
    Path("evidence/RADEON_BROWSER_SYNC_2026-07-30.json"),
    Path("evidence/RADEON_EVIDENCE_INDEX.md"),
    Path("evidence/RADEON_GEMMA4_EXECUTION_RECEIPT_2026-08-06.json"),
    Path("evidence/RADEON_MULTIGPU_PREFLIGHT_2026-07-30.json"),
    Path("evidence/RADEON_RUNTIME_ROUTE_AUDIT_2026-07-29.json"),
    Path("evidence/v10/aug3-product-readiness.json"),
    Path("evidence/v10/gtm-production-quality-current-v1.json"),
    Path("evidence/v10/gtm-last-mile-production-quality-v1.json"),
    Path("evidence/v10/local-multimodal-qualification.json"),
    Path("evidence/v10/radeon-instance-recovery-2026-07-31.json"),
    Path("evidence/v10/radeon-runtime-reprobe-2026-07-31.json"),
    Path("evidence/v10/radeon-template-ab-reprobe-2026-07-31.json"),
    Path(
        "evidence/v10/local-campaign-pack-v1/"
        "openai-imagegen-evidence-engine-challenger-v1.metadata.json"
    ),
    Path("artifacts/public-signal-gtm-pilot-v1/pilot-receipt.json"),
}

OPTIONAL_FINAL_EVIDENCE = {
    Path("evidence/v10/radeon-live-preflight.json"),
    Path("docs/ProofLaunch_Demo_Video_191s.mp4"),
    Path("docs/demo-video-url.txt"),
    Path("docs/pull-request-url.txt"),
}


def _is_under(relative: Path, prefix: Path) -> bool:
    try:
        relative.relative_to(prefix)
    except ValueError:
        return False
    return True


def is_public_tree_file(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    relative = path.relative_to(ROOT)
    if relative in EXCLUDED_FILES:
        return False
    if any(_is_under(relative, prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if any(part in EXCLUDED_COMPONENTS or part.endswith(".egg-info") for part in relative.parts):
        return False
    if path.suffix in {".pyc", ".pyo"} or path.name == ".DS_Store":
        return False
    suffixes = TREE_SUFFIXES.get(relative.parts[0])
    return suffixes is not None and path.suffix.lower() in suffixes


def _manifest_core_paths() -> set[Path]:
    manifest_path = ROOT / "submission/track1-prooflaunch/SUBMISSION_MANIFEST.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths: set[Path] = set()
    for item in payload.get("core_evidence", []):
        if isinstance(item, dict) and item.get("path"):
            paths.add(Path(str(item["path"])))
    return paths


def _gate_existing_paths() -> set[Path]:
    gate = json.loads((ROOT / "SUBMISSION_GATE.json").read_text(encoding="utf-8"))
    paths: set[Path] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and "/" in value:
            candidate = Path(value)
            if not candidate.is_absolute() and candidate.parts[0] in {
                "artifacts",
                "demo",
                "docs",
                "evidence",
                "submission",
            }:
                if (ROOT / candidate).is_file():
                    paths.add(candidate)

    visit(gate)
    return paths


def select_public_files() -> list[Path]:
    selected: set[Path] = set()
    for name in ROOT_FILES:
        path = ROOT / name
        if path.is_file() and not path.is_symlink():
            selected.add(path)

    for directory in TREE_SUFFIXES:
        root = ROOT / directory
        if not root.is_dir():
            continue
        selected.update(path for path in root.rglob("*") if is_public_tree_file(path))

    selected.update(ROOT / path for path in REPLAY_EVIDENCE if (ROOT / path).is_file())
    selected.update(ROOT / path for path in _manifest_core_paths() if (ROOT / path).is_file())
    selected.update(
        ROOT / path for path in OPTIONAL_FINAL_EVIDENCE if (ROOT / path).is_file()
    )

    campaign_pack = ROOT / "evidence/v10/local-campaign-pack-v1/delivery-v6"
    if campaign_pack.is_dir():
        selected.update(path for path in campaign_pack.rglob("*") if path.is_file() and not path.is_symlink())

    demo_receipts = ROOT / "artifacts/run-bound-multimodal-demo-v1"
    if demo_receipts.is_dir():
        selected.update(
            path
            for path in demo_receipts.rglob("*")
            if path.is_file() and path.suffix.lower() == ".json" and not path.is_symlink()
        )

    final_demo = ROOT / "demo/final/prooflaunch-amd-track1-demo.mp4"
    if final_demo.is_file() and not final_demo.is_symlink():
        selected.add(final_demo)

    return sorted(selected, key=lambda path: path.relative_to(ROOT).as_posix())


def _validate_output(output: Path) -> Path:
    resolved = output.expanduser().resolve()
    try:
        relative = resolved.relative_to(DIST_ROOT)
    except ValueError as exc:
        raise SystemExit(f"output must remain inside {DIST_ROOT}") from exc
    if relative.parts != ("prooflaunch",):
        raise SystemExit("output must be the exact dist/amd-track1/prooflaunch directory")
    if resolved.is_symlink():
        raise SystemExit("output may not be a symlink")
    return resolved


def build(output: Path = DEFAULT_OUTPUT, *, replace: bool = False) -> dict[str, Any]:
    destination = _validate_output(output)
    if destination.exists():
        if not replace:
            raise SystemExit(f"output already exists: {destination}; pass --replace after inspection")
        if destination.is_symlink() or not destination.is_dir():
            raise SystemExit("refusing to replace an unexpected output target")
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=False)

    selected = select_public_files()
    for source in selected:
        relative = source.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    entries = []
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            entries.append(
                {
                    "path": path.relative_to(destination).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )

    gate = json.loads((destination / "SUBMISSION_GATE.json").read_text(encoding="utf-8"))
    manifest = {
        "schema": "ProofLaunchAMDPublicExportManifestV1",
        "competition": "AMD Radeon Hackathon 2026-07",
        "track": "Track 1",
        "team": "Banyan",
        "application": "ProofLaunch",
        "repository_root": "prooflaunch/",
        "competition_status": gate.get("overallStatus", "unknown"),
        "file_count": len(entries),
        "total_bytes": sum(item["bytes"] for item in entries),
        "files": entries,
    }
    (destination / "PUBLIC_EXPORT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    report = validate(destination)
    (destination / "PUBLIC_EXPORT_VALIDATION.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if report["status"] != "passed":
        raise SystemExit(json.dumps(report, indent=2, ensure_ascii=False))
    return {"output": str(destination), "manifest": manifest, "validation": report}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--list", action="store_true", help="list selected files without writing")
    args = parser.parse_args()
    if args.list:
        for path in select_public_files():
            print(path.relative_to(ROOT).as_posix())
        return 0
    result = build(args.output, replace=args.replace)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
