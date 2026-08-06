from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from agent_factory.model_pool.config import resolve_model_root


class ModelStorageError(ValueError):
    pass


_TRANSFORMERS_WEIGHT_FILES = frozenset(
    {
        "model.safetensors",
        "model.safetensors.index.json",
        "pytorch_model.bin",
        "pytorch_model.bin.index.json",
    }
)
_TRANSFORMERS_WEIGHT_PATTERNS = (
    "model-*.safetensors",
    "pytorch_model-*.bin",
)
_IMAGE_MODEL_MANIFEST = "image-model.json"


@dataclass(frozen=True, slots=True)
class ModelDirectoryInfo:
    relative_path: str
    absolute_path: str
    display_name: str
    model_type: str
    dtype: str
    embedding_dimensions: int | None
    architectures: tuple[str, ...]
    tokenizer_available: bool
    supported_kinds: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return asdict(self)


class ModelStorage:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = resolve_model_root(root)

    @property
    def modelscope_cache(self) -> Path:
        return self.root / "modelscope"

    def ensure_directories(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.modelscope_cache.mkdir(parents=True, exist_ok=True)

    def list_model_directories(self) -> list[ModelDirectoryInfo]:
        self.ensure_directories()
        models: list[ModelDirectoryInfo] = []
        for config_path in self.root.rglob("config.json"):
            directory = config_path.parent.resolve()
            if not self._contains(directory) or not self._has_supported_weights(directory):
                continue
            models.append(self._describe(directory, config_path=config_path))
        image_model_paths: set[Path] = set()
        for manifest_path in self.root.rglob(_IMAGE_MODEL_MANIFEST):
            directory = manifest_path.parent.resolve()
            if self._contains(directory):
                described = self._describe_image_model(directory, manifest_path)
                if described is not None:
                    models.append(described)
                    image_model_paths.add(Path(described.absolute_path))
        for model_path in self.root.rglob("*.gguf"):
            if self._contains(model_path.resolve()) and model_path.resolve() not in image_model_paths:
                models.append(self._describe_gguf(model_path.resolve()))
        return sorted(models, key=lambda item: item.relative_path.casefold())

    def require_model_directory(self, value: str | Path) -> Path:
        directory = self.resolve_directory(value)
        if not self._is_supported_model_directory(directory):
            raise ModelStorageError(
                "model directory must contain config.json and supported Transformers weights"
            )
        return directory

    def require_llama_model_file(self, value: str | Path) -> Path:
        text = str(value or "").strip()
        raw_path = Path(text).expanduser()
        model_path = (raw_path if raw_path.is_absolute() else self.root / raw_path).resolve()
        if not self._contains(model_path) or not model_path.is_file():
            raise ModelStorageError("llama.cpp model file must exist inside the model root")
        return model_path

    def resolve_directory(self, value: str | Path) -> Path:
        text = str(value or "").strip()
        if not text:
            raise ModelStorageError("model directory is required")
        raw_path = Path(text).expanduser()
        candidate = raw_path if raw_path.is_absolute() else self.root / raw_path
        directory = candidate.resolve()
        if not self._contains(directory):
            raise ModelStorageError(f"model directory must be inside {self.root}")
        if not directory.is_dir():
            raise ModelStorageError(f"model directory does not exist: {directory}")
        return directory

    def _contains(self, path: Path) -> bool:
        return path == self.root or self.root in path.parents

    def _is_supported_model_directory(self, directory: Path) -> bool:
        return (directory / "config.json").is_file() and self._has_supported_weights(directory)

    def _has_supported_weights(self, directory: Path) -> bool:
        if any((directory / filename).is_file() for filename in _TRANSFORMERS_WEIGHT_FILES):
            return True
        return any(any(directory.glob(pattern)) for pattern in _TRANSFORMERS_WEIGHT_PATTERNS)

    def _describe(self, directory: Path, *, config_path: Path) -> ModelDirectoryInfo:
        config = _read_config(config_path)
        relative_path = directory.relative_to(self.root).as_posix()
        display_name = self._modelscope_model_id(directory) or _model_name(config, directory)
        architectures = tuple(
            text for item in _items(config.get("architectures")) if (text := _text(item))
        )
        tokenizer_available = any(
            (directory / filename).is_file()
            for filename in ("tokenizer.json", "tokenizer_config.json", "sentencepiece.bpe.model")
        )
        return ModelDirectoryInfo(
            relative_path=relative_path,
            absolute_path=str(directory),
            display_name=display_name,
            model_type=_text(config.get("model_type")),
            dtype=_text(config.get("torch_dtype")),
            embedding_dimensions=_positive_integer(config.get("hidden_size")),
            architectures=architectures,
            tokenizer_available=tokenizer_available,
            supported_kinds=("embedding",),
        )

    def _describe_gguf(self, model_path: Path) -> ModelDirectoryInfo:
        return ModelDirectoryInfo(
            relative_path=model_path.relative_to(self.root).as_posix(),
            absolute_path=str(model_path),
            display_name=model_path.stem,
            model_type="gguf",
            dtype="quantized",
            embedding_dimensions=None,
            architectures=(),
            tokenizer_available=True,
            supported_kinds=("chat",),
        )

    def _describe_image_model(self, directory: Path, manifest_path: Path) -> ModelDirectoryInfo | None:
        manifest = _read_config(manifest_path)
        if manifest.get("format") != "stable_diffusion_cpp":
            return None
        filenames = [
            _text(manifest.get(key))
            for key in ("diffusion_model", "vae", "clip_l", "t5xxl")
        ]
        if not all(filenames) or not all((directory / filename).is_file() for filename in filenames):
            return None
        diffusion_path = (directory / filenames[0]).resolve()
        return ModelDirectoryInfo(
            relative_path=diffusion_path.relative_to(self.root).as_posix(),
            absolute_path=str(diffusion_path),
            display_name=_text(manifest.get("display_name")) or directory.name,
            model_type=_text(manifest.get("family")) or "diffusion",
            dtype=_text(manifest.get("quantization")) or "quantized",
            embedding_dimensions=None,
            architectures=("stable-diffusion.cpp",),
            tokenizer_available=True,
            supported_kinds=("image_generation",),
        )

    def _modelscope_model_id(self, directory: Path) -> str:
        try:
            parts = directory.relative_to(self.modelscope_cache.resolve()).parts
        except ValueError:
            return ""
        if len(parts) < 4 or parts[0] != "models" or parts[2] != "snapshots":
            return ""
        namespace, separator, model_name = parts[1].partition("--")
        if not separator or not namespace or not model_name:
            return ""
        return f"{namespace}/{model_name}"


def _read_config(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _items(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _model_name(config: dict[str, Any], directory: Path) -> str:
    configured_name = _text(config.get("_name_or_path"))
    if configured_name and not Path(configured_name).expanduser().is_absolute():
        return configured_name
    return directory.name


def _text(value: object) -> str:
    return str(value or "").strip()


def _positive_integer(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
