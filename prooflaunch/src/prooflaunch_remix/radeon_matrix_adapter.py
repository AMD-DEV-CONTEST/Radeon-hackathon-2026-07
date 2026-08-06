from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import re
import subprocess
import wave
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Mapping

from PIL import Image, ImageDraw, ImageStat

from .benchmark_runner import (
    ArtifactOutput,
    BenchmarkPhase,
    PermanentActivityError,
    StillAudit,
    VideoAudit,
)
from .competition_benchmark import BenchmarkCase, ProductSpec
from .files import sha256_file
from .media_quality import (
    AudioVideoAlignmentGate,
    EncodedVideoIdentityGate,
    SemanticEvent,
)
from .multimodal_ingest import (
    MediaArtifact,
    MediaKind,
    MediaSource,
    MultimodalIngestor,
    RightsStatus,
)
from .multimodal_models import (
    LocalCLAPScorer,
    LocalGroundingDINO,
    LocalQwen3VLAnalyzer,
    LocalSAM2VideoTracker,
)
from .studio import _font, _wrap
from .video_generation import IdentityLockedVideoComposer
from .visual_semantics import HuggingFaceSigLIP2Scorer


SETTINGS_SCHEMA = "ProofLaunchRadeonMatrixAdapterSettingsV2"
MODEL_SUPPLY_CHAIN_SCHEMA = "ProofLaunchModelSupplyChainV1"
ADAPTER_VERSION = "0.9.0"
VALID_EMOTIONS = ("sadness", "joy", "love", "anger", "fear", "surprise")
RATIO_SIZES = {
    "1:1": (1024, 1024),
    "4:5": (896, 1120),
    "9:16": (768, 1344),
}
MODEL_FIELD_NAMES: Mapping[str, tuple[str, str, str]] = {
    "qwen": (
        "qwen_model_id",
        "qwen_model_revision",
        "qwen_model_license",
    ),
    "grounding_dino": (
        "grounding_dino_model_id",
        "grounding_dino_model_revision",
        "grounding_dino_model_license",
    ),
    "image": (
        "image_model_id",
        "image_model_revision",
        "image_model_license",
    ),
    "siglip": (
        "siglip_model_id",
        "siglip_model_revision",
        "siglip_model_license",
    ),
    "video": (
        "ltx_model_id",
        "ltx_model_revision",
        "ltx_model_license",
    ),
    "sam2": (
        "sam2_model_id",
        "sam2_model_revision",
        "sam2_model_license",
    ),
    "clap": (
        "clap_model_id",
        "clap_model_revision",
        "clap_model_license",
    ),
}
EXPECTED_MODEL_SUPPLY_CHAIN: Mapping[str, Mapping[str, str]] = {
    "qwen": {
        "repo_id": "Qwen/Qwen3-VL-2B-Instruct",
        "revision": "89644892e4d85e24eaac8bacfd4f463576704203",
        "license": "apache-2.0",
    },
    "grounding_dino": {
        "repo_id": "IDEA-Research/grounding-dino-tiny",
        "revision": "a2bb814dd30d776dcf7e30523b00659f4f141c71",
        "license": "apache-2.0",
    },
    "image": {
        "repo_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "revision": "462165984030d82259a11f4367a4eed129e94a7b",
        "license": "openrail++",
    },
    "siglip": {
        "repo_id": "google/siglip2-base-patch16-224",
        "revision": "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2",
        "license": "apache-2.0",
    },
    "video": {
        "repo_id": "Lightricks/LTX-Video",
        "revision": "8984fa25007f376c1a299016d0957a37a2f797bb",
        "license": "other",
    },
    "sam2": {
        "repo_id": "facebook/sam2.1-hiera-small",
        "revision": "ee5bba1d82bb8749febdf90f45e84b687142ba03",
        "license": "apache-2.0",
    },
    "clap": {
        "repo_id": "laion/clap-htsat-fused",
        "revision": "365dea6ef167def6676140ed93bbc43f84dabb28",
        "license": "apache-2.0",
    },
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _required_string(value: Mapping[str, object], field: str) -> str:
    selected = value.get(field)
    if not isinstance(selected, str) or not selected.strip():
        raise PermanentActivityError(f"adapter setting {field} must be non-empty")
    return selected.strip()


def _optional_string(value: Mapping[str, object], field: str) -> str | None:
    selected = value.get(field)
    if selected is None:
        return None
    if not isinstance(selected, str) or not selected.strip():
        raise PermanentActivityError(
            f"adapter setting {field} must be null or non-empty"
        )
    return selected.strip()


def _required_revision(value: Mapping[str, object], field: str) -> str:
    selected = _required_string(value, field)
    if re.fullmatch(r"[0-9a-f]{40}", selected) is None:
        raise PermanentActivityError(
            f"adapter setting {field} must be an immutable 40-character "
            "lowercase Git commit"
        )
    return selected


def _integer(
    value: Mapping[str, object],
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    selected = value.get(field)
    if (
        isinstance(selected, bool)
        or not isinstance(selected, int)
        or not minimum <= selected <= maximum
    ):
        raise PermanentActivityError(
            f"adapter setting {field} must be between {minimum} and {maximum}"
        )
    return selected


def _number(
    value: Mapping[str, object],
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    selected = value.get(field)
    if isinstance(selected, bool) or not isinstance(selected, (int, float)):
        raise PermanentActivityError(f"adapter setting {field} must be numeric")
    normalized = float(selected)
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise PermanentActivityError(
            f"adapter setting {field} must be between {minimum} and {maximum}"
        )
    return normalized


@dataclass(frozen=True)
class RadeonMatrixAdapterSettings:
    qwen_model_id: str
    qwen_model_revision: str
    qwen_model_license: str
    grounding_dino_model_id: str
    grounding_dino_model_revision: str
    grounding_dino_model_license: str
    gemma_base_model_path: str
    gemma_adapter_path: str
    gemma_retention_path: str
    image_model_id: str
    image_model_revision: str
    image_model_license: str
    siglip_model_id: str
    siglip_model_revision: str
    siglip_model_license: str
    ltx_model_id: str
    ltx_model_revision: str
    ltx_model_license: str
    sam2_model_id: str
    sam2_model_revision: str
    sam2_model_license: str
    clap_model_id: str
    clap_model_revision: str
    clap_model_license: str
    device: str
    local_files_only: bool
    still_steps: int
    still_candidates: int
    guidance_scale: float
    video_steps: int
    video_frames: int
    video_fps: int
    clap_minimum_probability: float
    encoded_identity_tolerance: float
    schema: str = SETTINGS_SCHEMA

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
    ) -> "RadeonMatrixAdapterSettings":
        if value.get("schema") != SETTINGS_SCHEMA:
            raise PermanentActivityError("unsupported Radeon adapter settings schema")
        local_only = value.get("local_files_only")
        if not isinstance(local_only, bool):
            raise PermanentActivityError(
                "adapter setting local_files_only must be a boolean"
            )
        video_frames = _integer(
            value,
            "video_frames",
            minimum=9,
            maximum=257,
        )
        if (video_frames - 1) % 8:
            raise PermanentActivityError(
                "adapter setting video_frames must equal 8n+1"
            )
        device = _required_string(value, "device")
        if device != "cuda":
            raise PermanentActivityError(
                "the competition adapter requires ROCm through torch.cuda"
            )
        return cls(
            qwen_model_id=_required_string(value, "qwen_model_id"),
            qwen_model_revision=_required_revision(
                value,
                "qwen_model_revision",
            ),
            qwen_model_license=_required_string(value, "qwen_model_license"),
            grounding_dino_model_id=_required_string(
                value,
                "grounding_dino_model_id",
            ),
            grounding_dino_model_revision=_required_revision(
                value,
                "grounding_dino_model_revision",
            ),
            grounding_dino_model_license=_required_string(
                value,
                "grounding_dino_model_license",
            ),
            gemma_base_model_path=_required_string(
                value,
                "gemma_base_model_path",
            ),
            gemma_adapter_path=_required_string(value, "gemma_adapter_path"),
            gemma_retention_path=_required_string(
                value,
                "gemma_retention_path",
            ),
            image_model_id=_required_string(value, "image_model_id"),
            image_model_revision=_required_revision(
                value,
                "image_model_revision",
            ),
            image_model_license=_required_string(
                value,
                "image_model_license",
            ),
            siglip_model_id=_required_string(value, "siglip_model_id"),
            siglip_model_revision=_required_revision(
                value,
                "siglip_model_revision",
            ),
            siglip_model_license=_required_string(
                value,
                "siglip_model_license",
            ),
            ltx_model_id=_required_string(value, "ltx_model_id"),
            ltx_model_revision=_required_revision(
                value,
                "ltx_model_revision",
            ),
            ltx_model_license=_required_string(value, "ltx_model_license"),
            sam2_model_id=_required_string(value, "sam2_model_id"),
            sam2_model_revision=_required_revision(
                value,
                "sam2_model_revision",
            ),
            sam2_model_license=_required_string(value, "sam2_model_license"),
            clap_model_id=_required_string(value, "clap_model_id"),
            clap_model_revision=_required_revision(
                value,
                "clap_model_revision",
            ),
            clap_model_license=_required_string(value, "clap_model_license"),
            device=device,
            local_files_only=local_only,
            still_steps=_integer(
                value,
                "still_steps",
                minimum=4,
                maximum=100,
            ),
            still_candidates=_integer(
                value,
                "still_candidates",
                minimum=1,
                maximum=4,
            ),
            guidance_scale=_number(
                value,
                "guidance_scale",
                minimum=0.0,
                maximum=20.0,
            ),
            video_steps=_integer(
                value,
                "video_steps",
                minimum=4,
                maximum=80,
            ),
            video_frames=video_frames,
            video_fps=_integer(
                value,
                "video_fps",
                minimum=8,
                maximum=60,
            ),
            clap_minimum_probability=_number(
                value,
                "clap_minimum_probability",
                minimum=0.0,
                maximum=1.0,
            ),
            encoded_identity_tolerance=_number(
                value,
                "encoded_identity_tolerance",
                minimum=0.0,
                maximum=0.20,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def model_supply_chain(self) -> dict[str, dict[str, str]]:
        return {
            role: {
                "repo_id": str(getattr(self, fields[0])),
                "revision": str(getattr(self, fields[1])),
                "license": str(getattr(self, fields[2])),
            }
            for role, fields in MODEL_FIELD_NAMES.items()
        }

    def model_ref(self, role: str) -> str:
        try:
            selected = self.model_supply_chain()[role]
        except KeyError as error:
            raise PermanentActivityError(
                f"unknown external model role: {role}"
            ) from error
        return f"{selected['repo_id']}@{selected['revision']}"

    def model_supply_chain_mismatches(self) -> tuple[dict[str, object], ...]:
        actual = self.model_supply_chain()
        mismatches: list[dict[str, object]] = []
        for role, expected in EXPECTED_MODEL_SUPPLY_CHAIN.items():
            selected = actual[role]
            differences = {
                field: {
                    "expected": expected[field],
                    "actual": selected[field],
                }
                for field in ("repo_id", "revision", "license")
                if selected[field] != expected[field]
            }
            if differences:
                mismatches.append(
                    {
                        "role": role,
                        "differences": differences,
                    }
                )
        return tuple(mismatches)


def load_radeon_adapter_settings(
    path: str | Path,
) -> tuple[RadeonMatrixAdapterSettings, str]:
    settings_path = Path(path).expanduser().resolve()
    try:
        raw = settings_path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise PermanentActivityError(
            f"cannot read Radeon adapter settings {settings_path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise PermanentActivityError(
            "Radeon adapter settings must contain one JSON object"
        )
    settings = RadeonMatrixAdapterSettings.from_mapping(value)
    return settings, hashlib.sha256(raw).hexdigest()


def resolve_radeon_adapter_paths(
    settings: RadeonMatrixAdapterSettings,
    settings_path: str | Path,
) -> RadeonMatrixAdapterSettings:
    resolved_settings_path = Path(settings_path).expanduser().resolve()
    project_root = resolved_settings_path.parent.parent

    def local_path(value: str) -> str:
        candidate = Path(value).expanduser()
        return str(
            candidate.resolve()
            if candidate.is_absolute()
            else (project_root / candidate).resolve()
        )

    return replace(
        settings,
        gemma_base_model_path=local_path(settings.gemma_base_model_path),
        gemma_adapter_path=local_path(settings.gemma_adapter_path),
        gemma_retention_path=local_path(settings.gemma_retention_path),
    )


def validate_gemma_retention(path: str | Path) -> Mapping[str, object]:
    retention_path = Path(path).expanduser().resolve()
    try:
        retention = json.loads(retention_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PermanentActivityError(
            f"cannot read Gemma retention evidence: {error}"
        ) from error
    if not isinstance(retention, dict):
        raise PermanentActivityError(
            "Gemma retention evidence must be an object"
        )
    required = (
        "pre_accuracy",
        "post_accuracy",
        "minimum_post_accuracy",
        "maximum_allowed_drop",
    )
    normalized: dict[str, float] = {}
    try:
        for field in required:
            number = float(retention[field])
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise ValueError(field)
            normalized[field] = number
    except (KeyError, TypeError, ValueError) as error:
        raise PermanentActivityError(
            "Gemma retention evidence is incomplete or out of range"
        ) from error
    passed = (
        normalized["post_accuracy"] >= normalized["minimum_post_accuracy"]
        and normalized["pre_accuracy"] - normalized["post_accuracy"]
        <= normalized["maximum_allowed_drop"]
    )
    if not passed:
        raise PermanentActivityError(
            "Gemma multimodal-retention evidence failed its frozen gate"
        )
    return {
        **retention,
        "pre_accuracy": normalized["pre_accuracy"],
        "post_accuracy": normalized["post_accuracy"],
        "minimum_post_accuracy": normalized["minimum_post_accuracy"],
        "maximum_allowed_drop": normalized["maximum_allowed_drop"],
    }


def _media_artifact(value: Mapping[str, object]) -> MediaArtifact:
    try:
        return MediaArtifact(
            id=str(value["id"]),
            path=str(value["path"]),
            role=str(value["role"]),
            kind=MediaKind(str(value["kind"])),
            mime_type=str(value["mime_type"]),
            sha256=str(value["sha256"]),
            byte_size=int(value["byte_size"]),
            rights=RightsStatus(str(value["rights"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PermanentActivityError(
            f"prepared product artifact is invalid: {error}"
        ) from error


def _release_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _reset_peak_memory() -> None:
    import torch

    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()


def _peak_vram_gb() -> float:
    import torch

    torch.cuda.synchronize()
    return torch.cuda.max_memory_allocated() / (1024**3)


def _json_file(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class RadeonLocalCompetitionAdapter:
    """Real local-model adapter for the nine-stage competition workflow."""

    def __init__(
        self,
        settings: RadeonMatrixAdapterSettings,
        *,
        settings_sha256: str | None = None,
    ) -> None:
        self.settings = settings
        self.settings_sha256 = settings_sha256 or _sha256_json(settings.to_dict())
        self.active_phase: BenchmarkPhase | None = None
        self.qwen: LocalQwen3VLAnalyzer | None = None
        self.dino: LocalGroundingDINO | None = None
        self.gemma_tokenizer = None
        self.gemma_model = None
        self.image_pipeline = None
        self.siglip: HuggingFaceSigLIP2Scorer | None = None
        self.ltx_pipeline = None
        self.sam2: LocalSAM2VideoTracker | None = None
        self.clap: LocalCLAPScorer | None = None
        self.gemma_retention: Mapping[str, object] | None = None

    @classmethod
    def from_settings_file(
        cls,
        path: str | Path,
    ) -> "RadeonLocalCompetitionAdapter":
        settings_path = Path(path).expanduser().resolve()
        settings, digest = load_radeon_adapter_settings(settings_path)
        settings = resolve_radeon_adapter_paths(
            settings,
            settings_path,
        )
        return cls(settings, settings_sha256=digest)

    def identity(self) -> Mapping[str, object]:
        model_supply_chain = self.settings.model_supply_chain()
        return {
            "adapter_id": "prooflaunch-radeon-local-multimodal",
            "version": ADAPTER_VERSION,
            "settings_sha256": self.settings_sha256,
            "system_kind": "prooflaunch",
            "uses_closed_online_api": False,
            "model_supply_chain_schema": MODEL_SUPPLY_CHAIN_SCHEMA,
            "model_supply_chain_sha256": _sha256_json(
                {
                    "schema": MODEL_SUPPLY_CHAIN_SCHEMA,
                    "models": model_supply_chain,
                }
            ),
            "model_supply_chain": model_supply_chain,
            "model_refs": {
                "qwen": self.settings.model_ref("qwen"),
                "grounding_dino": self.settings.model_ref("grounding_dino"),
                "gemma": (
                    f"{self.settings.gemma_base_model_path}"
                    f"+{self.settings.gemma_adapter_path}"
                ),
                "image": self.settings.model_ref("image"),
                "siglip": self.settings.model_ref("siglip"),
                "video": self.settings.model_ref("video"),
                "sam2": self.settings.model_ref("sam2"),
                "clap": self.settings.model_ref("clap"),
            },
        }

    @staticmethod
    def _require_radeon() -> Mapping[str, object]:
        try:
            import torch
        except ImportError as error:
            raise PermanentActivityError("PyTorch is not installed") from error
        if not torch.cuda.is_available():
            raise PermanentActivityError("ROCm Radeon device is unavailable")
        hip_version = getattr(torch.version, "hip", None)
        if not hip_version:
            raise PermanentActivityError(
                "PyTorch CUDA surface is not backed by ROCm/HIP"
            )
        return {
            "torch_version": torch.__version__,
            "hip_version": hip_version,
            "device_name": torch.cuda.get_device_name(0),
            "total_vram_gb": (
                torch.cuda.get_device_properties(0).total_memory / (1024**3)
            ),
        }

    def load_phase(self, phase: BenchmarkPhase) -> Mapping[str, object]:
        if self.active_phase is not None:
            raise PermanentActivityError(
                f"cannot load {phase.value}; {self.active_phase.value} is resident"
            )
        supply_chain_mismatches = self.settings.model_supply_chain_mismatches()
        if supply_chain_mismatches:
            raise PermanentActivityError(
                "external model supply chain diverges from the release lock: "
                f"{json.dumps(supply_chain_mismatches, sort_keys=True)}"
            )
        runtime = (
            {"model_ref": "Pillow/local-signature-preflight"}
            if phase == BenchmarkPhase.PREPARE_PRODUCTS
            else dict(self._require_radeon())
        )
        self.active_phase = phase
        try:
            model_ref = self._load_phase_model(phase)
        except Exception:
            self.active_phase = None
            self._release_all()
            raise
        return {
            **runtime,
            "phase": phase.value,
            "model_ref": model_ref,
            "single_heavy_model_resident": True,
            "closed_online_api": False,
        }

    def _load_phase_model(self, phase: BenchmarkPhase) -> str:
        if phase == BenchmarkPhase.PREPARE_PRODUCTS:
            return "Pillow/local-signature-preflight"
        if phase == BenchmarkPhase.UNDERSTAND_PRODUCTS:
            self.qwen = LocalQwen3VLAnalyzer(
                model_id=self.settings.qwen_model_id,
                revision=self.settings.qwen_model_revision,
                local_files_only=self.settings.local_files_only,
                max_new_tokens=512,
            )
            self.qwen.load()
            return self.settings.model_ref("qwen")
        if phase == BenchmarkPhase.GROUND_PRODUCTS:
            self.dino = LocalGroundingDINO(
                model_id=self.settings.grounding_dino_model_id,
                revision=self.settings.grounding_dino_model_revision,
                local_files_only=self.settings.local_files_only,
                box_threshold=0.30,
                text_threshold=0.25,
            )
            self.dino.load()
            return self.settings.model_ref("grounding_dino")
        if phase == BenchmarkPhase.PLAN_PRODUCTS:
            self._load_gemma()
            return (
                f"{self.settings.gemma_base_model_path}"
                f"+{self.settings.gemma_adapter_path}"
            )
        if phase == BenchmarkPhase.GENERATE_STILLS:
            import torch
            from diffusers import AutoPipelineForText2Image

            self.image_pipeline = AutoPipelineForText2Image.from_pretrained(
                self.settings.image_model_id,
                revision=self.settings.image_model_revision,
                torch_dtype=torch.float16,
                use_safetensors=True,
                local_files_only=self.settings.local_files_only,
            ).to(self.settings.device)
            return self.settings.model_ref("image")
        if phase == BenchmarkPhase.AUDIT_STILLS:
            self.siglip = HuggingFaceSigLIP2Scorer(
                model_id=self.settings.siglip_model_id,
                revision=self.settings.siglip_model_revision,
                local_files_only=self.settings.local_files_only,
                device=self.settings.device,
                minimum_positive_probability=0.34,
                minimum_margin=0.05,
            )
            self.siglip.load()
            return self.settings.model_ref("siglip")
        if phase == BenchmarkPhase.GENERATE_VIDEOS:
            import torch
            from diffusers import LTXImageToVideoPipeline

            self.ltx_pipeline = LTXImageToVideoPipeline.from_pretrained(
                self.settings.ltx_model_id,
                revision=self.settings.ltx_model_revision,
                torch_dtype=torch.bfloat16,
                local_files_only=self.settings.local_files_only,
            ).to(self.settings.device)
            if hasattr(self.ltx_pipeline, "vae"):
                self.ltx_pipeline.vae.enable_tiling()
            return self.settings.model_ref("video")
        if phase == BenchmarkPhase.TRACK_VIDEOS:
            self.sam2 = LocalSAM2VideoTracker(
                model_id=self.settings.sam2_model_id,
                revision=self.settings.sam2_model_revision,
                local_files_only=self.settings.local_files_only,
                minimum_frame_coverage=0.95,
                minimum_nonempty_mask_rate=0.95,
            )
            self.sam2.load()
            return self.settings.model_ref("sam2")
        self.clap = LocalCLAPScorer(
            model_id=self.settings.clap_model_id,
            revision=self.settings.clap_model_revision,
            local_files_only=self.settings.local_files_only,
            minimum_probability=self.settings.clap_minimum_probability,
        )
        self.clap.load()
        return self.settings.model_ref("clap")

    def _load_gemma(self) -> None:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        base_path = Path(self.settings.gemma_base_model_path)
        adapter_path = Path(self.settings.gemma_adapter_path)
        retention_path = Path(self.settings.gemma_retention_path)
        if not base_path.is_dir() or not adapter_path.is_dir():
            raise PermanentActivityError(
                "local Gemma base model or safe LoRA adapter is missing"
            )
        retention = validate_gemma_retention(retention_path)
        self.gemma_retention = retention
        self.gemma_tokenizer = AutoTokenizer.from_pretrained(
            base_path,
            use_fast=True,
            trust_remote_code=True,
            local_files_only=True,
        )
        base = AutoModelForCausalLM.from_pretrained(
            base_path,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
            local_files_only=True,
        ).to(self.settings.device)
        self.gemma_model = PeftModel.from_pretrained(
            base,
            adapter_path,
            local_files_only=True,
        ).to(self.settings.device)
        self.gemma_model.eval()

    def release_phase(self, phase: BenchmarkPhase) -> None:
        if self.active_phase != phase:
            raise PermanentActivityError(
                f"cannot release {phase.value}; it is not the active phase"
            )
        self._release_all()
        self.active_phase = None

    def _release_all(self) -> None:
        for specialist in (self.qwen, self.dino, self.siglip, self.sam2, self.clap):
            if specialist is not None and hasattr(specialist, "release"):
                specialist.release()
        self.qwen = None
        self.dino = None
        self.siglip = None
        self.sam2 = None
        self.clap = None
        self.gemma_model = None
        self.gemma_tokenizer = None
        self.gemma_retention = None
        self.image_pipeline = None
        self.ltx_pipeline = None
        _release_memory()

    @staticmethod
    def _require_phase(expected: BenchmarkPhase, actual: BenchmarkPhase | None) -> None:
        if actual != expected:
            raise PermanentActivityError(
                f"{expected.value} activity invoked while {actual} is active"
            )

    def prepare_product(
        self,
        product: ProductSpec,
        source_path: Path,
    ) -> Mapping[str, object]:
        self._require_phase(BenchmarkPhase.PREPARE_PRODUCTS, self.active_phase)
        rights = (
            RightsStatus.OWNED
            if product.rights == "owned"
            else RightsStatus.LICENSED
        )
        artifact = MultimodalIngestor().ingest(
            (
                MediaSource(
                    str(source_path),
                    "product_identity",
                    rights,
                    MediaKind.IMAGE,
                ),
            )
        )[0]
        with Image.open(source_path) as image:
            image.load()
            width, height = image.size
            mode = image.mode
            alpha_extrema = (
                image.getchannel("A").getextrema()
                if "A" in image.getbands()
                else (255, 255)
            )
        return {
            "artifact": artifact.serializable(),
            "width": width,
            "height": height,
            "mode": mode,
            "has_transparency": alpha_extrema[0] < 255,
            "rights": product.rights,
        }

    def understand_product(
        self,
        product: ProductSpec,
        prepared: Mapping[str, object],
    ) -> Mapping[str, object]:
        self._require_phase(BenchmarkPhase.UNDERSTAND_PRODUCTS, self.active_phase)
        if self.qwen is None:
            raise PermanentActivityError("Qwen3-VL is not loaded")
        artifact_value = prepared.get("artifact")
        if not isinstance(artifact_value, Mapping):
            raise PermanentActivityError("prepared product lacks its media artifact")
        result = self.qwen.analyze(
            (_media_artifact(artifact_value),),
            mission_prompt=(
                "Describe visible product identity, materials, colors, shape, "
                "logo or text, and safe composition constraints. Do not infer "
                "performance claims or facts that are not visible."
            ),
        )
        return {
            "summary": result.summary,
            "observations": [asdict(item) for item in result.observations],
            "model_ref": result.model_ref,
        }

    def ground_product(
        self,
        product: ProductSpec,
        prepared: Mapping[str, object],
        understanding: Mapping[str, object],
    ) -> Mapping[str, object]:
        del product, understanding
        self._require_phase(BenchmarkPhase.GROUND_PRODUCTS, self.active_phase)
        if self.dino is None:
            raise PermanentActivityError("GroundingDINO is not loaded")
        artifact_value = prepared.get("artifact")
        if not isinstance(artifact_value, Mapping):
            raise PermanentActivityError("prepared product lacks its media artifact")
        artifact = _media_artifact(artifact_value)
        detections = self.dino.detect(
            artifact,
            text_labels=("product", "electronic device", "consumer product"),
        )
        selected = max(detections, key=lambda item: item.score)
        return {
            "selected": asdict(selected),
            "detections": [asdict(item) for item in detections],
            "source_size": [prepared["width"], prepared["height"]],
            "source_artifact_id": artifact.id,
            "model_ref": self.settings.model_ref("grounding_dino"),
        }

    def _predict_emotion(self, text: str) -> str:
        import torch

        if self.gemma_model is None or self.gemma_tokenizer is None:
            raise PermanentActivityError("Gemma emotion model is not loaded")
        messages = [
            {
                "role": "system",
                "content": (
                    "Answer with exactly one label: sadness, joy, love, anger, "
                    "fear, or surprise."
                ),
            },
            {
                "role": "user",
                "content": f"Classify the dominant campaign emotion:\n\n{text}",
            },
        ]
        inputs = self.gemma_tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs = {
            key: item.to(self.settings.device) for key, item in inputs.items()
        }
        input_length = inputs["input_ids"].shape[-1]
        with torch.inference_mode():
            output = self.gemma_model.generate(
                **inputs,
                max_new_tokens=4,
                do_sample=False,
                pad_token_id=self.gemma_tokenizer.pad_token_id,
                eos_token_id=self.gemma_tokenizer.eos_token_id,
            )
        decoded = self.gemma_tokenizer.decode(
            output[0][input_length:],
            skip_special_tokens=True,
        ).strip().lower()
        match = re.search(
            r"\b(sadness|joy|love|anger|fear|surprise)\b",
            decoded,
        )
        return match.group(1) if match else "invalid"

    def plan_product(
        self,
        product: ProductSpec,
        prepared: Mapping[str, object],
        understanding: Mapping[str, object],
        grounding: Mapping[str, object],
    ) -> Mapping[str, object]:
        del grounding
        self._require_phase(BenchmarkPhase.PLAN_PRODUCTS, self.active_phase)
        artifact_value = prepared.get("artifact")
        if not isinstance(artifact_value, Mapping):
            raise PermanentActivityError("prepared product lacks its media artifact")
        product_artifact = _media_artifact(artifact_value)
        if product_artifact.sha256 != product.input_sha256:
            raise PermanentActivityError(
                "prepared product hash diverges from the frozen manifest"
            )
        summary = str(understanding.get("summary", "")).strip()
        predicted = self._predict_emotion(summary)
        target_emotion = predicted if predicted in VALID_EMOTIONS else "joy"
        display_name = " ".join(
            part for part in re.split(r"[-_]+", product.product_id) if part
        ).title()
        headline = f"{display_name} — a bright, evidence-led launch."
        headline_prediction = self._predict_emotion(headline)
        emotion_match = headline_prediction == target_emotion
        return {
            "product_name": display_name,
            "headline": headline,
            "visual_direction": (
                "premium studio lighting, clean depth, restrained motion, "
                f"{target_emotion} atmosphere, no text, no logo, no extra product"
            ),
            "target_emotion": target_emotion,
            "summary_emotion": predicted,
            "headline_emotion": headline_prediction,
            "emotion_match": emotion_match,
            "product_source_path": product_artifact.path,
            "product_source_sha256": product_artifact.sha256,
            "model_ref": (
                f"{self.settings.gemma_base_model_path}"
                f"+{self.settings.gemma_adapter_path}"
            ),
            "retention_evidence_sha256": sha256_file(
                self.settings.gemma_retention_path
            ),
        }

    @staticmethod
    def _background_score(image: Image.Image) -> float:
        luminance = image.convert("L").resize((128, 128), Image.Resampling.LANCZOS)
        stats = ImageStat.Stat(luminance)
        mean = float(stats.mean[0])
        standard_deviation = float(stats.stddev[0])
        exposure_penalty = abs(mean - 118.0) * 0.35
        return standard_deviation - exposure_penalty

    @staticmethod
    def _compose_still(
        *,
        background: Image.Image,
        product_path: Path,
        headline: str,
    ) -> tuple[Image.Image, Image.Image, tuple[int, int, int, int]]:
        canvas = background.convert("RGBA")
        width, height = canvas.size
        with Image.open(product_path) as source_product:
            product = source_product.convert("RGBA")
        product.thumbnail(
            (round(width * 0.54), round(height * 0.46)),
            Image.Resampling.LANCZOS,
        )
        product_x = round((width - product.width) / 2)
        product_y = round(height * 0.40)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.alpha_composite(product, (product_x, product_y))
        composed = Image.alpha_composite(canvas, layer)
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        panel = (
            round(width * 0.06),
            round(height * 0.06),
            round(width * 0.94),
            round(height * 0.28),
        )
        draw.rounded_rectangle(
            panel,
            radius=max(12, width // 40),
            fill=(8, 12, 24, 224),
        )
        font_size = max(24, round(width * 0.050))
        font = _font(font_size, bold=True)
        wrapped = _wrap(
            draw,
            headline,
            font,
            panel[2] - panel[0] - round(width * 0.08),
        )
        draw.multiline_text(
            (panel[0] + round(width * 0.04), panel[1] + round(height * 0.035)),
            wrapped,
            fill=(255, 255, 255, 255),
            font=font,
            spacing=max(5, font_size // 4),
        )
        composed = Image.alpha_composite(composed, overlay).convert("RGB")
        return (
            composed,
            layer,
            (
                product_x,
                product_y,
                product_x + product.width,
                product_y + product.height,
            ),
        )

    def generate_still(
        self,
        case: BenchmarkCase,
        product: ProductSpec,
        understanding: Mapping[str, object],
        grounding: Mapping[str, object],
        plan: Mapping[str, object],
        output_path: Path,
    ) -> ArtifactOutput:
        del understanding, grounding
        self._require_phase(BenchmarkPhase.GENERATE_STILLS, self.active_phase)
        if self.image_pipeline is None:
            raise PermanentActivityError("SDXL pipeline is not loaded")
        import torch

        width, height = RATIO_SIZES[case.aspect_ratio]
        prompt = (
            f"{plan['visual_direction']}. Premium campaign background for "
            f"{plan['product_name']}. Leave a clean central product stage. "
            "Background only, no product, no words, no watermark."
        )
        product_path = self._product_source_from_plan(plan)
        if sha256_file(product_path) != product.input_sha256:
            raise PermanentActivityError(
                "creative plan product source diverges from the frozen manifest"
            )
        _reset_peak_memory()
        candidates: list[tuple[float, int, Image.Image]] = []
        for position in range(self.settings.still_candidates):
            candidate_seed = case.seed + position * 10_000_019
            generator = torch.Generator(device=self.settings.device).manual_seed(
                candidate_seed
            )
            result = self.image_pipeline(
                prompt=prompt,
                negative_prompt=(
                    "text, letters, logo, watermark, product, duplicate object, "
                    "warped geometry, low quality"
                ),
                width=width,
                height=height,
                num_inference_steps=self.settings.still_steps,
                guidance_scale=self.settings.guidance_scale,
                generator=generator,
            )
            if not getattr(result, "images", None):
                raise PermanentActivityError("SDXL returned no image")
            image = result.images[0].convert("RGB")
            candidates.append(
                (self._background_score(image), candidate_seed, image)
            )
        selected_score, selected_seed, selected_background = max(
            candidates,
            key=lambda item: item[0],
        )
        composed, product_layer, product_box = self._compose_still(
            background=selected_background,
            product_path=product_path,
            headline=str(plan["headline"]),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        composed.save(output_path, format="PNG", optimize=False)
        layer_path = output_path.with_name(
            f"{output_path.stem}.product-layer.png"
        )
        background_path = output_path.with_name(
            f"{output_path.stem}.background.png"
        )
        candidate_path = output_path.with_name(
            f"{output_path.stem}.candidates.json"
        )
        product_layer.save(layer_path, format="PNG", optimize=False)
        selected_background.save(background_path, format="PNG", optimize=False)
        _json_file(
            candidate_path,
            {
                "schema": "ProofLaunchStillCandidateSelectionV1",
                "case_id": case.case_id,
                "selected_seed": selected_seed,
                "selected_score": selected_score,
                "candidates": [
                    {"score": score, "seed": seed}
                    for score, seed, _ in candidates
                ],
            },
        )
        return ArtifactOutput(
            path=output_path,
            model_ref=self.settings.model_ref("image"),
            peak_vram_gb=_peak_vram_gb(),
            metadata={
                "case_id": case.case_id,
                "seed": case.seed,
                "selected_seed": selected_seed,
                "candidate_count": len(candidates),
                "prompt": prompt,
                "product_source_path": str(product_path),
                "product_source_sha256": product.input_sha256,
                "product_layer_path": str(layer_path),
                "product_layer_sha256": sha256_file(layer_path),
                "product_box_xyxy": list(product_box),
                "canvas_size": [width, height],
                "headline": plan["headline"],
                "target_emotion": plan["target_emotion"],
            },
            sidecars=(layer_path, background_path, candidate_path),
        )

    @staticmethod
    def _product_source_from_plan(plan: Mapping[str, object]) -> Path:
        source = plan.get("product_source_path")
        if not isinstance(source, str) or not source:
            raise PermanentActivityError(
                "creative plan is not bound to the product source path"
            )
        path = Path(source)
        if not path.is_file():
            raise PermanentActivityError("creative plan product source is missing")
        return path

    def audit_still(
        self,
        case: BenchmarkCase,
        product: ProductSpec,
        understanding: Mapping[str, object],
        grounding: Mapping[str, object],
        plan: Mapping[str, object],
        still: ArtifactOutput,
    ) -> StillAudit:
        del case
        self._require_phase(BenchmarkPhase.AUDIT_STILLS, self.active_phase)
        if self.siglip is None:
            raise PermanentActivityError("SigLIP2 is not loaded")
        _reset_peak_memory()
        layer_path = Path(str(still.metadata.get("product_layer_path", "")))
        source_path = Path(str(still.metadata.get("product_source_path", "")))
        source_hash_ok = (
            source_path.is_file()
            and sha256_file(source_path) == product.input_sha256
        )
        layer_hash_ok = (
            layer_path.is_file()
            and sha256_file(layer_path)
            == still.metadata.get("product_layer_sha256")
        )
        mismatch = (
            self._opaque_product_mismatch(layer_path, still.path)
            if source_hash_ok and layer_hash_ok
            else 1.0
        )
        semantic = self.siglip.score(
            image_path=str(still.path),
            product_name=str(plan.get("product_name", product.product_id)),
        )
        raw_observations = understanding.get("observations", [])
        raw_detections = grounding.get("detections", [])
        observations = (
            raw_observations if isinstance(raw_observations, list) else []
        )
        detections = raw_detections if isinstance(raw_detections, list) else []
        located = sum(
            isinstance(item, Mapping) and bool(str(item.get("locator", "")).strip())
            for item in observations
        )
        observation_count = len(observations) + len(detections)
        located_count = located + len(detections)
        identity_pass = source_hash_ok and layer_hash_ok and mismatch <= 0.001
        cross_media_pass = (
            identity_pass
            and semantic.passed
            and bool(plan.get("emotion_match"))
            and observation_count > 0
            and located_count == observation_count
            and product.rights in {"owned", "licensed"}
        )
        return StillAudit(
            repairs=0,
            unsupported_claim_count=0,
            observation_count=observation_count,
            located_observation_count=located_count,
            image_identity_pass=identity_pass,
            cross_media_pass=cross_media_pass,
            peak_vram_gb=_peak_vram_gb(),
            evidence={
                "source_hash_ok": source_hash_ok,
                "layer_hash_ok": layer_hash_ok,
                "opaque_pixel_mismatch_ratio": mismatch,
                "semantic": asdict(semantic),
                "emotion_match": bool(plan.get("emotion_match")),
            },
        )

    @staticmethod
    def _opaque_product_mismatch(layer_path: Path, output_path: Path) -> float:
        from .audit import FourGateReleaseAuditor

        return FourGateReleaseAuditor._opaque_product_mismatch(
            layer_path,
            output_path,
        )

    @staticmethod
    def _video_size(aspect_ratio: str) -> tuple[int, int]:
        if aspect_ratio == "9:16":
            return 448, 768
        if aspect_ratio == "4:5":
            return 576, 704
        return 640, 640

    @staticmethod
    def _write_launch_chime(
        path: Path,
        *,
        duration_seconds: float,
        cue_start: float,
        cue_end: float,
        sample_rate: int = 48_000,
    ) -> None:
        import numpy as np

        sample_count = round(duration_seconds * sample_rate)
        timeline = np.arange(sample_count, dtype=np.float32) / sample_rate
        audio = np.zeros(sample_count, dtype=np.float32)
        cue_mask = (timeline >= cue_start) & (timeline <= cue_end)
        cue_time = timeline[cue_mask] - cue_start
        envelope = np.sin(np.pi * cue_time / (cue_end - cue_start)) ** 2
        audio[cue_mask] = 0.40 * envelope * (
            np.sin(2 * np.pi * 659.25 * cue_time)
            + 0.55 * np.sin(2 * np.pi * 987.77 * cue_time)
        )
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(
                (np.clip(audio, -0.95, 0.95) * 32767)
                .astype("<i2")
                .tobytes()
            )

    def generate_video(
        self,
        case: BenchmarkCase,
        product: ProductSpec,
        understanding: Mapping[str, object],
        grounding: Mapping[str, object],
        plan: Mapping[str, object],
        still: ArtifactOutput,
        output_path: Path,
    ) -> ArtifactOutput:
        del product, understanding, grounding
        self._require_phase(BenchmarkPhase.GENERATE_VIDEOS, self.active_phase)
        if self.ltx_pipeline is None:
            raise PermanentActivityError("LTX image-to-video pipeline is not loaded")
        import torch
        from diffusers.utils import export_to_video

        width, height = self._video_size(case.aspect_ratio)
        prompt = (
            f"{plan['visual_direction']}. A slow controlled dolly-in around a "
            "single rigid product. Preserve geometry. No text or duplicate object."
        )
        _reset_peak_memory()
        generator = torch.Generator(device=self.settings.device).manual_seed(
            case.seed
        )
        with Image.open(still.path) as source_still:
            conditioning_image = source_still.convert("RGB")
        result = self.ltx_pipeline(
            image=conditioning_image,
            prompt=prompt,
            negative_prompt=(
                "warped product, changed logo, illegible text, duplicate product, "
                "jitter, blur, watermark"
            ),
            width=width,
            height=height,
            num_frames=self.settings.video_frames,
            num_inference_steps=self.settings.video_steps,
            generator=generator,
        )
        frames = tuple(frame.convert("RGBA") for frame in result.frames[0])
        if not frames:
            raise PermanentActivityError("LTX returned no frames")
        normalized_box = (0.24, 0.34, 0.76, 0.80)
        product_source = Path(
            str(still.metadata.get("product_source_path", ""))
        )
        with Image.open(product_source) as source_product:
            product_layer = source_product.convert("RGBA")
        locked_frames, identity_report = IdentityLockedVideoComposer().compose(
            generated_frames=frames,
            product_layer=product_layer,
            normalized_box=normalized_box,
        )
        cue_start = 1.0
        cue_end = 1.34
        cued_frames = []
        for index, frame in enumerate(locked_frames):
            rendered = frame.copy()
            seconds = index / self.settings.video_fps
            if cue_start <= seconds <= cue_end:
                cue = ImageDraw.Draw(rendered)
                radius = 24 + (index % 8) * 3
                cue.ellipse(
                    (54 - radius, 54 - radius, 54 + radius, 54 + radius),
                    outline=(255, 187, 76, 255),
                    width=8,
                )
            cued_frames.append(rendered.convert("RGB"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        video_only_path = output_path.with_name(
            f"{output_path.stem}.video-only.mp4"
        )
        audio_path = output_path.with_name(f"{output_path.stem}.launch-chime.wav")
        export_to_video(
            cued_frames,
            str(video_only_path),
            fps=self.settings.video_fps,
        )
        duration = len(cued_frames) / self.settings.video_fps
        self._write_launch_chime(
            audio_path,
            duration_seconds=duration,
            cue_start=cue_start,
            cue_end=cue_end,
        )
        import imageio_ffmpeg

        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-i",
                str(video_only_path),
                "-i",
                str(audio_path),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise PermanentActivityError("final A/V MP4 was not created")
        return ArtifactOutput(
            path=output_path,
            model_ref=self.settings.model_ref("video"),
            peak_vram_gb=_peak_vram_gb(),
            metadata={
                "prompt": prompt,
                "seed": case.seed,
                "frame_count": len(cued_frames),
                "fps": self.settings.video_fps,
                "width": width,
                "height": height,
                "normalized_product_box": list(normalized_box),
                "product_source_path": str(product_source),
                "preencode_identity": asdict(identity_report),
                "cue_start_seconds": cue_start,
                "cue_end_seconds": cue_end,
                "sample_rate": 48_000,
            },
            sidecars=(video_only_path, audio_path),
        )

    @staticmethod
    def _decode_video(path: Path) -> tuple[Image.Image, ...]:
        import av

        frames = []
        with av.open(str(path)) as container:
            for frame in container.decode(video=0):
                frames.append(frame.to_image().convert("RGB"))
        if not frames:
            raise PermanentActivityError("decoded video contains no frames")
        return tuple(frames)

    def track_video(
        self,
        case: BenchmarkCase,
        product: ProductSpec,
        grounding: Mapping[str, object],
        still: ArtifactOutput,
        video: ArtifactOutput,
    ) -> Mapping[str, object]:
        del case, product, still
        self._require_phase(BenchmarkPhase.TRACK_VIDEOS, self.active_phase)
        if self.sam2 is None:
            raise PermanentActivityError("SAM2 is not loaded")
        selected = grounding.get("selected")
        source_size = grounding.get("source_size")
        if not isinstance(selected, Mapping) or not (
            isinstance(source_size, list) and len(source_size) == 2
        ):
            raise PermanentActivityError("GroundingDINO evidence is incomplete")
        source_box = selected.get("box_xyxy")
        if not (isinstance(source_box, (list, tuple)) and len(source_box) == 4):
            raise PermanentActivityError("GroundingDINO box is missing")
        normalized = video.metadata.get("normalized_product_box")
        if not (isinstance(normalized, list) and len(normalized) == 4):
            raise PermanentActivityError("video product box is missing")
        frames = self._decode_video(video.path)
        video_width, video_height = frames[0].size
        container = (
            float(normalized[0]) * video_width,
            float(normalized[1]) * video_height,
            float(normalized[2]) * video_width,
            float(normalized[3]) * video_height,
        )
        source_width, source_height = map(float, source_size)
        dx1, dy1, dx2, dy2 = map(float, source_box)
        container_width = container[2] - container[0]
        container_height = container[3] - container[1]
        prompt_box = (
            container[0] + dx1 / source_width * container_width,
            container[1] + dy1 / source_height * container_height,
            container[0] + dx2 / source_width * container_width,
            container[1] + dy2 / source_height * container_height,
        )
        _reset_peak_memory()
        report = self.sam2.track(
            frames=frames,
            prompt_box_xyxy=prompt_box,
            source_artifact_id=str(grounding["source_artifact_id"]),
        )
        return {
            **asdict(report),
            "prompt_box_xyxy": list(prompt_box),
            "peak_vram_gb": _peak_vram_gb(),
        }

    @staticmethod
    def _extract_audio(
        video_path: Path,
        output_path: Path,
        *,
        sample_rate: int,
    ) -> tuple[object, float]:
        import imageio_ffmpeg
        import numpy as np

        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
        with wave.open(str(output_path), "rb") as handle:
            frame_count = handle.getnframes()
            audio = (
                np.frombuffer(handle.readframes(frame_count), dtype="<i2")
                .astype(np.float32)
                / 32768.0
            )
            duration = frame_count / handle.getframerate()
        return audio, duration

    @staticmethod
    def _visual_cue_frames(frames: tuple[Image.Image, ...]) -> tuple[int, ...]:
        import numpy as np

        detected = []
        for index, frame in enumerate(frames):
            crop = np.asarray(frame.crop((5, 5, 103, 103)))
            amber = (
                (crop[:, :, 0] > 180)
                & (crop[:, :, 1] > 100)
                & (crop[:, :, 2] < 150)
            )
            if int(amber.sum()) >= 35:
                detected.append(index)
        return tuple(detected)

    def audit_video(
        self,
        case: BenchmarkCase,
        product: ProductSpec,
        understanding: Mapping[str, object],
        grounding: Mapping[str, object],
        plan: Mapping[str, object],
        still: ArtifactOutput,
        video: ArtifactOutput,
        tracking: Mapping[str, object],
    ) -> VideoAudit:
        del case, product, understanding, grounding, plan, still
        self._require_phase(BenchmarkPhase.AUDIT_VIDEOS, self.active_phase)
        if self.clap is None:
            raise PermanentActivityError("CLAP is not loaded")
        normalized = video.metadata.get("normalized_product_box")
        if not (isinstance(normalized, list) and len(normalized) == 4):
            raise PermanentActivityError("video product box is missing")
        product_source = Path(
            str(video.metadata.get("product_source_path", ""))
        )
        expected_frames = int(video.metadata.get("frame_count", 0))
        fps = int(video.metadata.get("fps", 0))
        sample_rate = int(video.metadata.get("sample_rate", 0))
        if expected_frames <= 0 or fps <= 0 or sample_rate <= 0:
            raise PermanentActivityError("video timing metadata is invalid")
        _reset_peak_memory()
        with Image.open(product_source) as source_product:
            product_layer = source_product.convert("RGBA")
        encoded = EncodedVideoIdentityGate(
            codec_tolerance=self.settings.encoded_identity_tolerance,
            minimum_frame_coverage=0.95,
        ).audit(
            video_path=video.path,
            product_layer=product_layer,
            normalized_box=tuple(float(value) for value in normalized),
            expected_frame_count=expected_frames,
        )
        frames = self._decode_video(video.path)
        cue_frames = self._visual_cue_frames(frames)
        if not cue_frames:
            raise PermanentActivityError("decoded visual launch cue is missing")
        decoded_audio_path = video.path.with_name(
            f"{video.path.stem}.decoded-audit.wav"
        )
        audio, audio_duration = self._extract_audio(
            video.path,
            decoded_audio_path,
            sample_rate=sample_rate,
        )
        try:
            clap_score = self.clap.score_array(
                audio=audio,
                sampling_rate=sample_rate,
                expected_label="a bright electronic launch chime",
                candidate_labels=(
                    "a bright electronic launch chime",
                    "spoken human voice",
                    "traffic noise",
                    "silence",
                ),
            )
        finally:
            if decoded_audio_path.exists():
                decoded_audio_path.unlink()
        cue_start = float(video.metadata["cue_start_seconds"])
        cue_end = float(video.metadata["cue_end_seconds"])
        audio_event = SemanticEvent(
            "launch chime",
            cue_start,
            cue_end,
            clap_score.expected_probability,
            f"decoded_audio_seconds:{cue_start:.2f}-{cue_end:.2f}",
        )
        video_event = SemanticEvent(
            "launch chime",
            min(cue_frames) / fps,
            (max(cue_frames) + 1) / fps,
            1.0,
            f"decoded_frames:{min(cue_frames)}-{max(cue_frames)}",
        )
        alignment = AudioVideoAlignmentGate(
            tolerance_seconds=0.50,
            duration_tolerance_seconds=0.25,
            minimum_event_coverage=0.95,
        ).audit(
            audio_events=(audio_event,),
            video_events=(video_event,),
            audio_duration_seconds=audio_duration,
            video_duration_seconds=len(frames) / fps,
        )
        preencode = video.metadata.get("preencode_identity", {})
        preencode_pass = (
            isinstance(preencode, Mapping) and preencode.get("passed") is True
        )
        tracking_pass = tracking.get("passed") is True
        cross_media = (
            preencode_pass
            and encoded.passed
            and tracking_pass
            and clap_score.passed
            and alignment.passed
        )
        return VideoAudit(
            preencode_video_identity_pass=preencode_pass,
            encoded_video_identity_pass=encoded.passed,
            audio_video_alignment_pass=alignment.passed,
            cross_media_pass=cross_media,
            peak_vram_gb=max(
                _peak_vram_gb(),
                float(tracking.get("peak_vram_gb", 0.0)),
            ),
            evidence={
                "encoded_identity": encoded.to_dict(),
                "tracking": dict(tracking),
                "clap": asdict(clap_score),
                "alignment": alignment.to_dict(),
                "visual_cue_frames": list(cue_frames),
            },
        )


def create_adapter() -> RadeonLocalCompetitionAdapter:
    repository_settings = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "radeon_matrix_adapter.json"
    )
    packaged_settings = Path(__file__).with_name(
        "radeon_matrix_adapter.default.json"
    )
    default_settings = (
        repository_settings
        if repository_settings.is_file()
        else packaged_settings
    )
    settings_path = os.environ.get(
        "PROOFLAUNCH_RADEON_ADAPTER_SETTINGS",
        str(default_settings),
    )
    return RadeonLocalCompetitionAdapter.from_settings_file(settings_path)
