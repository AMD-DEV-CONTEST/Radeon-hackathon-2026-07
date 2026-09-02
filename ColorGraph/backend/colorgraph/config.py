from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


@dataclass(frozen=True, slots=True)
class Settings:
    root_dir: Path
    data_dir: Path
    projects_dir: Path
    cache_dir: Path
    models_dir: Path
    huggingface_cache_dir: Path
    device_preference: str
    ffmpeg_binary: str
    ffprobe_binary: str
    enable_scene_model: bool
    scene_model_id: str
    model_cache_max_entries: int
    model_vram_budget_mb: int
    embedding_cache_max_entries: int
    enable_creative_knowledge_corpus: bool
    creative_knowledge_corpus_path: str
    enable_creative_critic_calibration: bool
    creative_critic_calibration_path: str
    creative_network_enabled: bool
    enable_openai_creative_provider: bool
    openai_creative_model: str
    openai_creative_model_revision: str
    openai_creative_base_url: str
    openai_creative_image_input: bool
    openai_creative_strict_structured_output: bool
    openai_creative_max_context_tokens: int
    openai_creative_max_images: int
    openai_creative_input_cost_per_million: float
    openai_creative_output_cost_per_million: float
    enable_ollama_creative_provider: bool
    ollama_creative_model: str
    ollama_creative_model_digest: str
    ollama_creative_runtime_version: str
    ollama_creative_quantization: str
    ollama_creative_require_gpu: bool
    ollama_creative_min_gpu_offload_ratio: float
    ollama_creative_unload_after_request: bool
    ollama_creative_base_url: str
    ollama_creative_image_input: bool
    ollama_creative_strict_structured_output: bool
    ollama_creative_max_context_tokens: int
    ollama_creative_max_images: int

    def __post_init__(self) -> None:
        if self.model_cache_max_entries <= 0:
            raise ValueError("COLORGRAPH_MODEL_CACHE_MAX_ENTRIES must be positive")
        if self.model_vram_budget_mb < 0:
            raise ValueError("COLORGRAPH_MODEL_VRAM_BUDGET_MB must be non-negative")
        if self.embedding_cache_max_entries <= 0:
            raise ValueError("COLORGRAPH_EMBEDDING_CACHE_MAX_ENTRIES must be positive")
        if (
            self.enable_creative_knowledge_corpus
            and not self.creative_knowledge_corpus_path.strip()
        ):
            raise ValueError(
                "COLORGRAPH_CREATIVE_KNOWLEDGE_CORPUS_PATH is required when "
                "the creative knowledge corpus is enabled"
            )
        if (
            self.enable_creative_critic_calibration
            and not self.creative_critic_calibration_path.strip()
        ):
            raise ValueError(
                "COLORGRAPH_CREATIVE_CRITIC_CALIBRATION_PATH is required when "
                "creative Critic calibration is enabled"
            )
        if self.openai_creative_max_context_tokens < 0:
            raise ValueError(
                "COLORGRAPH_OPENAI_CREATIVE_MAX_CONTEXT_TOKENS must be non-negative"
            )
        if self.openai_creative_max_images < 0:
            raise ValueError("COLORGRAPH_OPENAI_CREATIVE_MAX_IMAGES must be non-negative")
        if self.ollama_creative_max_context_tokens < 0:
            raise ValueError(
                "COLORGRAPH_OLLAMA_CREATIVE_MAX_CONTEXT_TOKENS must be non-negative"
            )
        if self.ollama_creative_max_images < 0:
            raise ValueError("COLORGRAPH_OLLAMA_CREATIVE_MAX_IMAGES must be non-negative")
        if not 0 <= self.ollama_creative_min_gpu_offload_ratio <= 1:
            raise ValueError(
                "COLORGRAPH_OLLAMA_CREATIVE_MIN_GPU_OFFLOAD_RATIO must be within [0, 1]"
            )
        if (
            self.enable_openai_creative_provider
            and self.enable_ollama_creative_provider
        ):
            raise ValueError(
                "OpenAI and Ollama creative providers cannot be enabled simultaneously"
            )
        if self.enable_ollama_creative_provider:
            if not self.ollama_creative_model.strip():
                raise ValueError(
                    "COLORGRAPH_OLLAMA_CREATIVE_MODEL is required when Ollama is enabled"
                )
            digest = self.ollama_creative_model_digest
            if (
                len(digest) != 64
                or digest.lower() != digest
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise ValueError(
                    "COLORGRAPH_OLLAMA_CREATIVE_MODEL_DIGEST must be a lowercase "
                    "SHA-256 value"
                )
            if not self.ollama_creative_runtime_version.strip():
                raise ValueError(
                    "COLORGRAPH_OLLAMA_CREATIVE_RUNTIME_VERSION is required when "
                    "Ollama is enabled"
                )
            if not self.ollama_creative_quantization.strip():
                raise ValueError(
                    "COLORGRAPH_OLLAMA_CREATIVE_QUANTIZATION is required when "
                    "Ollama is enabled"
                )
            if (
                self.ollama_creative_require_gpu
                and self.ollama_creative_min_gpu_offload_ratio <= 0
            ):
                raise ValueError(
                    "GPU-required Ollama execution needs a positive minimum "
                    "offload ratio"
                )

    @classmethod
    def from_environment(cls) -> Settings:
        backend_root = Path(__file__).resolve().parents[1]
        data_dir = Path(os.getenv("COLORGRAPH_DATA_DIR", backend_root / "data")).resolve()
        models_dir = Path(
            os.getenv("COLORGRAPH_MODELS_DIR", backend_root / "models")
        ).resolve()
        huggingface_redirect = models_dir / "huggingface.redirect"
        redirected_huggingface_cache = (
            huggingface_redirect.read_text(encoding="utf-8").strip()
            if huggingface_redirect.is_file()
            else ""
        )
        huggingface_cache_dir = Path(
            os.getenv(
                "COLORGRAPH_HUGGINGFACE_CACHE_DIR",
                redirected_huggingface_cache
                or models_dir / "huggingface",
            )
        ).resolve()
        return cls(
            root_dir=backend_root,
            data_dir=data_dir,
            projects_dir=data_dir / "projects",
            cache_dir=Path(os.getenv("COLORGRAPH_CACHE_DIR", backend_root / ".cache")).resolve(),
            models_dir=models_dir,
            huggingface_cache_dir=huggingface_cache_dir,
            device_preference=os.getenv("COLORGRAPH_DEVICE", "auto").lower(),
            ffmpeg_binary=os.getenv("COLORGRAPH_FFMPEG", "ffmpeg"),
            ffprobe_binary=os.getenv("COLORGRAPH_FFPROBE", "ffprobe"),
            enable_scene_model=os.getenv(
                "COLORGRAPH_ENABLE_SCENE_MODEL",
                "true",
            ).lower()
            not in {"0", "false", "no", "off"},
            scene_model_id=os.getenv(
                "COLORGRAPH_SCENE_MODEL",
                "openai/clip-vit-base-patch32",
            ),
            model_cache_max_entries=int(
                os.getenv("COLORGRAPH_MODEL_CACHE_MAX_ENTRIES", "3")
            ),
            model_vram_budget_mb=int(
                os.getenv("COLORGRAPH_MODEL_VRAM_BUDGET_MB", "12288")
            ),
            embedding_cache_max_entries=int(
                os.getenv("COLORGRAPH_EMBEDDING_CACHE_MAX_ENTRIES", "2048")
            ),
            enable_creative_knowledge_corpus=os.getenv(
                "COLORGRAPH_ENABLE_CREATIVE_KNOWLEDGE_CORPUS",
                "false",
            ).lower()
            in {"1", "true", "yes", "on"},
            creative_knowledge_corpus_path=os.getenv(
                "COLORGRAPH_CREATIVE_KNOWLEDGE_CORPUS_PATH",
                "",
            ),
            enable_creative_critic_calibration=os.getenv(
                "COLORGRAPH_ENABLE_CREATIVE_CRITIC_CALIBRATION",
                "false",
            ).lower()
            in {"1", "true", "yes", "on"},
            creative_critic_calibration_path=os.getenv(
                "COLORGRAPH_CREATIVE_CRITIC_CALIBRATION_PATH",
                "",
            ),
            creative_network_enabled=os.getenv(
                "COLORGRAPH_CREATIVE_NETWORK",
                "false",
            ).lower()
            in {"1", "true", "yes", "on"},
            enable_openai_creative_provider=os.getenv(
                "COLORGRAPH_ENABLE_OPENAI_CREATIVE_PROVIDER",
                "false",
            ).lower()
            in {"1", "true", "yes", "on"},
            openai_creative_model=os.getenv("COLORGRAPH_OPENAI_CREATIVE_MODEL", ""),
            openai_creative_model_revision=os.getenv(
                "COLORGRAPH_OPENAI_CREATIVE_MODEL_REVISION",
                "configured",
            ),
            openai_creative_base_url=os.getenv(
                "COLORGRAPH_OPENAI_CREATIVE_BASE_URL",
                "https://api.openai.com/v1",
            ),
            openai_creative_image_input=os.getenv(
                "COLORGRAPH_OPENAI_CREATIVE_IMAGE_INPUT",
                "false",
            ).lower()
            in {"1", "true", "yes", "on"},
            openai_creative_strict_structured_output=os.getenv(
                "COLORGRAPH_OPENAI_CREATIVE_STRICT_OUTPUT",
                "false",
            ).lower()
            in {"1", "true", "yes", "on"},
            openai_creative_max_context_tokens=int(
                os.getenv("COLORGRAPH_OPENAI_CREATIVE_MAX_CONTEXT_TOKENS", "0")
            ),
            openai_creative_max_images=int(
                os.getenv("COLORGRAPH_OPENAI_CREATIVE_MAX_IMAGES", "0")
            ),
            openai_creative_input_cost_per_million=float(
                os.getenv("COLORGRAPH_OPENAI_INPUT_COST_PER_MILLION", "0")
            ),
            openai_creative_output_cost_per_million=float(
                os.getenv("COLORGRAPH_OPENAI_OUTPUT_COST_PER_MILLION", "0")
            ),
            enable_ollama_creative_provider=os.getenv(
                "COLORGRAPH_ENABLE_OLLAMA_CREATIVE_PROVIDER",
                "false",
            ).lower()
            in {"1", "true", "yes", "on"},
            ollama_creative_model=os.getenv(
                "COLORGRAPH_OLLAMA_CREATIVE_MODEL",
                "colorgraph-qwen3.5:9b",
            ),
            ollama_creative_model_digest=os.getenv(
                "COLORGRAPH_OLLAMA_CREATIVE_MODEL_DIGEST",
                "a2845456d7ad1e2100f620eaad82c3e63860a24330948111f6ad5d8202fd3634",
            ),
            ollama_creative_runtime_version=os.getenv(
                "COLORGRAPH_OLLAMA_CREATIVE_RUNTIME_VERSION",
                "0.20.6",
            ),
            ollama_creative_quantization=os.getenv(
                "COLORGRAPH_OLLAMA_CREATIVE_QUANTIZATION",
                "Q4_K_M",
            ),
            ollama_creative_require_gpu=os.getenv(
                "COLORGRAPH_OLLAMA_CREATIVE_REQUIRE_GPU",
                "true",
            ).lower()
            in {"1", "true", "yes", "on"},
            ollama_creative_min_gpu_offload_ratio=float(
                os.getenv(
                    "COLORGRAPH_OLLAMA_CREATIVE_MIN_GPU_OFFLOAD_RATIO",
                    "0.99",
                )
            ),
            ollama_creative_unload_after_request=os.getenv(
                "COLORGRAPH_OLLAMA_CREATIVE_UNLOAD_AFTER_REQUEST",
                "true",
            ).lower()
            in {"1", "true", "yes", "on"},
            ollama_creative_base_url=os.getenv(
                "COLORGRAPH_OLLAMA_CREATIVE_BASE_URL",
                "http://127.0.0.1:11434",
            ),
            ollama_creative_image_input=os.getenv(
                "COLORGRAPH_OLLAMA_CREATIVE_IMAGE_INPUT",
                "true",
            ).lower()
            in {"1", "true", "yes", "on"},
            ollama_creative_strict_structured_output=os.getenv(
                "COLORGRAPH_OLLAMA_CREATIVE_STRICT_OUTPUT",
                "false",
            ).lower()
            in {"1", "true", "yes", "on"},
            ollama_creative_max_context_tokens=int(
                os.getenv("COLORGRAPH_OLLAMA_CREATIVE_MAX_CONTEXT_TOKENS", "0")
            ),
            ollama_creative_max_images=int(
                os.getenv("COLORGRAPH_OLLAMA_CREATIVE_MAX_IMAGES", "0")
            ),
        )

    def ensure_directories(self) -> None:
        for directory in (
            self.data_dir,
            self.projects_dir,
            self.cache_dir,
            self.models_dir,
            self.huggingface_cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings.from_environment()
