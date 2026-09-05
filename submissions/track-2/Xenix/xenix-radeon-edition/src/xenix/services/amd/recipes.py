"""Pinned target recipes for bundled AMD component manifests.

This module only turns an exact immutable generation into non-secret target
layout facts and a POSIX provisioning recipe.  A placement owns all actual
filesystem, transport, process, and endpoint effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .manifests import ArtifactDescriptor, ComponentManifest, ManifestCapability, SourceKind
from .reconcile import AmdGenerationMaterialization


class AmdRecipeError(RuntimeError):
    """A bundled target recipe cannot safely realize its manifest."""


_VLLM_WHEEL_INDEX = "https://wheels.vllm.ai/rocm/nightly/rocm721"
_RAPIDOCR_ASSET_URLS = {
    "rapidocr-det-model": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/torch/PP-OCRv6/det/PP-OCRv6_det_small.pth",
    "rapidocr-cls-model": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/torch/PP-OCRv4/cls/ch_ptocr_mobile_v2.0_cls_mobile.pth",
    "rapidocr-rec-model": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/torch/PP-OCRv6/rec/PP-OCRv6_rec_small.pth",
    "rapidocr-dictionary": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv6/rec/PP-OCRv6_rec_small/ppocrv6_dict.txt",
    "rapidocr-font": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/resources/fonts/FZYTK.TTF",
}


@dataclass(frozen=True, slots=True)
class TargetAsset:
    """A bounded source file transferred to the exact target generation."""

    filename: str
    source: bytes = field(repr=False)
    executable: bool = False

    def __post_init__(self) -> None:
        path = PurePosixPath(self.filename)
        if (
            not isinstance(self.filename, str)
            or path.is_absolute()
            or len(path.parts) != 1
            or self.filename in {"", ".", ".."}
            or "\x00" in self.filename
        ):
            raise AmdRecipeError("Target asset filename is invalid.")
        if not isinstance(self.source, bytes) or not self.source or len(self.source) > 2 * 1024 * 1024:
            raise AmdRecipeError("Target asset source is invalid.")


@dataclass(frozen=True, slots=True)
class TargetLaunchLayout:
    """One non-secret command and bounded cleanup allow-list."""

    command: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    public_port: int
    owned_relative_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.command or not self.command[0].startswith("/"):
            raise AmdRecipeError("Target launch command is invalid.")
        if not 1_024 <= self.public_port <= 65_535:
            raise AmdRecipeError("Target launch port is invalid.")


@dataclass(frozen=True, slots=True)
class ComponentRecipe:
    """The only bundled target recipe for one product generation."""

    materialization: AmdGenerationMaterialization
    kind: str

    @property
    def manifest(self) -> ComponentManifest:
        return self.materialization.manifest

    def provisioning_script(self) -> str:
        if self.kind == "vllm":
            return _VLLM_PROVISION_SCRIPT
        if self.kind == "rapidocr":
            return _RAPIDOCR_PROVISION_SCRIPT
        raise AmdRecipeError("Target recipe kind is unsupported.")

    def provisioning_arguments(self) -> tuple[str, ...]:
        if self.kind == "vllm":
            return self._vllm_arguments()
        if self.kind == "rapidocr":
            return self._rapidocr_arguments()
        raise AmdRecipeError("Target recipe kind is unsupported.")

    def target_assets(self) -> tuple[TargetAsset, ...]:
        if self.kind == "rapidocr":
            from .components.rapidocr_server import rapidocr_server_asset

            asset = rapidocr_server_asset()
            return (TargetAsset(filename=asset.filename, source=asset.source),)
        if self.kind == "vllm":
            from .components.openai_proxy import openai_proxy_asset

            asset = openai_proxy_asset()
            return (TargetAsset(filename=asset.filename, source=asset.source),)
        raise AmdRecipeError("Target recipe kind is unsupported.")

    def launch_layout(
        self,
        *,
        generation_root: str,
        public_port: int,
        backend_port: int | None = None,
    ) -> TargetLaunchLayout:
        root = _require_generation_root(generation_root)
        environment = {
            setting.name: setting.value for setting in self.manifest.launch.environment
        }
        environment.update(
            {
                "HF_HOME": f"{root}/cache/huggingface",
                "XDG_CACHE_HOME": f"{root}/cache/xdg",
                "VLLM_CONFIG_ROOT": f"{root}/config/vllm",
                "VLLM_CACHE_ROOT": f"{root}/cache/vllm",
            }
        )
        python = f"{root}/runtime/bin/python"
        owned = (
            "runtime",
            "runtime-wheels",
            "models",
            "target",
            "cache",
            "config",
            "provenance.json",
            "provisioning.log",
            "runtime.log",
        )
        if self.kind == "rapidocr":
            return TargetLaunchLayout(
                command=(
                    python,
                    f"{root}/target/rapidocr_kserve_server.py",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(public_port),
                    "--model-root",
                    f"{root}/models",
                ),
                environment=tuple(sorted(environment.items())),
                public_port=public_port,
                owned_relative_paths=owned,
            )
        if self.kind == "vllm":
            if backend_port is None or not 1_024 <= backend_port <= 65_535:
                raise AmdRecipeError("vLLM backend port is invalid.")
            wheel_name = _require_flat_filename(
                _single_runtime_artifact(self.manifest).relative_path,
                "vLLM runtime artifact filename",
            )
            return TargetLaunchLayout(
                command=(
                    python,
                    f"{root}/target/openai_proxy.py",
                    "--listen-port",
                    str(public_port),
                    "--backend-url",
                    f"http://127.0.0.1:{backend_port}",
                    "--backend-timeout-seconds",
                    "300",
                    "--backend-startup-timeout-seconds",
                    "300",
                    "--backend-command",
                    f"{root}/runtime/bin/vllm",
                    "serve",
                    f"{root}/models",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(backend_port),
                    "--served-model-name",
                    self.manifest.launch.served_model_name,
                    *self.manifest.launch.arguments,
                ),
                environment=tuple(sorted(environment.items())),
                public_port=public_port,
                # ``vllm.whl`` is the only pre-admission recipe residue.  It
                # remains cleanup-only so a retry can retire a generation
                # created by that earlier immutable draft recipe; new writes
                # use the manifest-declared wheel filename below.
                owned_relative_paths=(*owned, "vllm.whl", wheel_name),
            )
        raise AmdRecipeError("Target recipe kind is unsupported.")

    def _vllm_arguments(self) -> tuple[str, ...]:
        runtime_artifact = _single_runtime_artifact(self.manifest)
        source = _source_for(self.manifest, runtime_artifact.source_id)
        if source.kind is not SourceKind.HTTPS:
            raise AmdRecipeError("vLLM runtime source is invalid.")
        model = _single_model(self.manifest)
        declared = tuple(
            item
            for artifact in self.manifest.artifacts
            if artifact.kind.value in {"model", "support", "tokenizer"}
            for item in (artifact.relative_path, artifact.sha256, str(artifact.size_bytes))
        )
        return (
            model.model_id,
            model.revision,
            _require_flat_filename(runtime_artifact.relative_path, "vLLM runtime artifact filename"),
            source.locator,
            runtime_artifact.sha256,
            str(runtime_artifact.size_bytes),
            _VLLM_WHEEL_INDEX,
            str(len(declared) // 3),
            *declared,
        )

    def _rapidocr_arguments(self) -> tuple[str, ...]:
        runtime_arguments: list[str] = []
        for artifact in _runtime_artifacts(self.manifest):
            source = _source_for(self.manifest, artifact.source_id)
            if source.kind is not SourceKind.HTTPS:
                raise AmdRecipeError("RapidOCR runtime source is invalid.")
            runtime_arguments.extend(
                (artifact.relative_path, source.locator, artifact.sha256, str(artifact.size_bytes))
            )
        declared: list[str] = []
        for artifact in self.manifest.artifacts:
            if artifact.kind.value not in {"model", "support"}:
                continue
            url = _RAPIDOCR_ASSET_URLS.get(artifact.artifact_id)
            if url is None:
                raise AmdRecipeError("RapidOCR asset is not mapped by the bundled recipe.")
            declared.extend((artifact.relative_path, url, artifact.sha256, str(artifact.size_bytes)))
        return (
            str(len(runtime_arguments) // 4),
            *runtime_arguments,
            str(len(declared) // 4),
            *declared,
        )


def recipe_for(materialization: AmdGenerationMaterialization) -> ComponentRecipe:
    """Resolve one product capability to its explicitly shipped recipe."""

    manifest = materialization.manifest
    if materialization.capability is not manifest.capability:
        raise AmdRecipeError("Generation capability does not match its manifest.")
    if manifest.capability in {ManifestCapability.CHAT, ManifestCapability.EMBEDDING}:
        if manifest.runtime.framework_id != "vllm":
            raise AmdRecipeError("vLLM component manifest has the wrong runtime.")
        return ComponentRecipe(materialization=materialization, kind="vllm")
    if manifest.capability is ManifestCapability.OCR:
        if manifest.runtime.framework_id != "rapidocr":
            raise AmdRecipeError("RapidOCR component manifest has the wrong runtime.")
        return ComponentRecipe(materialization=materialization, kind="rapidocr")
    raise AmdRecipeError("AMD component capability is unsupported.")


def _single_runtime_artifact(manifest: ComponentManifest) -> ArtifactDescriptor:
    values = tuple(item for item in manifest.artifacts if item.kind.value == "runtime")
    if len(values) != 1:
        raise AmdRecipeError("AMD component must declare exactly one runtime artifact.")
    return values[0]


def _runtime_artifacts(manifest: ComponentManifest) -> tuple[ArtifactDescriptor, ...]:
    values = tuple(item for item in manifest.artifacts if item.kind.value == "runtime")
    if not values:
        raise AmdRecipeError("AMD component must declare one or more runtime artifacts.")
    return values


def _source_for(manifest: ComponentManifest, source_id: str):
    values = tuple(source for source in manifest.sources if source.source_id == source_id)
    if len(values) != 1:
        raise AmdRecipeError("AMD artifact source is invalid.")
    return values[0]


def _single_model(manifest: ComponentManifest):
    if len(manifest.models) != 1:
        raise AmdRecipeError("AMD component must declare exactly one model.")
    return manifest.models[0]


def _require_flat_filename(value: str, label: str) -> str:
    """Keep recipe-owned runtime artifacts below one exact generation root."""

    path = PurePosixPath(value)
    if (
        not isinstance(value, str)
        or path.is_absolute()
        or len(path.parts) != 1
        or value in {"", ".", ".."}
        or "\x00" in value
    ):
        raise AmdRecipeError(f"{label} is invalid.")
    return value


def _require_generation_root(value: str) -> str:
    path = PurePosixPath(value)
    if not isinstance(value, str) or not path.is_absolute() or ".." in path.parts or len(path.parts) < 5:
        raise AmdRecipeError("Generation root is invalid.")
    return str(path)


_TARGET_ASSET_UPLOAD_SCRIPT = r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
owner=$6
incarnation=$7
filename=$8
executable=$9
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
target_root="$generation_root/target"
retiring="$generation_root/.xenix-retiring"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 41
expected_marker=$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")
[ -f "$marker" ] && [ "$(cat "$marker")" = "$expected_marker" ] || exit 42
[ ! -e "$retiring" ] || exit 47
case "$filename" in
    ""|.|..|*/*|*\\*) exit 43 ;;
esac
case "$executable" in
    0|1) ;;
    *) exit 44 ;;
esac
[ -d "$target_root" ] && [ ! -L "$target_root" ] || exit 45
umask 077
temporary="$target_root/.${filename}.tmp.$$"
trap 'rm -f -- "$temporary"' EXIT HUP INT TERM
cat > "$temporary"
[ -f "$temporary" ] && [ ! -L "$temporary" ] || exit 46
if [ "$executable" = 1 ]; then
    chmod 700 -- "$temporary"
else
    chmod 600 -- "$temporary"
fi
mv -f -- "$temporary" "$target_root/$filename"
trap - EXIT HUP INT TERM
""".strip()


