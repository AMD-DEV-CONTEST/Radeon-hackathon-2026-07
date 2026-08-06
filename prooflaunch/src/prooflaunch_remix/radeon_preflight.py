from __future__ import annotations

import importlib.metadata
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .competition_benchmark import (
    REQUIRED_RATIOS,
    CompetitionBenchmarkError,
    FrozenBenchmarkManifest,
    load_frozen_manifest,
)
from .files import sha256_file
from .radeon_matrix_adapter import (
    ADAPTER_VERSION,
    EXPECTED_MODEL_SUPPLY_CHAIN,
    MODEL_SUPPLY_CHAIN_SCHEMA,
    RadeonLocalCompetitionAdapter,
    validate_gemma_retention,
)


PREFLIGHT_SCHEMA = "ProofLaunchRadeonPreflightV2"
PREFLIGHT_VERSION = "2.0.0"
DEFAULT_MINIMUM_VRAM_GB = 16.0
DEFAULT_MINIMUM_FREE_DISK_GB = 40.0
CHECK_PASSED = "passed"
CHECK_BLOCKED = "blocked"
CHECK_WARNING = "warning"

DEPENDENCY_MINIMUMS: Mapping[str, str] = {
    "accelerate": "1.2",
    "av": "13",
    "diffusers": "0.35",
    "huggingface-hub": "0.27",
    "imageio": "2.37",
    "imageio-ffmpeg": "0.5",
    "librosa": "0.10",
    "numpy": "2.0",
    "peft": "0.14",
    "Pillow": "10.4",
    "PyMuPDF": "1.24",
    "qwen-vl-utils": "0.0.14",
    "safetensors": "0.4",
    "torch": "2.5",
    "transformers": "5.5",
}


@dataclass(frozen=True)
class PreflightCheck:
    check_id: str
    status: str
    summary: str
    details: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class RadeonPreflightProbe(Protocol):
    def dependency_versions(
        self,
        distributions: Sequence[str],
    ) -> Mapping[str, str | None]: ...

    def runtime(self) -> Mapping[str, object]: ...

    def free_disk_gb(self, path: Path) -> float: ...

    def ffmpeg_path(self) -> str: ...

    def cached_model_revisions(self) -> Mapping[str, set[str]]: ...


class SystemRadeonPreflightProbe:
    def dependency_versions(
        self,
        distributions: Sequence[str],
    ) -> Mapping[str, str | None]:
        versions: dict[str, str | None] = {}
        for distribution in distributions:
            try:
                versions[distribution] = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                versions[distribution] = None
        return versions

    def runtime(self) -> Mapping[str, object]:
        import torch

        available = bool(torch.cuda.is_available())
        count = int(torch.cuda.device_count()) if available else 0
        return {
            "torch_version": str(torch.__version__),
            "cuda_available": available,
            "device_count": count,
            "hip_version": getattr(torch.version, "hip", None),
            "device_name": (
                str(torch.cuda.get_device_name(0)) if available and count else None
            ),
            "total_vram_gb": (
                float(torch.cuda.get_device_properties(0).total_memory)
                / (1024**3)
                if available and count
                else 0.0
            ),
        }

    def free_disk_gb(self, path: Path) -> float:
        return float(shutil.disk_usage(path).free) / (1024**3)

    def ffmpeg_path(self) -> str:
        import imageio_ffmpeg

        return str(Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve())

    def cached_model_revisions(self) -> Mapping[str, set[str]]:
        from huggingface_hub import scan_cache_dir

        return {
            str(repo.repo_id): {
                str(revision.commit_hash)
                for revision in repo.revisions
                if revision.commit_hash
            }
            for repo in scan_cache_dir().repos
        }


def _version_tuple(value: str) -> tuple[int, ...]:
    release = value.split("+", 1)[0]
    numbers = re.findall(r"\d+", release)
    return tuple(int(item) for item in numbers[:4])


def _version_at_least(actual: str, minimum: str) -> bool:
    actual_parts = _version_tuple(actual)
    minimum_parts = _version_tuple(minimum)
    width = max(len(actual_parts), len(minimum_parts))
    return actual_parts + (0,) * (width - len(actual_parts)) >= (
        minimum_parts + (0,) * (width - len(minimum_parts))
    )


