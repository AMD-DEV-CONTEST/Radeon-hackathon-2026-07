"""Package frozen models, manifests, and valid competition evidence.

Large generated datasets and invalid raw-headless closed-loop results are
deliberately excluded. Run this script from the project root on the persistent
cloud workspace, then download the resulting ZIP for repository assembly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = (
    "configs/paper_protocol.json",
    "configs/nuscenes_trainval_v3_split.json",
    "data/chronosafe_nuscenes_trainval_timing_v3.json",
    "artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026/model.pt",
    "artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2027/model.pt",
    "artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2028/model.pt",
    "results/fair_trainval_timestamp_robust_aggregate",
    "results/timestamp_robustness_v4_robust_aggregate",
    "results/mrm_threshold_calibration_xvfb_timestamp_robust_seed2026",
    "results/closed_loop_xvfb_timestamp_robust_seed2026",
    "results/rocm_inference_benchmark_seed2026",
)

OPTIONAL_PATHS = (
    "artifacts/hybrid_timing_gru_v3_large_seed2026/model.pt",
    "artifacts/hybrid_timing_gru_v3_large_seed2027/model.pt",
    "artifacts/hybrid_timing_gru_v3_large_seed2028/model.pt",
    "artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026/metrics.json",
    "artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2027/metrics.json",
    "artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2028/metrics.json",
    "results/timestamp_robustness_v3",
    "evidence/closed_loop_xvfb_timestamp_robust_seed2026",
)

EXCLUDED_PARTS = {
    "raw_headless",
    "closed_loop_raw_headless",
    "closed_loop_headless",
    "__pycache__",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ChronoSafe-submission-evidence.zip"),
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_under(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(item for item in path.rglob("*") if item.is_file())


def safe_relative(path: Path) -> str:
    relative = path.resolve().relative_to(PROJECT_ROOT.resolve())
    if any(part.lower() in EXCLUDED_PARTS for part in relative.parts):
        raise ValueError(f"Excluded result path was selected: {relative}")
    return PurePosixPath(*relative.parts).as_posix()


def main() -> None:
    args = parse_args()
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    missing = [name for name in REQUIRED_PATHS if not (PROJECT_ROOT / name).exists()]
    if missing:
        raise FileNotFoundError(
            "Required submission evidence is missing:\n- " + "\n- ".join(missing)
        )

    selected: dict[str, Path] = {}
    for name in (*REQUIRED_PATHS, *OPTIONAL_PATHS):
        path = PROJECT_ROOT / name
        if not path.exists():
            if name in OPTIONAL_PATHS:
                print(f"optional evidence absent: {name}")
            continue
        for file in files_under(path):
            relative = safe_relative(file)
            if relative.endswith((".npz", ".tar", ".tar.gz")):
                raise ValueError(f"Large/generated data must not enter the evidence ZIP: {relative}")
            selected[relative] = file

    manifest_files = []
    for relative, file in sorted(selected.items()):
        manifest_files.append(
            {
                "path": relative,
                "bytes": file.stat().st_size,
                "sha256": sha256_file(file),
            }
        )
    manifest = {
        "project": "ChronoSafe-Drive",
        "purpose": "competition submission evidence",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "exclusions": [
            "raw nuScenes media",
            "generated NPZ datasets",
            "raw-headless renderer-bypass closed-loop results",
        ],
        "files": manifest_files,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, file in sorted(selected.items()):
            archive.write(file, relative)
        archive.writestr(
            "submission_evidence_manifest.json",
            json.dumps(manifest, indent=2).encode("utf-8"),
        )

    with zipfile.ZipFile(output, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("Duplicate archive entries were generated")
        if "submission_evidence_manifest.json" not in names:
            raise RuntimeError("Evidence manifest is absent from the archive")
        bad = [
            name
            for name in names
            if "raw_headless" in name.lower() or name.lower().endswith(".npz")
        ]
        if bad:
            raise RuntimeError(f"Forbidden evidence entered the archive: {bad}")

    print(
        f"SUBMISSION EVIDENCE ZIP PASS: {output} "
        f"({len(selected)} files, {output.stat().st_size / 2**20:.2f} MiB)"
    )


if __name__ == "__main__":
    main()
