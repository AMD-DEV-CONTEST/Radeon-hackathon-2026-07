"""Audit the repository against the Track 3 release structure."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_FILES = (
    "README.md",
    "README.zh-CN.md",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "requirements.local.txt",
    "requirements.remote.txt",
    "docs/REMOTE_ROCM_SETUP.md",
    "docs/DATASET_CARD.md",
    "docs/MODEL_CARD.md",
    "artifacts/evaluation.schema.json",
    ".dockerignore",
    "docker/Dockerfile",
    "docker/compose.yaml",
    "docker/entrypoint.sh",
    "reports/RadeonVLA-Reflex-Technical-Report.md",
    "src/radeonvla/record_dataset.py",
    "src/radeonvla/train_policy.py",
    "src/radeonvla/evaluate.py",
    "src/radeonvla/stress.py",
    "src/radeonvla/artifact_io.py",
    "src/radeonvla/vendor_vlm_assets.py",
    "src/radeonvla/pipeline.py",
    "src/radeonvla/grounding.py",
    "src/radeonvla/tasks.py",
    "scripts/run_all_local.sh",
    "scripts/run_record.sh",
    "scripts/run_full_remote.sh",
    "scripts/lib.sh",
    "Makefile",
    "assets/README.md",
    "assets/SHA256SUMS",
    "assets/robots/franka/panda.xml",
    "assets/ycb/011_banana/textured.obj",
    "assets/ycb/013_apple/textured.obj",
    "assets/ycb/014_lemon/textured.obj",
    "assets/ycb/017_orange/textured.obj",
    "assets/ycb/018_plum/textured.obj",
    "assets/ycb/024_bowl/textured.obj",
)

README_HEADINGS = (
    "## Target application",
    "## System architecture",
    "## Dependency policy",
    "## Local development setup",
    "## Remote AMD Radeon setup",
    "## Dataset specification",
    "## Evaluation protocol",
    "## Reproduction sequence",
    "## Deliverables",
    "## Team",
    "## Submission",
)

REPORT_HEADINGS = (
    "## 2. Target Application",
    "## 4. System Architecture",
    "## 6. Demonstration Dataset",
    "## 7. Model and Training",
    "## 10. AMD Radeon GPU and ROCm Integration",
    "## 14. Innovation and Technical Contributions",
    "## 15. Deliverables",
    "## 17. Team Member and Contribution",
)

UNFINALIZED_MARKERS = (
    "pre-release",
    "TBD",
    "<GITHUB_ID>",
    "<PVC_ROOT>",
    "<SUBMITTED_",
    "<BEST_CHECKPOINT>",
    "<PUBLIC_",
)


@dataclass
class AuditResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _read(path: Path, result: AuditResult) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        result.errors.append(f"Cannot read {path}: {exc}")
        return ""


def audit_project(root: Path, *, final: bool = False) -> AuditResult:
    result = AuditResult()

    for relative in REQUIRED_FILES:
        path = root / relative
        if not path.is_file():
            result.errors.append(f"Missing required project file: {relative}")

    readme = _read(root / "README.md", result)
    for heading in README_HEADINGS:
        if heading not in readme:
            result.errors.append(f"README is missing heading: {heading}")

    report = _read(root / "reports/RadeonVLA-Reflex-Technical-Report.md", result)
    for heading in REPORT_HEADINGS:
        if heading not in report:
            result.errors.append(f"Technical report is missing heading: {heading}")

    release_files = (
        root / "README.md",
        root / "docs/DATASET_CARD.md",
        root / "docs/MODEL_CARD.md",
        root / "reports/RadeonVLA-Reflex-Technical-Report.md",
    )
    for path in release_files:
        text = _read(path, result)
        found = sorted(token for token in UNFINALIZED_MARKERS if token in text)
        if found:
            message = f"{path.relative_to(root)} contains pre-release markers: {', '.join(found)}"
            if final:
                result.errors.append(message)
            else:
                result.warnings.append(message)

    if final:
        report_pdf = root / "reports/RadeonVLA-Reflex-Technical-Report.pdf"
        checksums = root / "artifacts/SHA256SUMS"
        if not report_pdf.is_file():
            result.errors.append(f"Missing final report PDF: {report_pdf.relative_to(root)}")
        if not checksums.is_file():
            result.errors.append(f"Missing final checksums: {checksums.relative_to(root)}")

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--final", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = audit_project(args.root.resolve(), final=args.final)

    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}")

    if result.ok:
        print("Release structure audit passed.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
