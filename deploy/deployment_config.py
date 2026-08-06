from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re


ASSIGNMENT = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
REQUIRED_SETTINGS = (
    "REMOTE_PROJECT_ROOT",
    "REMOTE_STATE_ROOT",
    "REMOTE_MODEL_ROOT",
    "REMOTE_LLAMA_SOURCE_ROOT",
    "REMOTE_LLAMA_RUNTIME_ROOT",
    "LOCAL_LLAMA_OFFICIAL_DIR",
    "LOCAL_LLAMA_AMD_DIR",
    "LOCAL_STABLE_DIFFUSION_CPP_DIR",
    "LLAMA_OFFICIAL_REVISION",
    "LLAMA_OFFICIAL_BUILD_NUMBER",
    "LLAMA_AMD_BASE_REVISION",
    "LLAMA_AMD_BASE_BUILD_NUMBER",
    "LLAMA_DEFAULT_IMPLEMENTATION",
    "REMOTE_STABLE_DIFFUSION_CPP_DIR",
    "STABLE_DIFFUSION_CPP_REVISION",
    "REMOTE_CA_BUNDLE",
    "REMOTE_REPAIR_CA_TRUST",
    "REMOTE_CA_PROBE_URL",
    "CHAT_MODEL_REPOSITORY",
    "CHAT_MODEL_REVISION",
    "CHAT_MODEL_FILENAME",
    "CHAT_MODEL_SHA256",
    "CHAT_MMPROJ_FILENAME",
    "CHAT_MMPROJ_SHA256",
    "EMBEDDING_MODEL_ID",
    "EMBEDDING_MODEL_REVISION",
    "CHAT_PROFILE_ID",
    "CHAT_SERVED_MODEL_NAME",
    "CHAT_NATIVE_CONTEXT_TOKENS",
    "CHAT_YARN_MAX_CONTEXT_TOKENS",
    "CHAT_CONTEXT_SIZE",
    "CHAT_MAX_OUTPUT_TOKENS",
    "CHAT_COMPRESSION_THRESHOLD",
    "CHAT_GPU_LAYERS",
    "CHAT_PARALLEL_SLOTS",
    "CHAT_ADMISSION_MAX_PENDING",
    "CHAT_ADMISSION_PER_SESSION_ACTIVE",
    "CHAT_ADMISSION_QUEUE_TIMEOUT_SECONDS",
    "CHAT_ADMISSION_PRIORITY_AGING_SECONDS",
    "CHAT_CACHE_TYPE_K",
    "CHAT_CACHE_TYPE_V",
    "EMBEDDING_PROFILE_ID",
    "EMBEDDING_SERVED_MODEL_NAME",
    "EMBEDDING_DIMENSIONS",
    "REMOTE_CHAT_PORT",
    "REMOTE_EMBEDDING_PORT",
    "REMOTE_TELEMETRY_PORT",
    "REMOTE_IMAGE_PORT",
    "LOCAL_CHAT_PORT",
    "LOCAL_EMBEDDING_PORT",
    "LOCAL_TELEMETRY_PORT",
    "LOCAL_IMAGE_PORT",
    "IMAGE_PROFILE_ID",
    "IMAGE_SERVED_MODEL_NAME",
    "IMAGE_MODEL_FILENAME",
    "IMAGE_VAE_FILENAME",
    "IMAGE_CLIP_L_FILENAME",
    "IMAGE_T5XXL_FILENAME",
    "REMOTE_INFERENCE_PYTHON_PACKAGES",
)
LOCAL_PORT_NAMES = (
    "LOCAL_CHAT_PORT",
    "LOCAL_EMBEDDING_PORT",
    "LOCAL_TELEMETRY_PORT",
    "LOCAL_IMAGE_PORT",
)
REMOTE_PATH_NAMES = (
    "REMOTE_PROJECT_ROOT",
    "REMOTE_STATE_ROOT",
    "REMOTE_MODEL_ROOT",
    "REMOTE_LLAMA_SOURCE_ROOT",
    "REMOTE_LLAMA_RUNTIME_ROOT",
    "REMOTE_STABLE_DIFFUSION_CPP_DIR",
)


