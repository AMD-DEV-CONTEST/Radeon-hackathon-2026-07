from __future__ import annotations

import os
from pathlib import Path
import platform
import sys
from typing import Sequence

from deployment_config import DeploymentConfig
from remote_deployment import CommandError, RemoteDeployment, log, require_command, run
from web_runtime import WebRuntimeSupervisor


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_REMOTE_COMMANDS = {
    "models",
    "image-models",
    "build-llama",
    "build-sd",
    "switch-llama",
    "list-llama-builds",
    "rollback-llama",
    "restart",
    "down",
    "status",
    "doctor",
    "logs",
}


def main(arguments: Sequence[str] | None = None) -> int:
    raw_arguments = list(arguments if arguments is not None else sys.argv[1:])
    command = raw_arguments.pop(0) if raw_arguments else "up"
    start_web = "--no-web" not in raw_arguments
    command_arguments = [argument for argument in raw_arguments if argument != "--no-web"]
    try:
        ensure_generated_user_configuration()
        config = DeploymentConfig.load(PROJECT_ROOT)
        if command == "web":
            WebRuntimeSupervisor(config).run()
            return 0
        deployment = RemoteDeployment(config)
        if command == "up":
            check_bootstrap_prerequisites(config)
            if start_web:
                check_web_prerequisites()
            bootstrap(config, deployment)
            if start_web:
                log("Starting the local Web application and inference connection")
                WebRuntimeSupervisor(config).run()
            else:
                log("Inference-node deployment is ready; Web startup was skipped")
            return 0
        if command == "bootstrap":
            check_bootstrap_prerequisites(config)
            bootstrap(config, deployment)
            return 0
        if command == "sync":
            deployment.prepare_sources()
            deployment.upload_controller()
            deployment.remote_command("prepare-host")
            deployment.sync_sources()
            return 0
        if command in SUPPORTED_REMOTE_COMMANDS:
            deployment.upload_controller()
            deployment.remote_command(command, command_arguments)
            return 0
        supported = ", ".join(
            ["up", "bootstrap", "sync", *sorted(SUPPORTED_REMOTE_COMMANDS)]
        )
        raise ValueError(f"unsupported command: {command}; expected one of: {supported}")
    except KeyboardInterrupt:
        print("\nDeployment interrupted.", file=sys.stderr)
        return 130
    except (CommandError, FileNotFoundError, OSError, TimeoutError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def ensure_generated_user_configuration() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        raise FileNotFoundError(
            f"deployment config is missing; copy {PROJECT_ROOT / '.env.example'} to {env_path}"
        )
    run(
        [
            sys.executable,
            str(PROJECT_ROOT / "deploy" / "configure_user_env.py"),
            "--env-file",
            str(env_path),
        ],
        cwd=PROJECT_ROOT,
    )


def check_bootstrap_prerequisites(config: DeploymentConfig) -> None:
    require_command("git")
    require_command("uv")
    if config.deploy_target == "ssh":
        require_command("ssh")
        require_command("scp")
        return
    if platform.system() != "Linux":
        raise ValueError("DEPLOY_TARGET=local requires a Linux host with ROCm device access")
    require_command("bash")
    require_command("rsync")


def check_web_prerequisites() -> None:
    require_command("node")
    require_command("npm")


def bootstrap(config: DeploymentConfig, deployment: RemoteDeployment) -> None:
    deployment.check_connectivity()
    deployment.prepare_sources()
    deployment.upload_controller()
    deployment.remote_command("prepare-host")
    deployment.sync_sources()
    deployment.upload_controller()
    deployment.remote_command("bootstrap")
    configure_local_profiles(config)
    log("Deployment bootstrap completed")


def configure_local_profiles(config: DeploymentConfig) -> None:
    uv = require_command("uv")
    log("Preparing local Python environment")
    environment = config.runtime_environment()
    command = [uv, "sync", "--extra", "web"]
    python_request = local_python_request()
    if python_request is not None:
        command.extend(["--python", python_request])
    run(command, cwd=PROJECT_ROOT, environment=environment)
    python_bin = virtualenv_python(PROJECT_ROOT)
    if not python_bin.is_file():
        raise FileNotFoundError(f"local Python environment was not created: {python_bin}")
    arguments = [
        str(python_bin),
        str(PROJECT_ROOT / "deploy" / "configure_model_pool.py"),
        "--mode",
        "client",
        "--prune-unconfigured-models",
        "--store-path",
        str(PROJECT_ROOT / ".agentfactory" / "model_pool" / "factory.sqlite"),
        "--chat-profile-id",
        config.require("CHAT_PROFILE_ID"),
        "--chat-served-model-name",
        config.require("CHAT_SERVED_MODEL_NAME"),
        "--chat-mmproj-path",
        f"{config.require('REMOTE_MODEL_ROOT')}/gguf/{config.require('CHAT_MMPROJ_FILENAME')}",
        "--chat-revision",
        config.require("CHAT_MODEL_REVISION"),
        "--chat-checksum",
        config.require("CHAT_MODEL_SHA256"),
        "--chat-native-context-tokens",
        config.require("CHAT_NATIVE_CONTEXT_TOKENS"),
        "--chat-yarn-max-context-tokens",
        config.require("CHAT_YARN_MAX_CONTEXT_TOKENS"),
        "--context-size",
        config.require("CHAT_CONTEXT_SIZE"),
        "--max-output-tokens",
        config.require("CHAT_MAX_OUTPUT_TOKENS"),
        "--compression-threshold",
        config.require("CHAT_COMPRESSION_THRESHOLD"),
        "--gpu-layers",
        config.require("CHAT_GPU_LAYERS"),
        "--parallel-slots",
        config.require("CHAT_PARALLEL_SLOTS"),
        "--cache-type-k",
        config.require("CHAT_CACHE_TYPE_K"),
        "--cache-type-v",
        config.require("CHAT_CACHE_TYPE_V"),
        boolean_argument(config.enabled("CHAT_FLASH_ATTENTION", True), "flash-attention"),
        boolean_argument(config.enabled("CHAT_MTP_ENABLED"), "chat-mtp-enabled"),
        "--chat-mtp-max-draft-tokens",
        config.get("CHAT_MTP_MAX_DRAFT_TOKENS", "3"),
        "--chat-mtp-min-draft-tokens",
        config.get("CHAT_MTP_MIN_DRAFT_TOKENS", "0"),
        "--chat-mtp-min-acceptance-probability",
        config.get("CHAT_MTP_MIN_ACCEPTANCE_PROBABILITY", "0.0"),
        boolean_argument(
            config.enabled("CHAT_MTP_BACKEND_SAMPLING", True),
            "chat-mtp-backend-sampling",
        ),
        boolean_argument(
            config.enabled("CHAT_REASONING_SUPPORTED", True),
            "reasoning-supported",
        ),
        "--embedding-profile-id",
        config.require("EMBEDDING_PROFILE_ID"),
        "--embedding-served-model-name",
        config.require("EMBEDDING_SERVED_MODEL_NAME"),
        "--embedding-revision",
        config.require("EMBEDDING_MODEL_REVISION"),
        "--embedding-dimensions",
        config.require("EMBEDDING_DIMENSIONS"),
        boolean_argument(
            config.enabled("EMBEDDING_TRUST_REMOTE_CODE"),
            "embedding-trust-remote-code",
        ),
        "--image-profile-id",
        config.require("IMAGE_PROFILE_ID"),
        "--image-served-model-name",
        config.require("IMAGE_SERVED_MODEL_NAME"),
        "--image-vae-path",
        (
            f"{config.require('REMOTE_MODEL_ROOT')}/image/flux1-dev-q4_0/"
            f"{config.require('IMAGE_VAE_FILENAME')}"
        ),
        "--image-clip-l-path",
        (
            f"{config.require('REMOTE_MODEL_ROOT')}/image/flux1-dev-q4_0/"
            f"{config.require('IMAGE_CLIP_L_FILENAME')}"
        ),
        "--image-t5xxl-path",
        (
            f"{config.require('REMOTE_MODEL_ROOT')}/image/flux1-dev-q4_0/"
            f"{config.require('IMAGE_T5XXL_FILENAME')}"
        ),
        boolean_argument(config.enabled("IMAGE_ENABLED", True), "image-enabled"),
        boolean_argument(
            config.enabled("IMAGE_DIFFUSION_FLASH_ATTENTION", True),
            "image-diffusion-flash-attention",
        ),
        boolean_argument(config.enabled("IMAGE_EAGER_LOAD", True), "image-eager-load"),
        boolean_argument(config.enabled("IMAGE_CLIP_ON_CPU", True), "image-clip-on-cpu"),
        boolean_argument(config.enabled("IMAGE_VAE_TILING", True), "image-vae-tiling"),
        "--image-default-width",
        config.get("IMAGE_DEFAULT_WIDTH", "1024"),
        "--image-default-height",
        config.get("IMAGE_DEFAULT_HEIGHT", "1024"),
        "--image-default-steps",
        config.get("IMAGE_DEFAULT_STEPS", "20"),
        "--image-default-cfg-scale",
        config.get("IMAGE_DEFAULT_CFG_SCALE", "1.0"),
        "--image-residency-policy",
        config.get("IMAGE_RESIDENCY_POLICY", "exclusive"),
        "--image-timeout-seconds",
        config.get("IMAGE_TIMEOUT_SECONDS", "900"),
    ]
    run(arguments, cwd=PROJECT_ROOT, environment=environment)


def virtualenv_python(project_root: Path) -> Path:
    if os.name == "nt":
        return project_root / ".venv" / "Scripts" / "python.exe"
    return project_root / ".venv" / "bin" / "python"


def local_python_request() -> str | None:
    if platform.system() != "Windows":
        return None
    if platform.machine().lower() not in {"arm64", "aarch64"}:
        return None
    return "cpython-3.11-windows-x86_64-none"


def boolean_argument(enabled: bool, name: str) -> str:
    return f"--{name}" if enabled else f"--no-{name}"


if __name__ == "__main__":
    raise SystemExit(main())
