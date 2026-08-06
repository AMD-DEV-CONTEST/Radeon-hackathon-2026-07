from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from typing import Callable, Iterator, Sequence
import uuid

from deployment_config import DeploymentConfig


REMOTE_CONFIG_BASENAME = "fastagentfactory-deploy.env"
REMOTE_CONTROLLER_PATH = "/tmp/remote_runtime.sh"
REMOTE_CONFIG_PATH = f"/tmp/{REMOTE_CONFIG_BASENAME}"
MINIMAL_RUNTIME_FILES = (
    "agent_factory/__init__.py",
    "agent_factory/warnings.py",
    "agent_factory/env.py",
    "agent_factory/paths.py",
    "agent_factory/sqlite_runtime.py",
    "agent_factory/model_pool/config.py",
    "agent_factory/model_pool/schema.py",
    "agent_factory/model_pool/store.py",
    "agent_factory/model_pool/storage.py",
    "agent_factory/model_pool/download.py",
    "agent_factory/models/protocol.py",
    "deploy/configure_model_pool.py",
)


class CommandError(RuntimeError):
    pass


class RemoteDeployment:
    def __init__(self, config: DeploymentConfig) -> None:
        self.config = config
        self.project_root = config.project_root
        self.remote_controller = self.project_root / "deploy" / "remote_runtime.sh"
        self.ssh = require_command("ssh") if config.deploy_target == "ssh" else None
        self.scp = require_command("scp") if config.deploy_target == "ssh" else None
        self.rsync = None if os.name == "nt" else shutil.which("rsync")

    def ssh_arguments(self) -> list[str]:
        arguments = [
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-p",
            self.config.require("SSH_PORT"),
        ]
        if self.config.ssh_key is not None:
            arguments.extend(["-i", str(self.config.ssh_key)])
        return arguments

    def scp_arguments(self) -> list[str]:
        arguments = [
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-P",
            self.config.require("SSH_PORT"),
        ]
        if self.config.ssh_key is not None:
            arguments.extend(["-i", str(self.config.ssh_key)])
        return arguments

    def check_connectivity(self) -> None:
        if self.config.deploy_target == "ssh":
            log("Checking SSH connectivity")
            self.ssh_run("true")

    def upload_controller(self) -> None:
        if self.config.deploy_target == "local":
            return
        with (
            normalized_posix_text_file(
                self.remote_controller,
                "remote_runtime.sh",
            ) as remote_controller,
            normalized_posix_text_file(
                self.config.defaults_path,
                "defaults.env",
            ) as defaults,
            rendered_remote_config(self.config) as rendered_config,
        ):
            self.scp_upload(remote_controller, REMOTE_CONTROLLER_PATH)
            self.scp_upload(defaults, "/tmp/defaults.env")
            self.scp_upload(rendered_config, REMOTE_CONFIG_PATH)
        self.ssh_run("chmod", "700", REMOTE_CONTROLLER_PATH)
        self.ssh_run("chmod", "600", REMOTE_CONFIG_PATH)

    def remote_command(self, command: str, arguments: Sequence[str] = ()) -> None:
        if self.config.deploy_target == "ssh":
            self.ssh_run(
                REMOTE_CONTROLLER_PATH,
                command,
                REMOTE_CONFIG_PATH,
                *arguments,
            )
            return
        with rendered_remote_config(self.config) as rendered_config:
            local_config_dir = rendered_config.parent
            defaults_copy = local_config_dir / "defaults.env"
            shutil.copy2(self.config.defaults_path, defaults_copy)
            try:
                run(
                    [
                        "bash",
                        str(self.remote_controller),
                        command,
                        str(rendered_config),
                        *arguments,
                    ],
                    cwd=self.project_root,
                )
            finally:
                defaults_copy.unlink(missing_ok=True)

    def prepare_sources(self) -> None:
        validate_llama_source_tree(
            "official",
            self.config.local_path("LOCAL_LLAMA_OFFICIAL_DIR"),
        )
        validate_llama_source_tree(
            "amd",
            self.config.local_path("LOCAL_LLAMA_AMD_DIR"),
        )
        common = (self.project_root / "vendor" / "llama.cpp-common").resolve()
        for name in (
            "fastagentfactory-operator-trace.h",
            "fastagentfactory-operator-trace.cpp",
        ):
            require_file(common / name, f"bundled shared llama.cpp source is incomplete: {common}")
        validate_stable_diffusion_source_tree(
            self.config.local_path("LOCAL_STABLE_DIFFUSION_CPP_DIR"),
            self.config.require("STABLE_DIFFUSION_CPP_REVISION"),
        )

    def sync_sources(self) -> None:
        if self.rsync:
            self._sync_sources_with_rsync()
            return
        if self.config.deploy_target != "ssh":
            raise CommandError("rsync is required for DEPLOY_TARGET=local")
        log("rsync is unavailable; using cross-platform compressed archive synchronization")
        self._sync_minimal_runtime_archive()
        self._sync_tree_archive(
            "official llama.cpp",
            self.config.local_path("LOCAL_LLAMA_OFFICIAL_DIR"),
            str(self.config.remote_path("REMOTE_LLAMA_SOURCE_ROOT") / "official"),
            exclude=exclude_build_directories,
        )
        self._sync_tree_archive(
            "AMD llama.cpp",
            self.config.local_path("LOCAL_LLAMA_AMD_DIR"),
            str(self.config.remote_path("REMOTE_LLAMA_SOURCE_ROOT") / "amd"),
            exclude=exclude_build_directories,
        )
        self._sync_tree_archive(
            "shared llama.cpp operator trace",
            (self.project_root / "vendor" / "llama.cpp-common").resolve(),
            str(self.config.remote_path("REMOTE_LLAMA_SOURCE_ROOT") / "llama.cpp-common"),
        )
        self._sync_tree_archive(
            "stable-diffusion.cpp",
            self.config.local_path("LOCAL_STABLE_DIFFUSION_CPP_DIR"),
            self.config.require("REMOTE_STABLE_DIFFUSION_CPP_DIR"),
            exclude=exclude_stable_diffusion_generated_directories,
        )

    def ssh_run(self, *remote_arguments: str) -> None:
        if self.ssh is None:
            raise CommandError("SSH is unavailable for a local deployment target")
        remote_command = " ".join(shlex.quote(argument) for argument in remote_arguments)
        run(
            [
                self.ssh,
                *self.ssh_arguments(),
                self.config.ssh_target,
                remote_command,
            ],
            cwd=self.project_root,
        )

    def ssh_script(self, script: str) -> None:
        self.ssh_run("sh", "-c", script)

    def scp_upload(self, source: Path, remote_path: str) -> None:
        if self.scp is None:
            raise CommandError("SCP is unavailable for a local deployment target")
        run(
            [
                self.scp,
                *self.scp_arguments(),
                str(source),
                f"{self.config.ssh_target}:{remote_path}",
            ],
            cwd=self.project_root,
        )

    def _sync_sources_with_rsync(self) -> None:
        target_prefix = f"{self.config.ssh_target}:" if self.config.deploy_target == "ssh" else ""
        transport = self._rsync_transport()
        remote_project_root = self.config.require("REMOTE_PROJECT_ROOT")
        if self.config.deploy_target == "local" and same_path(
            self.project_root, Path(remote_project_root)
        ):
            log("Using the current FastAgentFactory checkout as the local inference runtime")
        else:
            log(f"Synchronizing minimal inference runtime to {target_prefix}{remote_project_root}")
            command = [
                self.rsync or "rsync",
                "-az",
                "--delete",
                "--delete-excluded",
                "--prune-empty-dirs",
                *transport,
                "--include",
                "/agent_factory/",
                "--include",
                "/agent_factory/__init__.py",
                "--include",
                "/agent_factory/warnings.py",
                "--include",
                "/agent_factory/env.py",
                "--include",
                "/agent_factory/paths.py",
                "--include",
                "/agent_factory/sqlite_runtime.py",
                "--include",
                "/agent_factory/local_inference/",
                "--exclude",
                "/agent_factory/local_inference/__init__.py",
                "--include",
                "/agent_factory/local_inference/*.py",
                "--include",
                "/agent_factory/model_pool/",
                "--exclude",
                "/agent_factory/model_pool/__init__.py",
                "--include",
                "/agent_factory/model_pool/config.py",
                "--include",
                "/agent_factory/model_pool/schema.py",
                "--include",
                "/agent_factory/model_pool/store.py",
                "--include",
                "/agent_factory/model_pool/storage.py",
                "--include",
                "/agent_factory/model_pool/download.py",
                "--include",
                "/agent_factory/models/",
                "--exclude",
                "/agent_factory/models/__init__.py",
                "--include",
                "/agent_factory/models/protocol.py",
                "--include",
                "/deploy/",
                "--include",
                "/deploy/configure_model_pool.py",
                "--include",
                "/deploy/kernel-catalogs/",
                "--include",
                "/deploy/kernel-catalogs/*.json",
                "--exclude",
                "*",
                f"{self.project_root}{os.sep}",
                f"{target_prefix}{remote_project_root}/",
            ]
            run(command, cwd=self.project_root)
        self._rsync_tree(
            "official llama.cpp",
            self.config.local_path("LOCAL_LLAMA_OFFICIAL_DIR"),
            str(self.config.remote_path("REMOTE_LLAMA_SOURCE_ROOT") / "official"),
            ["--exclude", "build*/"],
        )
        self._rsync_tree(
            "AMD llama.cpp",
            self.config.local_path("LOCAL_LLAMA_AMD_DIR"),
            str(self.config.remote_path("REMOTE_LLAMA_SOURCE_ROOT") / "amd"),
            ["--exclude", "build*/"],
        )
        self._rsync_tree(
            "shared llama.cpp operator trace",
            (self.project_root / "vendor" / "llama.cpp-common").resolve(),
            str(self.config.remote_path("REMOTE_LLAMA_SOURCE_ROOT") / "llama.cpp-common"),
        )
        self._rsync_tree(
            "stable-diffusion.cpp",
            self.config.local_path("LOCAL_STABLE_DIFFUSION_CPP_DIR"),
            self.config.require("REMOTE_STABLE_DIFFUSION_CPP_DIR"),
            ["--exclude", ".git/", "--exclude", "/build*/"],
        )

    def _rsync_tree(
        self,
        label: str,
        source: Path,
        target: str,
        extra_arguments: Sequence[str] = (),
    ) -> None:
        if self.config.deploy_target == "local" and same_path(source, Path(target)):
            log(f"Using bundled {label} source in place")
            return
        log(f"Synchronizing bundled {label} source")
        target_prefix = f"{self.config.ssh_target}:" if self.config.deploy_target == "ssh" else ""
        run(
            [
                self.rsync or "rsync",
                "-az",
                "--delete",
                *self._rsync_transport(),
                *extra_arguments,
                f"{source}{os.sep}",
                f"{target_prefix}{target}/",
            ],
            cwd=self.project_root,
        )

    def _rsync_transport(self) -> list[str]:
        if self.config.deploy_target != "ssh":
            return []
        ssh_parts = ["ssh", *self.ssh_arguments()]
        return ["-e", " ".join(shlex.quote(part) for part in ssh_parts)]

    def _sync_minimal_runtime_archive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="faf-runtime-sync-") as temporary:
            staging = Path(temporary) / "runtime"
            for relative in MINIMAL_RUNTIME_FILES:
                copy_file(self.project_root / relative, staging / relative)
            for source in (
                self.project_root / "agent_factory" / "local_inference",
                self.project_root / "deploy" / "kernel-catalogs",
            ):
                for file_path in source.glob("*.py" if source.name == "local_inference" else "*.json"):
                    if file_path.name == "__init__.py":
                        continue
                    copy_file(file_path, staging / file_path.relative_to(self.project_root))
            self._sync_tree_archive(
                "minimal inference runtime",
                staging,
                self.config.require("REMOTE_PROJECT_ROOT"),
            )

    def _sync_tree_archive(
        self,
        label: str,
        source: Path,
        target: str,
        exclude: Callable[[Path, bool], bool] | None = None,
    ) -> None:
        validate_remote_sync_target(target)
        log(f"Synchronizing {label} with a compressed archive")
        archive_name = f"faf-sync-{uuid.uuid4().hex}.tar.gz"
        with tempfile.TemporaryDirectory(prefix="faf-source-sync-") as temporary:
            archive = Path(temporary) / archive_name
            create_source_archive(source, archive, exclude=exclude)
            remote_archive = f"/tmp/{archive_name}"
            self.scp_upload(archive, remote_archive)
            script = build_remote_archive_install_script(target, remote_archive)
            self.ssh_script(script)