@dataclass(frozen=True, slots=True)
class DeploymentConfig:
    project_root: Path
    defaults_path: Path
    env_path: Path
    defaults: dict[str, str]
    user_values: dict[str, str]
    values: dict[str, str]

    @classmethod
    def load(cls, project_root: Path) -> "DeploymentConfig":
        root = project_root.resolve()
        defaults_path = root / "deploy" / "defaults.env"
        env_path = root / ".env"
        if not defaults_path.is_file():
            raise FileNotFoundError(f"deployment defaults are missing: {defaults_path}")
        if not env_path.is_file():
            raise FileNotFoundError(
                f"deployment config is missing; copy {root / '.env.example'} to {env_path}"
            )
        defaults = read_env_file(defaults_path)
        user_values = read_env_file(env_path)
        values = {**defaults, **user_values}
        config = cls(
            project_root=root,
            defaults_path=defaults_path,
            env_path=env_path,
            defaults=defaults,
            user_values=user_values,
            values=values,
        )
        config.validate()
        return config

    def require(self, name: str) -> str:
        value = self.values.get(name, "").strip()
        if not value:
            raise ValueError(f"missing deployment setting: {name}")
        return value

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default)

    def enabled(self, name: str, default: bool = False) -> bool:
        fallback = "1" if default else "0"
        value = self.get(name, fallback)
        if value not in {"0", "1"}:
            raise ValueError(f"{name} must be 0 or 1")
        return value == "1"

    @property
    def deploy_target(self) -> str:
        return self.get("DEPLOY_TARGET", "ssh")

    @property
    def ssh_target(self) -> str:
        return f"{self.require('SSH_USER')}@{self.require('SSH_HOST')}"

    @property
    def ssh_key(self) -> Path | None:
        value = self.get("SSH_KEY").strip()
        if not value:
            return None
        return Path(value).expanduser().resolve()

    @property
    def default_names(self) -> tuple[str, ...]:
        return tuple(self.defaults)

    def local_path(self, name: str) -> Path:
        path = Path(self.require(name)).expanduser()
        if not path.is_absolute():
            path = self.project_root / path
        return path.resolve()

    def remote_path(self, name: str) -> PurePosixPath:
        return PurePosixPath(self.require(name))

    def runtime_environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment.update(self.user_values)
        target_is_local = self.deploy_target == "local"
        embedding_port = self.require(
            "REMOTE_EMBEDDING_PORT" if target_is_local else "LOCAL_EMBEDDING_PORT"
        )
        telemetry_port = self.require(
            "REMOTE_TELEMETRY_PORT" if target_is_local else "LOCAL_TELEMETRY_PORT"
        )
        image_port = self.require("REMOTE_IMAGE_PORT" if target_is_local else "LOCAL_IMAGE_PORT")
        derived = {
            "AGENTFACTORY_INFERENCE_RUNTIME_MODE": self.get(
                "AGENTFACTORY_INFERENCE_RUNTIME_MODE", "external"
            ),
            "AGENTFACTORY_INFERENCE_CONNECTION_MODE": self.get(
                "AGENTFACTORY_INFERENCE_CONNECTION_MODE",
                "direct" if target_is_local else "ssh",
            ),
            "AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT": self.get(
                "AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT",
                f"http://127.0.0.1:{telemetry_port}/v1",
            ),
            "AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT": self.get(
                "AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT",
                f"http://127.0.0.1:{embedding_port}",
            ),
            "AGENTFACTORY_LOCAL_IMAGE_ENDPOINT": self.get(
                "AGENTFACTORY_LOCAL_IMAGE_ENDPOINT",
                f"http://127.0.0.1:{image_port}/v1",
            ),
            "AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT": self.get(
                "AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT",
                f"http://127.0.0.1:{telemetry_port}",
            ),
            "AGENTFACTORY_INFERENCE_SSH_HOST": self.get(
                "AGENTFACTORY_INFERENCE_SSH_HOST", self.get("SSH_HOST")
            ),
            "AGENTFACTORY_INFERENCE_SSH_PORT": self.get(
                "AGENTFACTORY_INFERENCE_SSH_PORT", self.get("SSH_PORT")
            ),
            "AGENTFACTORY_INFERENCE_SSH_USER": self.get(
                "AGENTFACTORY_INFERENCE_SSH_USER", self.get("SSH_USER")
            ),
            "AGENTFACTORY_INFERENCE_SSH_KEY": self.get(
                "AGENTFACTORY_INFERENCE_SSH_KEY", self.get("SSH_KEY")
            ),
        }
        for kind in ("CHAT", "EMBEDDING", "TELEMETRY", "IMAGE"):
            derived[f"AGENTFACTORY_INFERENCE_SSH_{kind}_LOCAL_PORT"] = self.get(
                f"AGENTFACTORY_INFERENCE_SSH_{kind}_LOCAL_PORT",
                self.require(f"LOCAL_{kind}_PORT"),
            )
            derived[f"AGENTFACTORY_INFERENCE_SSH_{kind}_REMOTE_PORT"] = self.get(
                f"AGENTFACTORY_INFERENCE_SSH_{kind}_REMOTE_PORT",
                self.require(f"REMOTE_{kind}_PORT"),
            )
        environment.update(derived)
        return environment

    def validate(self) -> None:
        if self.deploy_target not in {"local", "ssh"}:
            raise ValueError("DEPLOY_TARGET must be local or ssh")
        for name in REQUIRED_SETTINGS:
            self.require(name)
        if self.deploy_target == "ssh":
            for name in ("SSH_HOST", "SSH_PORT", "SSH_USER"):
                self.require(name)
            validate_port("SSH_PORT", self.require("SSH_PORT"))
            key = self.ssh_key
            if key is not None and not key.is_file():
                raise FileNotFoundError(f"SSH private key is not readable: {key}")
        for name in ("LLAMA_OFFICIAL_BUILD_NUMBER", "LLAMA_AMD_BASE_BUILD_NUMBER"):
            validate_non_negative_integer(name, self.require(name))
        for name in ("CHAT_ADMISSION_MAX_PENDING", "CHAT_ADMISSION_PER_SESSION_ACTIVE"):
            validate_positive_integer(name, self.require(name))
        for name in ("CHAT_ADMISSION_QUEUE_TIMEOUT_SECONDS", "CHAT_ADMISSION_PRIORITY_AGING_SECONDS"):
            validate_positive_number(name, self.require(name))
        if self.require("REMOTE_REPAIR_CA_TRUST") not in {"0", "1"}:
            raise ValueError("REMOTE_REPAIR_CA_TRUST must be 0 or 1")
        ports = [validate_port(name, self.require(name)) for name in LOCAL_PORT_NAMES]
        if len(set(ports)) != len(ports):
            raise ValueError("local inference ports must be different")
        for name in REMOTE_PATH_NAMES:
            path = self.remote_path(name)
            if not path.is_absolute() or str(path) == "/":
                raise ValueError(f"{name} must be an absolute non-root POSIX path")


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, source_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ASSIGNMENT.match(line)
        if match is None:
            raise ValueError(f"invalid assignment in {path}:{line_number}")
        name = match.group("name")
        values[name] = _parse_env_value(match.group("value"), path, line_number)
    return values


def _parse_env_value(value: str, path: Path, line_number: int) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if raw[0] in {"'", '"'}:
        quote = raw[0]
        if len(raw) < 2 or raw[-1] != quote:
            raise ValueError(f"unterminated quoted value in {path}:{line_number}")
        return raw[1:-1]
    comment_index = raw.find(" #")
    return (raw[:comment_index] if comment_index >= 0 else raw).rstrip()


def validate_port(name: str, value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer between 1 and 65535") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"{name} must be an integer between 1 and 65535")
    return port


def validate_non_negative_integer(name: str, value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if number < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return number


def validate_positive_integer(name: str, value: str) -> int:
    number = validate_non_negative_integer(name, value)
    if number == 0:
        raise ValueError(f"{name} must be greater than zero")
    return number


def validate_positive_number(name: str, value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number greater than zero") from exc
    if number <= 0:
        raise ValueError(f"{name} must be a number greater than zero")
    return number