def target_asset_upload_script() -> str:
    """Return the immutable fenced asset-write program for Linux operations."""

    return _TARGET_ASSET_UPLOAD_SCRIPT


def target_recipe_programs() -> dict[str, str]:
    """Return the small explicit program catalogue used by WSL transport.

    A WSL session accepts a recipe identifier rather than arbitrary shell text.
    This mapping is the composition-owned bridge from capability recipes to
    that restricted process boundary.
    """

    return {
        "rapidocr-provision": _RAPIDOCR_PROVISION_SCRIPT,
        "target-asset-upload": _TARGET_ASSET_UPLOAD_SCRIPT,
        "vllm-provision": _VLLM_PROVISION_SCRIPT,
    }


_VLLM_PROVISION_SCRIPT = r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
owner=$6
incarnation=$7
model_id=$8
model_revision=$9
wheel_filename=${10}
wheel_url=${11}
wheel_sha=${12}
wheel_size=${13}
wheel_index=${14}
artifact_count=${15}
shift 15
generation_root="$root/installations/$installation/generations/$generation"
runtime="$generation_root/runtime"
models="$generation_root/models"
cache="$generation_root/cache"
config="$generation_root/config"
case "$wheel_filename" in
    ""|.|..|*/*|*\\*) exit 44 ;;
esac
wheel="$generation_root/$wheel_filename"
marker="$generation_root/.xenix-generation"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 41
[ -f "$marker" ] && [ "$(cat "$marker")" = "$target	$installation	$generation	$manifest" ] || exit 42
for tool in python3 curl sha256sum wc; do command -v "$tool" >/dev/null 2>&1 || exit 43; done
umask 077
mkdir -p -- "$models" "$generation_root/target" "$cache/huggingface" "$cache/xdg" "$cache/vllm" "$cache/tmp" "$config/vllm"
export TMPDIR="$cache/tmp"
if [ ! -d "$runtime" ]; then python3 -m venv "$runtime"; fi
[ -d "$runtime" ] && [ ! -L "$runtime" ] || exit 45
wheel_temporary="$wheel.download.$$"
rm -f -- "$wheel_temporary"
curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 --retry 3 --output "$wheel_temporary" "$wheel_url"
[ -f "$wheel_temporary" ] && [ ! -L "$wheel_temporary" ] || exit 45
[ "$(wc -c < "$wheel_temporary")" = "$wheel_size" ] || exit 46
[ "$(sha256sum "$wheel_temporary" | awk '{print $1}')" = "$wheel_sha" ] || exit 47
mv -f -- "$wheel_temporary" "$wheel"
PIP_NO_INPUT=1 "$runtime/bin/python" -m pip install -q --disable-pip-version-check --no-cache-dir --timeout 60 --retries 3 --index-url "https://pypi.tuna.tsinghua.edu.cn/simple" --extra-index-url "$wheel_index" "$wheel" >"$generation_root/provisioning.log" 2>&1
HF_HOME="$cache/huggingface" HF_ENDPOINT="https://hf-mirror.com" HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_XET=1 "$runtime/bin/python" -c 'from huggingface_hub import snapshot_download; import sys; snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3], ignore_patterns=[".DS_Store", "**/.DS_Store"])' "$model_id" "$model_revision" "$models" >>"$generation_root/provisioning.log" 2>&1
i=0
while [ "$i" -lt "$artifact_count" ]; do
    [ "$#" -ge 3 ] || exit 47
    relative=$1
    expected_sha=$2
    expected_size=$3
    shift 3
    candidate="$models/$relative"
    [ -f "$candidate" ] && [ ! -L "$candidate" ] || exit 48
    [ "$(wc -c < "$candidate")" = "$expected_size" ] || exit 49
    [ "$(sha256sum "$candidate" | awk '{print $1}')" = "$expected_sha" ] || exit 50
    i=$((i + 1))