@contextmanager
def rendered_remote_config(config: DeploymentConfig) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="fastagentfactory-deploy-") as temporary:
        path = Path(temporary) / REMOTE_CONFIG_BASENAME
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            for setting in config.default_names:
                stream.write(f"{setting}={shlex.quote(config.get(setting))}\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        yield path


@contextmanager
def normalized_posix_text_file(source: Path, name: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="fastagentfactory-posix-text-") as temporary:
        target = Path(temporary) / name
        text = source.read_text(encoding="utf-8")
        target.write_text(text, encoding="utf-8", newline="\n")
        yield target


def create_source_archive(
    source: Path,
    archive: Path,
    *,
    exclude: Callable[[Path, bool], bool] | None = None,
) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"sync source directory is missing: {source}")

    def archive_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        relative = Path(info.name)
        return None if exclude is not None and exclude(relative, info.isdir()) else info

    with tarfile.open(archive, "w:gz", dereference=False) as bundle:
        for child in sorted(source.iterdir(), key=lambda item: item.name.casefold()):
            bundle.add(child, arcname=child.name, recursive=True, filter=archive_filter)


def exclude_build_directories(relative: Path, entry_is_directory: bool) -> bool:
    directory_parts = relative.parts if entry_is_directory else relative.parts[:-1]
    return any(part.startswith("build") for part in directory_parts)


