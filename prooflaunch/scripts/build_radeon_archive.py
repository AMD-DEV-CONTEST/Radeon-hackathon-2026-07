from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import stat
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Runtime state is deliberately outside the portable source/evidence boundary.
# It can contain reviewer assignments, local model predictions, bearer-token
# hashes, API state, or other machine-local material that must never enter a
# submission or GPU handoff archive.  Keep this denylist before every allowlist
# below so a future broad evidence/source rule cannot override it.
PRIVATE_ROOTS = {
    ".prooflaunch-runtime",
    ".prooflaunch-secrets",
    ".super-site-10x",
}
PUBLIC_HIDDEN_ROOTS = {".github"}


def part_filename(version: str, index: int, part_count: int) -> str:
    if index < 0 or part_count < 1 or index >= part_count:
        raise ValueError("invalid archive part index")
    width = max(2, len(str(part_count - 1)))
    return f"prooflaunch-radeon-{version}.part-{index:0{width}d}"


def should_include(path: Path, version: str) -> bool:
    relative = path.relative_to(ROOT)
    parts = relative.parts
    if not path.is_file():
        return False
    if parts and parts[0] in PRIVATE_ROOTS:
        return False
    if parts and parts[0].startswith(".") and len(parts) > 1:
        return parts[0] in PUBLIC_HIDDEN_ROOTS
    if any(
        part in {"__pycache__", ".pytest_cache", ".git", ".venv"}
        or part.endswith(".egg-info")
        for part in parts
    ):
        return False
    if path.suffix in {".pyc", ".pyo"} or path.name == ".DS_Store":
        return False
    if parts[0] == "evidence":
        if version != "v10":
            return False
        if parts[:3] == ("evidence", "v10", "image-mastering-fixture"):
            return parts[3:] in {
                ("background-3840x2160.png",),
                ("google-no-text-3840x2160.png",),
                ("logo-mask.png",),
                ("master-3840x2160.png",),
                ("product-mask.png",),
                ("product-source.png",),
                ("report.json",),
                ("social-safe-3840x2160.png",),
                ("text-mask.png",),
            }
        if parts[:3] == ("evidence", "v10", "video-mastering-fixture"):
            return parts[3:] in {
                ("frame-000-3840x2160.png",),
                ("frame-047-3840x2160.png",),
                ("frame-048-3840x2160.png",),
                ("frame-143-3840x2160.png",),
                ("frame-144-3840x2160.png",),
                ("frame-191-3840x2160.png",),
                ("report.json",),
            }
        # The portable V10 suite consumes public, redacted JSON receipts through
        # the TODO closure definitions.  Keep those receipts complete so a clean
        # extraction can verify the same closure report as the source tree.  Raw
        # Token Factory panel responses remain excluded below because their
        # training and redistribution rights are unresolved.
        if parts[:3] == ("evidence", "v10", "tokenfactory-final-panel"):
            return parts[3:] == ("receipt.json",)
        if parts[:4] in {
            (
                "evidence",
                "v10",
                "local-campaign-pack-v1",
                "delivery-v5",
            ),
            (
                "evidence",
                "v10",
                "local-campaign-pack-v1",
                "delivery-v6",
            ),
        }:
            # These exact hash-bound media files are required by the product
            # readiness receipt, human comparison, and portable demo API.
            # Earlier campaign iterations remain excluded.
            return True
        if parts == (
            "evidence",
            "v10",
            "local-campaign-pack-v1",
            "openai-imagegen-evidence-engine-challenger-v1.png",
        ):
            return True
        if parts[:2] == ("evidence", "v10") and path.suffix.lower() == ".json":
            return True
        return parts in {
            (
                "evidence",
                "OFFICIAL_TRACK1_RULES_AUDIT_2026-07-30.json",
            ),
            (
                "evidence",
                "GEMMA4_MODELSCOPE_REVISION_LOCK_2026-07-30.json",
            ),
            (
                "evidence",
                "RADEON_BROWSER_SYNC_2026-07-30.json",
            ),
            (
                "evidence",
                "RADEON_MULTIGPU_PREFLIGHT_2026-07-30.json",
            ),
            ("evidence", "v10", "20-lens-synthesis.json"),
            (
                "evidence",
                "v10",
                "agentic-gtm-flagship-benchmark-2026-07-31.json",
            ),
            ("evidence", "v10", "breakthrough-matrix.json"),
            (
                "evidence",
                "v10",
                "agency-corpus-v2-dataset-card-audit.json",
            ),
            (
                "evidence",
                "v10",
                "agency-trajectories-1000-independent-replay.json",
            ),
            (
                "evidence",
                "v10",
                "cpt-corpus-independent-recount.json",
            ),
            (
                "evidence",
                "v10",
                "gold-candidates-independent-audit.json",
            ),
            (
                "evidence",
                "v10",
                "gold-five-human-review-gate.json",
            ),
            (
                "evidence",
                "v10",
                "preference-pairs-5k-independent-audit.json",
            ),
            (
                "evidence",
                "v10",
                "region-preferences-2k-independent-audit.json",
            ),
            (
                "evidence",
                "v10",
                "repair-episodes-500-independent-audit.json",
            ),
            (
                "evidence",
                "v10",
                "sft-corpus-15k-independent-audit.json",
            ),
            ("evidence", "v10", "brand-memory-seed-audit.json"),
            ("evidence", "v10", "brand-memory-runtime-audit.json"),
            ("evidence", "v10", "double-standard-requirements.json"),
            ("evidence", "v10", "fireworks-access-state.json"),
            (
                "evidence",
                "v10",
                "frontier-free-api-availability-2026-07-31.json",
            ),
            (
                "evidence",
                "v10",
                "frontier-api-panel-preflight.json",
            ),
            (
                "evidence",
                "v10",
                "frontier-free-api-sprint.json",
            ),
            ("evidence", "v10", "four-a-campaign-research-audit.json"),
            ("evidence", "v10", "four-a-transfer-corpus-validation.json"),
            ("evidence", "v10", "full-scenario-training-audit.json"),
            ("evidence", "v10", "gtm-seed-corpus-audit.json"),
            ("evidence", "v10", "local-test-report.json"),
            (
                "evidence",
                "v10",
                "local-test-report.on-policy-distillation-v1.json",
            ),
            (
                "evidence",
                "v10",
                "local-test-report.agentic-gtm-v1.json",
            ),
            (
                "evidence",
                "v10",
                "local-test-report.multi-objective-alignment-v1.json",
            ),
            ("evidence", "v10", "memory-card.json"),
            ("evidence", "v10", "multigpu-execution-plan.json"),
            ("evidence", "v10", "cpt-card.planned.json"),
            ("evidence", "v10", "sft-card.planned.json"),
            (
                "evidence",
                "v10",
                "on-policy-distillation-card.planned.json",
            ),
            (
                "evidence",
                "v10",
                "multi-objective-alignment-card.planned.json",
            ),
            (
                "evidence",
                "v10",
                "adapter-pseudo-moe-card.planned.json",
            ),
            (
                "evidence",
                "v10",
                "peft-hotswap-local-probe.json",
            ),
            (
                "evidence",
                "v10",
                "local-test-report.adapter-stack-v1.json",
            ),
            (
                "evidence",
                "v10",
                "gtm-skill-card.planned.json",
            ),
            (
                "evidence",
                "v10",
                "local-test-report.gtm-employee-v1.json",
            ),
            ("evidence", "v10", "image-pack-card.planned.json"),
            (
                "evidence",
                "v10",
                "local-test-report.image-mastering-v1.json",
            ),
            ("evidence", "v10", "video-pack-card.planned.json"),
            (
                "evidence",
                "v10",
                "local-test-report.video-mastering-v1.json",
            ),
            (
                "evidence",
                "v10",
                "local-test-report.scientific-evaluation-v1.json",
            ),
            ("evidence", "v10", "scientific-metric-formula-fixture.json"),
            ("evidence", "v10", "scientific-report.planned.json"),
            (
                "evidence",
                "v10",
                "safety-case-mechanical-fixture.json",
            ),
            (
                "evidence",
                "v10",
                "submission-api-mechanical-fixture.json",
            ),
            (
                "evidence",
                "v10",
                "submission-flow-preflight.json",
            ),
            (
                "evidence",
                "v10",
                "competition-contract-v3-mechanical-fixture.json",
            ),
            (
                "evidence",
                "v10",
                "reuse-manifest-v1-mechanical-fixture.json",
            ),
            (
                "evidence",
                "v10",
                "research-ledger-v1-mechanical-fixture.json",
            ),
            (
                "evidence",
                "v10",
                "distillation-stack-v1-mechanical-fixture.json",
            ),
            (
                "evidence",
                "v10",
                "world-model-v1-mechanical-fixture.json",
            ),
            (
                "evidence",
                "v10",
                "dynamic-topology-v1-mechanical-fixture.json",
            ),
            (
                "evidence",
                "v10",
                "open-materials-v1-audit.json",
            ),
            (
                "evidence",
                "v10",
                "source-bundle-2000-audit.json",
            ),
            ("evidence", "v10", "program-manifest.json"),
            (
                "evidence",
                "v10",
                "radeon-runtime-reprobe-2026-07-31.json",
            ),
            (
                "evidence",
                "v10",
                "radeon-reproduction-mechanical-fixture.json",
            ),
            (
                "evidence",
                "v10",
                "radeon-instance-recovery-2026-07-31.json",
            ),
            (
                "evidence",
                "v10",
                "radeon-template-ab-reprobe-2026-07-31.json",
            ),
            ("evidence", "v10", "research-ledger.json"),
            (
                "evidence",
                "v10",
                "source-reconciliation-300-plus-1200.json",
            ),
            ("evidence", "v10", "super-site-10x-gate.json"),
            ("evidence", "v10", "tokenfactory-availability.json"),
            ("evidence", "v10", "tokenfactory-corpus-validation.json"),
            (
                "evidence",
                "v10",
                "third-party-route-reprobe-2026-07-31.json",
            ),
            (
                "evidence",
                "v10",
                "tokenfactory-final-panel",
                "receipt.json",
            ),
            ("evidence", "v10", "tokenfactory-output-rights.json"),
            ("evidence", "v10", "todo-closure-report.json"),
            ("evidence", "v10", "trajectory-kd-seed-audit.json"),
            ("evidence", "v10", "trajectory-kd-runtime-audit.json"),
            ("evidence", "v10", "trajectory-card.json"),
            ("evidence", "v10", "web-overlay-regression.json"),
            ("evidence", "v10", "web-visual-mobile-390.png"),
            ("evidence", "v10", "web-visual-tablet-dark-900.png"),
        }
    if parts == ("SUBMISSION_GATE.json",):
        return version == "v10"
    if parts[0] in {"build", "dist"}:
        return False
    if parts[:2] == ("data", "tokenfactory_teacher_v10"):
        # Raw Token Factory outputs remain private until AMD explicitly grants
        # training and redistribution rights. Public archives contain only the
        # validator, policy, and redacted aggregate receipt.
        return False
    if version == "v10" and parts in {
        ("docs", "ProofLaunch_Project_Profile.pdf"),
        ("docs", "ProofLaunch_Poster.pptx"),
        ("docs", "ProofLaunch_Submission_Deck.pptx"),
    }:
        return True
    if parts[0] == "docs" and path.suffix.lower() in {".pdf", ".pptx", ".jpg"}:
        return False
    if parts[0] == "web" and path.name == "evidence-desktop-viewport.png":
        return False
    if parts[0] == "notebooks":
        # V10's final source lock covers every committed notebook.  Omitting an
        # older gate notebook makes the extracted tree correctly report lock
        # drift, so the V10 reproduction archive carries the complete set.
        if version == "v10":
            return True
        notebook_allowlist = {
            "gemma4_emotion_lora_multimodal_safe_v2.ipynb",
            f"prooflaunch_radeon_gate_{version}.ipynb",
        }
        if version in {"v5", "v6", "v7", "v10"}:
            notebook_allowlist.add("prooflaunch_radeon_gate_v4.ipynb")
        if version in {"v6", "v7", "v10"}:
            notebook_allowlist.add("prooflaunch_radeon_gate_v5.ipynb")
        if version in {"v7", "v10"}:
            notebook_allowlist.add("prooflaunch_radeon_gate_v6.ipynb")
        return path.name in notebook_allowlist
    return True