def _check(
    check_id: str,
    status: str,
    summary: str,
    **details: object,
) -> PreflightCheck:
    return PreflightCheck(
        check_id=check_id,
        status=status,
        summary=summary,
        details=details,
    )


def _safe_relative_source(root: Path, locator: str, label: str) -> Path:
    relative = Path(locator)
    if relative.is_absolute() or ".." in relative.parts:
        raise CompetitionBenchmarkError(
            f"{label} source_locator must be traversal-free and relative"
        )
    resolved_root = root.resolve()
    source = (resolved_root / relative).resolve()
    if not source.is_relative_to(resolved_root):
        raise CompetitionBenchmarkError(
            f"{label} source_locator escapes the manifest directory"
        )
    if not source.is_file():
        raise CompetitionBenchmarkError(f"{label} source does not exist: {locator}")
    return source


def _validate_manifest_sources(
    manifest_path: Path,
    manifest: FrozenBenchmarkManifest,
) -> Mapping[str, object]:
    root = manifest_path.parent.resolve()
    verified = 0
    for product in manifest.products:
        source = _safe_relative_source(
            root,
            product.source_locator,
            product.product_id,
        )
        actual = sha256_file(source)
        if actual != product.input_sha256:
            raise CompetitionBenchmarkError(
                f"{product.product_id} source hash mismatch: "
                f"expected {product.input_sha256}, got {actual}"
            )
        verified += 1
    baseline_source = _safe_relative_source(
        root,
        manifest.baseline.source_locator,
        "baseline",
    )
    baseline_sha256 = sha256_file(baseline_source)
    if baseline_sha256 != manifest.baseline.settings_sha256:
        raise CompetitionBenchmarkError(
            "baseline settings source hash does not match the frozen manifest"
        )
    video_cases = sum(case.video_required for case in manifest.cases)
    if (
        len(manifest.products) != 30
        or tuple(manifest.aspect_ratios) != REQUIRED_RATIOS
        or len(manifest.seeds) != 5
        or len(manifest.cases) != 450
        or video_cases < 30
    ):
        raise CompetitionBenchmarkError(
            "manifest does not satisfy the exact 30×3×5 / 30-video contract"
        )
    return {
        "manifest_hash": manifest.manifest_hash,
        "product_count": len(manifest.products),
        "aspect_ratios": list(manifest.aspect_ratios),
        "seed_count": len(manifest.seeds),
        "case_count": len(manifest.cases),
        "video_case_count": video_cases,
        "verified_product_source_count": verified,
        "baseline_settings_sha256": baseline_sha256,
    }


def _model_revisions(
    adapter: RadeonLocalCompetitionAdapter,
) -> Mapping[str, Mapping[str, str]]:
    return adapter.settings.model_supply_chain()