def exclude_stable_diffusion_generated_directories(
    relative: Path,
    entry_is_directory: bool,
) -> bool:
    directory_parts = relative.parts if entry_is_directory else relative.parts[:-1]
    return ".git" in directory_parts or (
        bool(directory_parts) and directory_parts[0].startswith("build")
    )


def build_remote_archive_install_script(target: str, archive: str) -> str:
    operation_id = uuid.uuid4().hex
    quoted_target = shlex.quote(target)
    quoted_archive = shlex.quote(archive)
    staging = shlex.quote(f"{target}.incoming-{operation_id}")
    backup = shlex.quote(f"{target}.previous-{operation_id}")
    return (
        f"set -eu; staging={staging}; backup={backup}; target={quoted_target}; "
        'cleanup() { rm -rf -- "$staging"; rm -f -- '
        f"{quoted_archive};"
        ' }; trap cleanup EXIT HUP INT TERM; rm -rf -- "$staging" "$backup"; '
        'mkdir -p -- "$staging"; '
        f'tar -xzf {quoted_archive} -C "$staging"; '
        'if [ -e "$target" ]; then mv -- "$target" "$backup"; fi; '
        'if mv -- "$staging" "$target"; then rm -rf -- "$backup"; '
        'else if [ -e "$backup" ]; then mv -- "$backup" "$target"; fi; exit 1; fi; '
        "trap - EXIT HUP INT TERM; "
        f"rm -f -- {quoted_archive}"
    )


