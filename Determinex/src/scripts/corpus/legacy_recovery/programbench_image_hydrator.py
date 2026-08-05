#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.programbench_local_verifier_mode import evaluate_local_verifier


class ImageHydrationStatus(str, Enum):
    IMAGE_LOCAL_READY = "IMAGE_LOCAL_READY"
    IMAGE_PULL_READY = "IMAGE_PULL_READY"
    IMAGE_HYDRATED_FROM_CACHE = "IMAGE_HYDRATED_FROM_CACHE"
    ONLINE_DISCOVERY_CANDIDATE_FOUND = "ONLINE_DISCOVERY_CANDIDATE_FOUND"
    ONLINE_ARTIFACT_PINNED = "ONLINE_ARTIFACT_PINNED"
    ONLINE_ARTIFACT_REJECTED = "ONLINE_ARTIFACT_REJECTED"
    ONLINE_ARTIFACT_AMBIGUOUS = "ONLINE_ARTIFACT_AMBIGUOUS"
    IMAGE_MISSING = "IMAGE_MISSING"
    IMAGE_PULL_FAILED = "IMAGE_PULL_FAILED"
    IMAGE_METADATA_MISSING = "IMAGE_METADATA_MISSING"
    IMAGE_NAME_AMBIGUOUS = "IMAGE_NAME_AMBIGUOUS"
    LOCAL_NO_IMAGE_VERIFIER_READY = "LOCAL_NO_IMAGE_VERIFIER_READY"
    LOCAL_NO_IMAGE_VERIFIER_UNSUPPORTED = "LOCAL_NO_IMAGE_VERIFIER_UNSUPPORTED"


READY_STATUSES = {
    ImageHydrationStatus.IMAGE_LOCAL_READY.value,
    ImageHydrationStatus.IMAGE_HYDRATED_FROM_CACHE.value,
    ImageHydrationStatus.LOCAL_NO_IMAGE_VERIFIER_READY.value,
    ImageHydrationStatus.ONLINE_ARTIFACT_PINNED.value,
}


DockerImageLister = Callable[[], list[str]]
ImagePuller = Callable[[str], bool]


@dataclass(slots=True)
class ImageHydrationConfig:
    image_roots: list[Path]
    output_path: Path = Path(
        "assurance/evidence/programbench_replay_batch_001_image_hydration_report.json"
    )
    disambiguation_report: Path | None = None
    allow_pull: bool = False
    docker_image_lister: DockerImageLister | None = None
    image_puller: ImagePuller | None = None


@dataclass(slots=True)
class ImageHydrationResult:
    tool: str
    status: str = ""
    task_image: str = ""
    image_source: str = ""
    selected_root: str = ""
    local_verifier_allowed: bool = False
    local_verifier_reason: str = ""
    local_verifier_command: str = ""
    local_verifier_limitations: list[str] = field(default_factory=list)
    verifier_scope: str = ""
    searched: list[str] = field(default_factory=list)
    reason: str = ""