done
[ "$#" -eq 0 ] || exit 51
printf '%s\n' "$manifest" > "$generation_root/provenance.json"
""".strip()


_RAPIDOCR_PROVISION_SCRIPT = r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
owner=$6
incarnation=$7
runtime_count=$8
shift 8
generation_root="$root/installations/$installation/generations/$generation"
runtime="$generation_root/runtime"
models="$generation_root/models"
cache="$generation_root/cache"
config="$generation_root/config"
runtime_wheels="$generation_root/runtime-wheels"
marker="$generation_root/.xenix-generation"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 41
[ -f "$marker" ] && [ "$(cat "$marker")" = "$target	$installation	$generation	$manifest" ] || exit 42
for tool in python3 curl sha256sum wc; do command -v "$tool" >/dev/null 2>&1 || exit 43; done
umask 077
mkdir -p -- "$models" "$generation_root/target" "$cache/huggingface" "$cache/xdg" "$cache/vllm" "$cache/tmp" "$config/vllm" "$runtime_wheels"
export TMPDIR="$cache/tmp"
if [ ! -d "$runtime" ]; then python3 -m venv "$runtime"; fi
[ -d "$runtime" ] && [ ! -L "$runtime" ] || exit 44
runtime_arguments="$runtime_wheels/install.list"
: > "$runtime_arguments"
download_runtime_artifact() {
    destination=$1
    source_url=$2
    case "$source_url" in
        https://files.pythonhosted.org/packages/*)
            mirror_url="https://pypi.tuna.tsinghua.edu.cn/packages/${source_url#https://files.pythonhosted.org/packages/}"
            if curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 1800 --retry 3 --output "$destination" "$mirror_url"; then
                return 0
            fi
            rm -f -- "$destination"
            ;;
    esac
    curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 1800 --retry 3 --output "$destination" "$source_url"
}
i=0
while [ "$i" -lt "$runtime_count" ]; do
    [ "$#" -ge 4 ] || exit 45
    relative=$1
    wheel_url=$2
    expected_sha=$3
    expected_size=$4
    shift 4
    case "$relative" in
        ""|.|..|*/*|*\\*) exit 46 ;;
    esac
    wheel="$runtime_wheels/$relative"
    wheel_temporary="$wheel.download.$$"
    rm -f -- "$wheel_temporary"
    download_runtime_artifact "$wheel_temporary" "$wheel_url"
    [ -f "$wheel_temporary" ] && [ ! -L "$wheel_temporary" ] || exit 47
    [ "$(wc -c < "$wheel_temporary")" = "$expected_size" ] || exit 48
    [ "$(sha256sum "$wheel_temporary" | awk '{print $1}')" = "$expected_sha" ] || exit 49
    mv -f -- "$wheel_temporary" "$wheel"
    printf '%s\n' "$wheel" >> "$runtime_arguments"
    i=$((i + 1))
done
[ "$#" -ge 1 ] || exit 50
asset_count=$1
shift
"$runtime/bin/python" - "$runtime_arguments" <<'PY' >"$generation_root/provisioning.log" 2>&1
import subprocess
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    wheels = [line.rstrip("\n") for line in stream]
if not wheels or any(not item for item in wheels):
    raise SystemExit(1)
subprocess.run(
    [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-q",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--timeout",
        "60",
        "--retries",
        "3",
        "--index-url",
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        *wheels,
    ],
    check=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
PY
i=0
while [ "$i" -lt "$asset_count" ]; do
    [ "$#" -ge 4 ] || exit 51
    relative=$1
    asset_url=$2
    expected_sha=$3
    expected_size=$4
    shift 4
    candidate="$models/$relative"
    mkdir -p -- "$(dirname "$candidate")"
    curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 --retry 3 --output "$candidate" "$asset_url"
    [ -f "$candidate" ] && [ ! -L "$candidate" ] || exit 52
    [ "$(wc -c < "$candidate")" = "$expected_size" ] || exit 53
    [ "$(sha256sum "$candidate" | awk '{print $1}')" = "$expected_sha" ] || exit 54
    i=$((i + 1))
done
[ "$#" -eq 0 ] || exit 55
printf '%s\n' "$manifest" > "$generation_root/provenance.json"
""".strip()


__all__ = [
    "AmdRecipeError",
    "ComponentRecipe",
    "TargetAsset",
    "TargetLaunchLayout",
    "recipe_for",
    "target_asset_upload_script",
    "target_recipe_programs",
]