def run_radeon_preflight(
    *,
    settings_path: str | Path,
    manifest_path: str | Path | None = None,
    strict_cache: bool = False,
    minimum_vram_gb: float = DEFAULT_MINIMUM_VRAM_GB,
    minimum_free_disk_gb: float = DEFAULT_MINIMUM_FREE_DISK_GB,
    probe: RadeonPreflightProbe | None = None,
) -> dict[str, object]:
    if (
        not math.isfinite(minimum_vram_gb)
        or minimum_vram_gb <= 0
        or not math.isfinite(minimum_free_disk_gb)
        or minimum_free_disk_gb <= 0
    ):
        raise ValueError("preflight resource minimums must be positive and finite")
    selected_probe = probe or SystemRadeonPreflightProbe()
    selected_settings = Path(settings_path).expanduser().resolve()
    selected_manifest = (
        Path(manifest_path).expanduser().resolve()
        if manifest_path is not None
        else None
    )
    checks: list[PreflightCheck] = []
    adapter: RadeonLocalCompetitionAdapter | None = None
    identity: Mapping[str, object] | None = None

    try:
        adapter = RadeonLocalCompetitionAdapter.from_settings_file(
            selected_settings
        )
        identity = adapter.identity()
        valid_identity = (
            identity.get("system_kind") == "prooflaunch"
            and identity.get("uses_closed_online_api") is False
            and identity.get("version") == ADAPTER_VERSION
        )
        checks.append(
            _check(
                "adapter_identity",
                CHECK_PASSED if valid_identity else CHECK_BLOCKED,
                (
                    "Bundled local-only ProofLaunch adapter identity is valid."
                    if valid_identity
                    else "Adapter identity is not eligible for the local competition runner."
                ),
                adapter_id=identity.get("adapter_id"),
                version=identity.get("version"),
                settings_sha256=identity.get("settings_sha256"),
                system_kind=identity.get("system_kind"),
                uses_closed_online_api=identity.get("uses_closed_online_api"),
            )
        )
    except Exception as error:
        checks.append(
            _check(
                "adapter_identity",
                CHECK_BLOCKED,
                "Radeon adapter settings could not be loaded.",
                error=f"{type(error).__name__}: {error}",
            )
        )

    if adapter is None:
        checks.append(
            _check(
                "model_supply_chain_lock",
                CHECK_BLOCKED,
                "Model supply-chain lock cannot be checked without valid settings.",
                schema=MODEL_SUPPLY_CHAIN_SCHEMA,
            )
        )
    else:
        selected_supply_chain = adapter.settings.model_supply_chain()
        supply_chain_mismatches = (
            adapter.settings.model_supply_chain_mismatches()
        )
        supply_chain_ok = not supply_chain_mismatches
        checks.append(
            _check(
                "model_supply_chain_lock",
                CHECK_PASSED if supply_chain_ok else CHECK_BLOCKED,
                (
                    "All seven external specialists match the release-locked "
                    "repository, immutable commit, and license metadata."
                    if supply_chain_ok
                    else "External model repository, commit, or license metadata "
                    "diverges from the release lock."
                ),
                schema=MODEL_SUPPLY_CHAIN_SCHEMA,
                selected_models=selected_supply_chain,
                expected_models={
                    role: dict(model)
                    for role, model in EXPECTED_MODEL_SUPPLY_CHAIN.items()
                },
                mismatches=list(supply_chain_mismatches),
                model_supply_chain_sha256=identity.get(
                    "model_supply_chain_sha256"
                )
                if identity is not None
                else None,
            )
        )

    try:
        versions = dict(
            selected_probe.dependency_versions(tuple(DEPENDENCY_MINIMUMS))
        )
        missing = sorted(
            distribution
            for distribution in DEPENDENCY_MINIMUMS
            if not versions.get(distribution)
        )
        outdated = [
            {
                "distribution": distribution,
                "actual": str(versions[distribution]),
                "minimum": minimum,
            }
            for distribution, minimum in DEPENDENCY_MINIMUMS.items()
            if versions.get(distribution)
            and not _version_at_least(str(versions[distribution]), minimum)
        ]
        outdated.sort(key=lambda item: str(item["distribution"]))
        dependency_status = (
            CHECK_PASSED if not missing and not outdated else CHECK_BLOCKED
        )
        checks.append(
            _check(
                "python_dependencies",
                dependency_status,
                (
                    "All Radeon runtime dependencies meet minimum versions."
                    if dependency_status == CHECK_PASSED
                    else "Required Radeon runtime dependencies are missing or too old."
                ),
                versions=versions,
                minimums=dict(DEPENDENCY_MINIMUMS),
                missing=missing,
                outdated=outdated,
            )
        )
    except Exception as error:
        checks.append(
            _check(
                "python_dependencies",
                CHECK_BLOCKED,
                "Radeon dependency inventory failed.",
                error=f"{type(error).__name__}: {error}",
            )
        )

    runtime: Mapping[str, object] = {}
    try:
        runtime = dict(selected_probe.runtime())
        vram = float(runtime.get("total_vram_gb", 0.0))
        runtime_ok = (
            runtime.get("cuda_available") is True
            and int(runtime.get("device_count", 0)) >= 1
            and bool(runtime.get("hip_version"))
            and math.isfinite(vram)
            and vram >= minimum_vram_gb
        )
        checks.append(
            _check(
                "rocm_runtime",
                CHECK_PASSED if runtime_ok else CHECK_BLOCKED,
                (
                    "ROCm/HIP Radeon runtime meets the execution floor."
                    if runtime_ok
                    else "ROCm/HIP Radeon runtime is unavailable or below the VRAM floor."
                ),
                **runtime,
                minimum_vram_gb=minimum_vram_gb,
            )
        )
    except Exception as error:
        checks.append(
            _check(
                "rocm_runtime",
                CHECK_BLOCKED,
                "ROCm/HIP Radeon runtime probe failed.",
                error=f"{type(error).__name__}: {error}",
                minimum_vram_gb=minimum_vram_gb,
            )
        )

    try:
        disk_root = (
            selected_manifest.parent
            if selected_manifest is not None
            else selected_settings.parent
        )
        free_disk_gb = float(selected_probe.free_disk_gb(disk_root))
        disk_ok = (
            math.isfinite(free_disk_gb)
            and free_disk_gb >= minimum_free_disk_gb
        )
        checks.append(
            _check(
                "free_disk",
                CHECK_PASSED if disk_ok else CHECK_BLOCKED,
                (
                    "Free disk meets the checkpoint and artifact floor."
                    if disk_ok
                    else "Free disk is below the checkpoint and artifact floor."
                ),
                path=str(disk_root),
                free_disk_gb=free_disk_gb,
                minimum_free_disk_gb=minimum_free_disk_gb,
            )
        )
    except Exception as error:
        checks.append(
            _check(
                "free_disk",
                CHECK_BLOCKED,
                "Free-disk probe failed.",
                error=f"{type(error).__name__}: {error}",
                minimum_free_disk_gb=minimum_free_disk_gb,
            )
        )

    try:
        ffmpeg_path = Path(selected_probe.ffmpeg_path()).resolve()
        ffmpeg_ok = ffmpeg_path.is_file() and os.access(ffmpeg_path, os.X_OK)
        checks.append(
            _check(
                "ffmpeg",
                CHECK_PASSED if ffmpeg_ok else CHECK_BLOCKED,
                (
                    "Executable FFmpeg is available for deterministic A/V muxing."
                    if ffmpeg_ok
                    else "FFmpeg is missing or not executable."
                ),
                path=str(ffmpeg_path),
            )
        )
    except Exception as error:
        checks.append(
            _check(
                "ffmpeg",
                CHECK_BLOCKED,
                "FFmpeg probe failed.",
                error=f"{type(error).__name__}: {error}",
            )
        )

    if adapter is None:
        checks.append(
            _check(
                "gemma_safe_lora",
                CHECK_BLOCKED,
                "Gemma paths and retention evidence cannot be checked without valid settings.",
                settings_path=str(selected_settings),
            )
        )
    else:
        base_path = Path(adapter.settings.gemma_base_model_path)
        lora_path = Path(adapter.settings.gemma_adapter_path)
        retention_path = Path(adapter.settings.gemma_retention_path)
        try:
            retention = validate_gemma_retention(retention_path)
            base_markers = (
                (base_path / "config.json").is_file()
                and any(base_path.glob("*.safetensors"))
            )
            lora_markers = (
                (lora_path / "adapter_config.json").is_file()
                and any(lora_path.glob("adapter_model*.safetensors"))
            )
            gemma_ok = (
                base_path.is_dir()
                and lora_path.is_dir()
                and base_markers
                and lora_markers
            )
            checks.append(
                _check(
                    "gemma_safe_lora",
                    CHECK_PASSED if gemma_ok else CHECK_BLOCKED,
                    (
                        "Local Gemma base, safe LoRA, and retention gate are complete."
                        if gemma_ok
                        else "Gemma model or LoRA weight markers are incomplete."
                    ),
                    base_model_path=str(base_path),
                    adapter_path=str(lora_path),
                    retention_path=str(retention_path),
                    base_model_markers_present=base_markers,
                    adapter_markers_present=lora_markers,
                    retention_sha256=sha256_file(retention_path),
                    pre_accuracy=retention["pre_accuracy"],
                    post_accuracy=retention["post_accuracy"],
                    minimum_post_accuracy=retention[
                        "minimum_post_accuracy"
                    ],
                    maximum_allowed_drop=retention[
                        "maximum_allowed_drop"
                    ],
                )
            )
        except Exception as error:
            checks.append(
                _check(
                    "gemma_safe_lora",
                    CHECK_BLOCKED,
                    "Gemma safe-LoRA retention gate failed.",
                    base_model_path=str(base_path),
                    adapter_path=str(lora_path),
                    retention_path=str(retention_path),
                    error=f"{type(error).__name__}: {error}",
                )
            )

    if adapter is None:
        checks.append(
            _check(
                "huggingface_model_cache",
                CHECK_BLOCKED,
                "Model-cache coverage cannot be checked without valid settings.",
                strict_cache=strict_cache,
            )
        )
    else:
        required_models = _model_revisions(adapter)
        cache_required = bool(strict_cache or adapter.settings.local_files_only)
        try:
            cached_model_revisions = {
                str(repo_id): {str(revision) for revision in revisions}
                for repo_id, revisions in (
                    selected_probe.cached_model_revisions().items()
                )
            }
            missing_models: list[dict[str, str]] = []
            cached_exact_models: list[dict[str, str]] = []
            for role, model in required_models.items():
                repo_id = model["repo_id"]
                revision = model["revision"]
                cached_revisions = cached_model_revisions.get(repo_id, set())
                if revision in cached_revisions:
                    cached_exact_models.append(
                        {
                            "role": role,
                            "repo_id": repo_id,
                            "revision": revision,
                        }
                    )
                else:
                    missing_models.append(
                        {
                            "role": role,
                            "repo_id": repo_id,
                            "revision": revision,
                            "reason": (
                                "repository_not_cached"
                                if repo_id not in cached_model_revisions
                                else "exact_revision_not_cached"
                            ),
                        }
                    )
            cache_status = (
                CHECK_PASSED
                if not missing_models
                else CHECK_BLOCKED
                if cache_required
                else CHECK_WARNING
            )
            checks.append(
                _check(
                    "huggingface_model_cache",
                    cache_status,
                    (
                        "All seven external specialist commits are cached exactly."
                        if cache_status == CHECK_PASSED
                        else "One or more exact specialist commits are not cached."
                    ),
                    required_models={
                        role: dict(model)
                        for role, model in required_models.items()
                    },
                    cached_exact_models=sorted(
                        cached_exact_models,
                        key=lambda item: item["role"],
                    ),
                    missing_models=sorted(
                        missing_models,
                        key=lambda item: item["role"],
                    ),
                    strict_cache=cache_required,
                    download_allowed=not adapter.settings.local_files_only,
                )
            )
        except Exception as error:
            checks.append(
                _check(
                    "huggingface_model_cache",
                    CHECK_BLOCKED if cache_required else CHECK_WARNING,
                    "Hugging Face cache inventory failed.",
                    strict_cache=cache_required,
                    error=f"{type(error).__name__}: {error}",
                )
            )

    if selected_manifest is None:
        checks.append(
            _check(
                "frozen_manifest",
                CHECK_WARNING,
                "No manifest was supplied; runtime readiness is not submission readiness.",
                required_product_count=30,
                required_case_count=450,
                required_video_case_count=30,
            )
        )
    else:
        try:
            manifest = load_frozen_manifest(selected_manifest)
            details = _validate_manifest_sources(
                selected_manifest,
                manifest,
            )
            checks.append(
                _check(
                    "frozen_manifest",
                    CHECK_PASSED,
                    "Frozen 30×3×5 manifest and every bound source byte are valid.",
                    path=str(selected_manifest),
                    **details,
                )
            )
        except Exception as error:
            checks.append(
                _check(
                    "frozen_manifest",
                    CHECK_BLOCKED,
                    "Frozen benchmark manifest or source-byte binding failed.",
                    path=str(selected_manifest),
                    error=f"{type(error).__name__}: {error}",
                )
            )

    blocker_count = sum(
        check.status == CHECK_BLOCKED for check in checks
    )
    warning_count = sum(
        check.status == CHECK_WARNING for check in checks
    )
    return {
        "schema": PREFLIGHT_SCHEMA,
        "version": PREFLIGHT_VERSION,
        "result": CHECK_PASSED if blocker_count == 0 else CHECK_BLOCKED,
        "passed": blocker_count == 0,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "settings_path": str(selected_settings),
        "manifest_path": (
            str(selected_manifest) if selected_manifest is not None else None
        ),
        "requirements": {
            "minimum_vram_gb": minimum_vram_gb,
            "minimum_free_disk_gb": minimum_free_disk_gb,
            "strict_cache": strict_cache,
            "external_specialist_count": 7,
            "phase_count": 9,
        },
        "adapter_identity": dict(identity) if identity is not None else None,
        "runtime": dict(runtime),
        "checks": [check.to_dict() for check in checks],
    }


def write_preflight_report(
    report: Mapping[str, object],
    output_path: str | Path,
) -> None:
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                report,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