class ProgramBenchImageHydrator:
    def __init__(self, config: ImageHydrationConfig) -> None:
        self.config = config
        self.selected_roots = _selected_roots(config.disambiguation_report)

    def hydrate_batch(self, batch_artifact: Path) -> dict[str, Any]:
        batch = json.loads(batch_artifact.read_text(encoding="utf-8"))
        candidates = list(batch.get("selected") or [])
        results = [self.hydrate_candidate(candidate) for candidate in candidates]
        counts = _counts(result.status for result in results)
        report = {
            "schema_version": "determinex-programbench-image-hydration-v1",
            "batch_id": "legacy_replay_promotion_batch_001",
            "source_batch": str(batch_artifact),
            "candidates": len(candidates),
            "image_local_ready": counts.get(ImageHydrationStatus.IMAGE_LOCAL_READY.value, 0),
            "image_hydrated": counts.get(ImageHydrationStatus.IMAGE_HYDRATED_FROM_CACHE.value, 0),
            "image_pull_ready": counts.get(ImageHydrationStatus.IMAGE_PULL_READY.value, 0),
            "local_no_image_ready": counts.get(
                ImageHydrationStatus.LOCAL_NO_IMAGE_VERIFIER_READY.value, 0
            ),
            "missing": counts.get(ImageHydrationStatus.IMAGE_MISSING.value, 0)
            + counts.get(ImageHydrationStatus.IMAGE_METADATA_MISSING.value, 0),
            "ambiguous": counts.get(ImageHydrationStatus.IMAGE_NAME_AMBIGUOUS.value, 0),
            "pull_failed": counts.get(ImageHydrationStatus.IMAGE_PULL_FAILED.value, 0),
            "status_counts": counts,
            "results": [asdict(result) for result in results],
            "policy": "Image hydration does not run verifier or promote rows. Local no-image mode uses verifier_scope=local_replay, never official_programbench.",
        }
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report

    def hydrate_candidate(self, candidate: dict[str, Any]) -> ImageHydrationResult:
        tool = str(candidate.get("tool") or "")
        root = Path(
            self.selected_roots.get(tool)
            or candidate.get("selected_root")
            or candidate.get("task_root")
            or ""
        )
        result = ImageHydrationResult(
            tool=tool, selected_root=str(root) if str(root) != "." else ""
        )
        local = evaluate_local_verifier(candidate, root) if root and root.exists() else None
        if local and local.allowed:
            result.status = ImageHydrationStatus.LOCAL_NO_IMAGE_VERIFIER_READY.value
            result.local_verifier_allowed = True
            result.local_verifier_reason = local.reason
            result.local_verifier_command = local.command
            result.local_verifier_limitations = local.limitations
            result.verifier_scope = local.verifier_scope
            result.reason = "explicit_local_no_image_verifier"
            return result
        if local:
            result.local_verifier_reason = local.reason

        image, source = _explicit_image(candidate, root)
        result.task_image = image
        result.image_source = source
        if not image:
            if local and local.declared:
                result.status = ImageHydrationStatus.LOCAL_NO_IMAGE_VERIFIER_UNSUPPORTED.value
                result.reason = local.reason
                return result
            result.status = ImageHydrationStatus.IMAGE_METADATA_MISSING.value
            result.reason = "no_explicit_image_metadata"
            return result
        if _is_ambiguous_image(image):
            result.status = ImageHydrationStatus.IMAGE_NAME_AMBIGUOUS.value
            result.reason = "image_name_ambiguous"
            return result

        local_images = set(
            self.config.docker_image_lister() if self.config.docker_image_lister else []
        )
        if image in local_images:
            result.status = ImageHydrationStatus.IMAGE_LOCAL_READY.value
            result.reason = "docker_image_list_match"
            return result

        cached = _cached_image(image, self.config.image_roots)
        result.searched = [str(root) for root in self.config.image_roots]
        if cached:
            result.status = ImageHydrationStatus.IMAGE_HYDRATED_FROM_CACHE.value
            result.reason = f"cache_artifact:{cached}"
            return result

        if self.config.allow_pull:
            if self.config.image_puller is None:
                result.status = ImageHydrationStatus.IMAGE_PULL_READY.value
                result.reason = "pull_allowed_no_runner"
                return result
            if self.config.image_puller(image):
                result.status = ImageHydrationStatus.IMAGE_PULL_READY.value
                result.reason = "pull_runner_success"
                return result
            result.status = ImageHydrationStatus.IMAGE_PULL_FAILED.value
            result.reason = "pull_runner_failed"
            return result

        result.status = ImageHydrationStatus.IMAGE_MISSING.value
        result.reason = "image_not_local_and_pull_disabled"
        return result


def _explicit_image(candidate: dict[str, Any], root: Path) -> tuple[str, str]:
    for key in ("task_image", "docker_image", "image"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), f"candidate.{key}"
    for path in _metadata_paths(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for key in ("task_image", "docker_image", "image"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), str(path)
    return "", ""


def _metadata_paths(root: Path) -> list[Path]:
    if not root or not root.exists():
        return []
    return [
        root / name for name in ("manifest.json", "task.json", "metadata.json", "programbench.json")
    ]


def _cached_image(image: str, roots: list[Path]) -> str:
    safe = _safe_image_name(image)
    for root in roots:
        if not root.exists():
            continue
        for suffix in (".tar", ".json", ".txt"):
            path = root / f"{safe}{suffix}"
            if path.is_file():
                return str(path)
    return ""


def _is_ambiguous_image(image: str) -> bool:
    return image in {"latest", "programbench/latest", "unknown"} or image.endswith("/:latest")


def _safe_image_name(image: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in image)[:180]


def _selected_roots(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    selected_statuses = {
        "CANONICAL_ROOT_SELECTED",
        "OVERRIDE_ROOT_SELECTED",
        "LOCKED_ROOT_SELECTED",
        "ACTIVE_RUN_ROOT_SELECTED",
        "T_DRIVE_RUN_ROOT_SELECTED",
    }
    out: dict[str, str] = {}
    for row in data.get("results") or []:
        if isinstance(row, dict) and row.get("tool") and row.get("status") in selected_statuses:
            out[str(row["tool"])] = str(row.get("selected_root") or "")
    return out


def _counts(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve ProgramBench task images or explicit local no-image verifier mode."
    )
    parser.add_argument("batch_artifact", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "assurance/evidence/programbench_replay_batch_001_image_hydration_report.json"
        ),
    )
    parser.add_argument(
        "--disambiguation-report",
        type=Path,
        default=Path("assurance/evidence/programbench_root_disambiguation_batch_001.json"),
    )
    parser.add_argument(
        "--image-root",
        action="append",
        type=Path,
        default=[Path("assurance/evidence/programbench_images"), Path("T:/programbench-images")],
    )
    parser.add_argument("--allow-pull", action="store_true")
    args = parser.parse_args()

    report = ProgramBenchImageHydrator(
        ImageHydrationConfig(
            image_roots=args.image_root,
            output_path=args.output,
            disambiguation_report=args.disambiguation_report,
            allow_pull=args.allow_pull,
        )
    ).hydrate_batch(args.batch_artifact)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