def validate_remote_sync_target(target: str) -> None:
    normalized = PurePosixPath(target)
    if not normalized.is_absolute() or str(normalized) == "/":
        raise ValueError(f"remote sync target must be an absolute non-root path: {target}")


def validate_llama_source_tree(implementation: str, source: Path) -> None:
    for relative in (
        "CMakeLists.txt",
        "cmake/build-info.cmake",
        "common/CMakeLists.txt",
        "common/build-info.cpp.in",
        "common/build-info.h",
        ".fastagentfactory-kernel-catalog.json",
    ):
        require_file(
            source / relative,
            f"bundled {implementation} llama.cpp source is incomplete: {source / relative}",
        )


def validate_stable_diffusion_source_tree(source: Path, expected_revision: str) -> None:
    for relative in (
        "CMakeLists.txt",
        "ggml/CMakeLists.txt",
        "thirdparty/libwebm/build/cxx_flags.cmake",
        "thirdparty/libwebm/build/msvc_runtime.cmake",
        "thirdparty/libwebm/build/x86-mingw-gcc.cmake",
        "thirdparty/libwebm/build/x86_64-mingw-gcc.cmake",
        ".fastagentfactory-revision",
    ):
        require_file(
            source / relative,
            f"bundled stable-diffusion.cpp source is incomplete: {source / relative}",
        )
    actual_revision = (source / ".fastagentfactory-revision").read_text(
        encoding="utf-8"
    ).strip()
    if actual_revision != expected_revision:
        raise ValueError(
            "bundled stable-diffusion.cpp revision does not match "
            "STABLE_DIFFUSION_CPP_REVISION"
        )


def copy_file(source: Path, target: Path) -> None:
    require_file(source, f"runtime sync source is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def require_file(path: Path, message: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(message)


def require_command(name: str) -> str:
    command = shutil.which(name)
    if command is None:
        raise FileNotFoundError(f"{name} is required but was not found on PATH")
    return command


def same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve() == right.expanduser().resolve()


def run(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> None:
    completed = subprocess.run(
        list(arguments),
        cwd=cwd,
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        rendered = " ".join(shlex.quote(str(argument)) for argument in arguments)
        raise CommandError(f"command failed with exit code {completed.returncode}: {rendered}")


def log(message: str) -> None:
    print(f"[deploy] {message}", flush=True)
