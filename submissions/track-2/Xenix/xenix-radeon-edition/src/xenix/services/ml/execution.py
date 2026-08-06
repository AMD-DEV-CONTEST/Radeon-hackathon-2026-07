from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from ...config import package_root
from .contracts import TaskLogEntry
from .worker_settings import MLWorkerConfig


WORKER_BUNDLE_VERSION = "source-v1"
PATH_KEYS = {
    "dataset_source_path",
    "trained_model_artifact_path",
    "holdout_artifact_path",
    "absolute_path",
}


class LocalMLWorkerRunner:
    def run(
        self,
        entrypoint: Callable[[str], None],
        task_dir: Path,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> int:
        context = get_context("spawn")
        process = context.Process(target=entrypoint, args=(str(task_dir),))
        process.start()
        while process.is_alive():
            if cancel_requested is not None and cancel_requested():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join()
                return -15
            process.join(timeout=0.1)
        return process.exitcode or 0


class MLWorkerRunner(LocalMLWorkerRunner):
    """Backward-compatible local runner name used by existing tests."""


class OpenSshClient:
    def __init__(
        self,
        worker: MLWorkerConfig,
        *,
        ssh_command: str = "ssh",
        scp_command: str = "scp",
    ) -> None:
        self._worker = worker
        self._ssh_command = ssh_command
        self._scp_command = scp_command

    def run(
        self,
        remote_command: str,
        *,
        check: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [self._ssh_command, *self._ssh_options(), self._worker.target, remote_command]
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode != 0:
            raise RuntimeError(_format_process_error("ssh", result))
        return result

    def upload(self, local_path: Path, remote_path: str) -> None:
        parent = _posix_parent(remote_path)
        if parent:
            self.run(f"mkdir -p {_sh_quote(parent)}", check=True)
        command = [
            self._scp_command,
            *self._scp_options(),
            str(local_path),
            f"{self._worker.target}:{remote_path}",
        ]
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(_format_process_error("scp upload", result))

    def upload_tree(self, local_path: Path, remote_parent: str) -> None:
        self.run(f"mkdir -p {_sh_quote(remote_parent)}", check=True)
        command = [
            self._scp_command,
            *self._scp_options(),
            "-r",
            str(local_path),
            f"{self._worker.target}:{remote_parent}",
        ]
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(_format_process_error("scp upload tree", result))

    def download(self, remote_path: str, local_path: Path) -> bool:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._scp_command,
            *self._scp_options(),
            f"{self._worker.target}:{remote_path}",
            str(local_path),
        ]
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            return False
        return True

    def download_tree_contents(self, remote_dir: str, local_dir: Path) -> None:
        local_dir.mkdir(parents=True, exist_ok=True)
        command = [
            self._scp_command,
            *self._scp_options(),
            "-r",
            f"{self._worker.target}:{remote_dir}/.",
            str(local_dir),
        ]
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(_format_process_error("scp download tree", result))

    def _ssh_options(self) -> list[str]:
        options: list[str] = ["-o", "BatchMode=yes"]
        include_connection_options = bool(self._worker.host or not self._worker.ssh_alias)
        if self._worker.port and include_connection_options:
            options.extend(["-p", str(self._worker.port)])
        if self._worker.identity_file_path and include_connection_options:
            options.extend(["-i", self._worker.identity_file_path])
        return options

    def _scp_options(self) -> list[str]:
        options: list[str] = ["-o", "BatchMode=yes"]
        include_connection_options = bool(self._worker.host or not self._worker.ssh_alias)
        if self._worker.port and include_connection_options:
            options.extend(["-P", str(self._worker.port)])
        if self._worker.identity_file_path and include_connection_options:
            options.extend(["-i", self._worker.identity_file_path])
        return options


class SshMLWorkerRunner:
    def __init__(
        self,
        worker: MLWorkerConfig,
        *,
        client: OpenSshClient | None = None,
    ) -> None:
        self._worker = worker
        self._client = client or OpenSshClient(worker)

    def run(
        self,
        entrypoint: Callable[[str], None],
        task_dir: Path,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> int:
        task_dir = Path(task_dir)
        self._worker = self._worker.model_copy(update={"remote_root": self._resolve_remote_root()})
        remote_task_dir = _remote_task_dir(self._worker, task_dir.name)
        path_map: dict[str, str] = {}
        try:
            self._append_log(task_dir, "INFO", f"Selected SSH worker '{self._worker.display_name}'.")
            self._prepare_remote_task_dir(remote_task_dir)
            self._ensure_worker_bundle()
            request_payload = json.loads((task_dir / "request.json").read_text(encoding="utf-8"))
            rewritten_payload = self._stage_request_paths(request_payload, remote_task_dir, path_map)
            rewritten_request = task_dir / "request.remote.json"
            rewritten_request.write_text(
                json.dumps(rewritten_payload, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            self._client.upload(rewritten_request, f"{remote_task_dir}/request.json")
            if cancel_requested is not None and cancel_requested():
                return -15
            result = self._client.run(
                self._remote_run_command(entrypoint, remote_task_dir),
                check=False,
            )
            self._download_remote_outputs(remote_task_dir, task_dir)
            self._rewrite_local_result(task_dir, remote_task_dir)
            if cancel_requested is not None and cancel_requested():
                self._client.run(f"pkill -f {_sh_quote(remote_task_dir)}", check=False)
                return -15
            return result.returncode
        except Exception as exc:
            self._append_log(task_dir, "ERROR", f"SSH worker failed: {exc}")
            self._write_failure_result(task_dir, str(exc))
            return 1

    def _resolve_remote_root(self) -> str:
        remote_root = self._worker.remote_root.strip()
        if not remote_root.startswith("~"):
            return remote_root
        script = (
            f"{_sh_quote(self._worker.python_command)} - <<'PY'\n"
            "from pathlib import Path\n"
            f"print(Path({json.dumps(remote_root)}).expanduser().as_posix())\n"
            "PY"
        )
        result = self._client.run(script, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[-1]
        return remote_root

    def _prepare_remote_task_dir(self, remote_task_dir: str) -> None:
        self._client.run(
            " && ".join(
                [
                    f"mkdir -p {_sh_quote(remote_task_dir)}",
                    f"mkdir -p {_sh_quote(remote_task_dir + '/input')}",
                    f"mkdir -p {_sh_quote(remote_task_dir + '/output')}",
                    f"mkdir -p {_sh_quote(remote_task_dir + '/models')}",
                ]
            ),
            check=True,
        )

    def _ensure_worker_bundle(self) -> None:
        source_root = _worker_source_root()
        remote_bundle_parent = _remote_bundle_parent(self._worker)
        remote_bundle_root = f"{remote_bundle_parent}/xenix"
        marker = f"{remote_bundle_root}/.xenix-worker-bundle-{WORKER_BUNDLE_VERSION}"
        exists = self._client.run(f"test -f {_sh_quote(marker)}", check=False)
        if exists.returncode == 0:
            return
        self._client.run(f"rm -rf {_sh_quote(remote_bundle_root)}", check=False)
        self._client.upload_tree(source_root, remote_bundle_parent)
        self._client.run(f"touch {_sh_quote(marker)}", check=True)

    def _stage_request_paths(
        self,
        payload: Any,
        remote_task_dir: str,
        path_map: dict[str, str],
    ) -> Any:
        if isinstance(payload, dict):
            rewritten: dict[str, Any] = {}
            for key, value in payload.items():
                if key in PATH_KEYS and isinstance(value, str) and value.strip():
                    rewritten[key] = self._remote_path_for_local(value, remote_task_dir, path_map)
                else:
                    rewritten[key] = self._stage_request_paths(value, remote_task_dir, path_map)
            return rewritten
        if isinstance(payload, list):
            return [self._stage_request_paths(item, remote_task_dir, path_map) for item in payload]
        return payload

    def _remote_path_for_local(self, value: str, remote_task_dir: str, path_map: dict[str, str]) -> str:
        local_path = Path(value)
        if not local_path.exists():
            return value
        resolved = str(local_path.resolve())
        existing = path_map.get(resolved)
        if existing is not None:
            return existing
        digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
        remote_path = f"{remote_task_dir}/input/staged/{digest}-{local_path.name}"
        self._client.upload(local_path, remote_path)
        path_map[resolved] = remote_path
        return remote_path

    def _remote_run_command(self, entrypoint: Callable[[str], None], remote_task_dir: str) -> str:
        entrypoint_name = _entrypoint_name(entrypoint)
        remote_bundle_parent = _remote_bundle_parent(self._worker)
        python = self._worker.python_command
        return (
            f"PYTHONPATH={_sh_quote(remote_bundle_parent)} "
            f"{_sh_quote(python)} -m xenix.services.ml.remote_worker "
            f"{_sh_quote(entrypoint_name)} {_sh_quote(remote_task_dir)}"
        )

    def _download_remote_outputs(self, remote_task_dir: str, task_dir: Path) -> None:
        self._client.download(f"{remote_task_dir}/result.json", task_dir / "result.json")
        remote_logs_downloaded = self._client.download(f"{remote_task_dir}/logs.jsonl", task_dir / "logs.remote.jsonl")
        if remote_logs_downloaded:
            with (task_dir / "logs.jsonl").open("a", encoding="utf-8") as target:
                for line in (task_dir / "logs.remote.jsonl").read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        target.write(line)
                        target.write("\n")
        self._client.download(f"{remote_task_dir}/input/holdout.pkl", task_dir / "input" / "holdout.pkl")
        for name in ("output", "models"):
            self._client.download_tree_contents(f"{remote_task_dir}/{name}", task_dir / name)

    def _rewrite_local_result(self, task_dir: Path, remote_task_dir: str) -> None:
        result_path = task_dir / "result.json"
        if not result_path.exists():
            return
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        rewritten = _rewrite_remote_paths(payload, remote_task_dir, str(task_dir).replace("\\", "/"))
        result_path.write_text(
            json.dumps(rewritten, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def _write_failure_result(self, task_dir: Path, message: str) -> None:
        request_path = task_dir / "request.json"
        task_id = task_dir.name
        if request_path.exists():
            try:
                payload = json.loads(request_path.read_text(encoding="utf-8"))
                task_id = str(payload.get("task_id") or task_id)
            except json.JSONDecodeError:
                pass
        (task_dir / "result.json").write_text(
            json.dumps({"task_id": task_id, "error_summary": message}, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def _append_log(self, task_dir: Path, level: str, message: str) -> None:
        path = task_dir / "logs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(TaskLogEntry(level=level, message=message).model_dump_json())
            handle.write("\n")


def _entrypoint_name(entrypoint: Callable[[str], None]) -> str:
    name = getattr(entrypoint, "__name__", "")
    if name in {
        "run_fit_task",
        "run_hyperparameter_tuning_task",
        "run_evaluate_task",
        "run_apply_task",
    }:
        return name
    raise ValueError(f"Unsupported ML worker entrypoint '{name}'.")


def _remote_root(worker: MLWorkerConfig) -> str:
    return worker.remote_root.rstrip("/")


def _remote_bundle_parent(worker: MLWorkerConfig) -> str:
    return f"{_remote_root(worker)}/worker-bundles/{WORKER_BUNDLE_VERSION}"


def _remote_task_dir(worker: MLWorkerConfig, task_id: str) -> str:
    return f"{_remote_root(worker)}/tasks/{task_id}"


def _rewrite_remote_paths(value: Any, remote_task_dir: str, local_task_dir: str) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite_remote_paths(item, remote_task_dir, local_task_dir) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_remote_paths(item, remote_task_dir, local_task_dir) for item in value]
    if isinstance(value, str) and value.startswith(remote_task_dir):
        return value.replace(remote_task_dir, local_task_dir, 1).replace("/", os.sep)
    return value


def _worker_source_root() -> Path:
    frozen_source = Path(getattr(sys, "_MEIPASS", "")) / "xenix_worker_source" / "xenix"
    if frozen_source.exists():
        return frozen_source
    root = package_root()
    if not (root / "services" / "ml").exists():
        raise RuntimeError("Unable to locate Xenix worker source bundle.")
    return root


def _posix_parent(path: str) -> str:
    normalized = path.rstrip("/")
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _format_process_error(label: str, result: subprocess.CompletedProcess[str]) -> str:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    detail = stderr or stdout or f"exit code {result.returncode}"
    return f"{label} failed: {detail}"