def normalized_tarinfo(path: Path, arcname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(arcname)
    info.size = path.stat().st_size
    source_mode = stat.S_IMODE(path.stat().st_mode)
    if os.access(path, os.X_OK):
        info.mode = 0o755
    elif source_mode & 0o077 == 0:
        # Preserve an explicit owner-only privacy boundary (for example a
        # blinded review private manifest) instead of widening it to 0644.
        info.mode = 0o600
    else:
        info.mode = 0o644
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v5")
    parser.add_argument("--part-bytes", type=int, default=85_000)
    args = parser.parse_args()
    version = args.version.lower()
    if not version.startswith("v"):
        raise SystemExit("version must look like v4")
    if args.part_bytes < 1:
        raise SystemExit("part-bytes must be positive")

    output_dir = ROOT / "dist" / f"radeon-{version}"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"prooflaunch-radeon-{version}.tar.gz"
    checksum = output_dir / f"prooflaunch-radeon-{version}.sha256"
    for stale in output_dir.glob(f"prooflaunch-radeon-{version}.part-*"):
        stale.unlink()

    selected = sorted(
        path for path in ROOT.rglob("*") if should_include(path, version)
    )
    with archive.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as bundle:
                for path in selected:
                    arcname = f"prooflaunch/{path.relative_to(ROOT)}"
                    with path.open("rb") as handle:
                        bundle.addfile(normalized_tarinfo(path, arcname), handle)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    payload = archive.read_bytes()
    parts = []
    part_count = max(1, (len(payload) + args.part_bytes - 1) // args.part_bytes)
    for index, offset in enumerate(range(0, len(payload), args.part_bytes)):
        part = output_dir / part_filename(version, index, part_count)
        part.write_bytes(payload[offset : offset + args.part_bytes])
        parts.append(part)

    print(f"archive={archive}")
    print(f"sha256={digest}")
    print(f"files={len(selected)}")
    print(f"parts={len(parts)}")
    for part in parts:
        print(f"{part.name}={part.stat().st_size}")


if __name__ == "__main__":
    main()
