from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import IO, Sequence
import urllib.error
import urllib.request

from deployment_config import DeploymentConfig, validate_port
from remote_deployment import CommandError, require_command, run


WEB_SEARCH_MCP_REPOSITORY = "https://github.com/LiuYan-89937/BigOpenLLMSearch.git"
BACKEND_PORT = 8000
FRONTEND_PORT = 3000
BACKEND_HEALTH_URL = f"http://127.0.0.1:{BACKEND_PORT}/health"
FRONTEND_HEALTH_URL = f"http://127.0.0.1:{FRONTEND_PORT}/"


@dataclass(slots=True)
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]
    log_stream: IO[str] | None = None
    reader: threading.Thread | None = None

    @classmethod
    def start_logged(
        cls,
        name: str,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: dict[str, str],
        log_path: Path,
    ) -> "ManagedProcess":
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = log_path.open("a", encoding="utf-8", newline="")
        process = subprocess.Popen(
            list(arguments),
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **process_group_options(),
        )
        managed = cls(name=name, process=process, log_stream=stream)
        managed.reader = threading.Thread(
            target=managed._copy_output,
            name=f"{name}-log-reader",
            daemon=True,
        )
        managed.reader.start()
        return managed

    def _copy_output(self) -> None:
        if self.process.stdout is None or self.log_stream is None:
            return
        for line in self.process.stdout:
            self.log_stream.write(line)
            self.log_stream.flush()
            print(line, end="", flush=True)

    def stop(self, grace_seconds: int) -> None:
        if self.process.poll() is not None:
            self.close_log()
            return
        print(f"Stopping {self.name} service...", flush=True)
        terminate_process_tree(self.process, grace_seconds)
        self.close_log()

    def close_log(self) -> None:
        if self.reader is not None:
            self.reader.join(timeout=2)
            self.reader = None
        if self.log_stream is not None:
            self.log_stream.close()
            self.log_stream = None


@dataclass(slots=True)
class WebRuntimeSupervisor:
    config: DeploymentConfig
    environment: dict[str, str] = field(init=False)
    tunnel: subprocess.Popen[bytes] | None = field(default=None, init=False)
    backend: ManagedProcess | None = field(default=None, init=False)
    frontend: ManagedProcess | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.environment = self.config.runtime_environment()

    @property
    def project_root(self) -> Path:
        return self.config.project_root

    @property
    def frontend_dir(self) -> Path:
        return self.project_root / "web_frontend" / "frontend"

    @property
    def python_bin(self) -> Path:
        relative = (
            Path(".venv") / "Scripts" / "python.exe"
            if os.name == "nt"
            else Path(".venv") / "bin" / "python"
        )
        return self.project_root / relative

    @property
    def logs_dir(self) -> Path:
        return self.project_root / ".agentfactory" / "logs"

    def run(self) -> None:
        print("===================================")
        print("FastAgentFactory Web")
        print("===================================")
        self._check_configuration()
        require_available_port("Backend", BACKEND_PORT)
        require_available_port("Frontend", FRONTEND_PORT)
        try:
            self._start_inference_connection()
            self._sync_python_dependencies()
            self._sync_frontend_dependencies()
            self._ensure_builtin_web_search_mcp()
            self._start_backend()
            self._start_frontend()
            self._print_ready()
            self._supervise()
        finally:
            self.stop()

    def stop(self) -> None:
        grace = positive_integer_setting(
            self.environment,
            "AGENTFACTORY_WEB_PROCESS_STOP_GRACE_SECONDS",
            15,
        )
        if self.frontend is not None:
            self.frontend.stop(grace)
            self.frontend = None
        if self.backend is not None:
            self.backend.stop(grace)
            self.backend = None
        if self.tunnel is not None:
            if self.tunnel.poll() is None:
                print("Stopping inference SSH tunnel...", flush=True)
                terminate_process_tree(self.tunnel, grace)
            self.tunnel = None

    def _check_configuration(self) -> None:
        print("Checking local environment configuration...")
        if self.environment.get("AGENTFACTORY_RESOURCE_MASTER_KEY", "").strip():
            print(".env looks configured")
            return
        print(
            "WARNING: AGENTFACTORY_RESOURCE_MASTER_KEY is empty; encrypted resources "
            "will not be recoverable until it is configured.",
            file=sys.stderr,
        )

    def _start_inference_connection(self) -> None:
        mode = self.environment.get("AGENTFACTORY_INFERENCE_RUNTIME_MODE", "external")
        if mode != "external":
            return
        connection = self.environment.get("AGENTFACTORY_INFERENCE_CONNECTION_MODE", "")
        if connection not in {"direct", "ssh"}:
            raise ValueError("AGENTFACTORY_INFERENCE_CONNECTION_MODE must be direct or ssh")
        if connection == "direct":
            if not self._inference_node_ready():
                raise CommandError("direct inference control endpoint validation failed")
            print("Direct inference control endpoint is reachable")
            return
        ssh = require_command("ssh")
        port = self.environment["AGENTFACTORY_INFERENCE_SSH_PORT"]
        validate_port("AGENTFACTORY_INFERENCE_SSH_PORT", port)
        forwards: list[tuple[str, str]] = []
        for kind in ("CHAT", "EMBEDDING", "TELEMETRY", "IMAGE"):
            local = self.environment[f"AGENTFACTORY_INFERENCE_SSH_{kind}_LOCAL_PORT"]
            remote = self.environment[f"AGENTFACTORY_INFERENCE_SSH_{kind}_REMOTE_PORT"]
            validate_port(f"AGENTFACTORY_INFERENCE_SSH_{kind}_LOCAL_PORT", local)
            validate_port(f"AGENTFACTORY_INFERENCE_SSH_{kind}_REMOTE_PORT", remote)
            forwards.append((local, remote))
        local_ports = [local for local, _remote in forwards]
        if len(set(local_ports)) != len(local_ports):
            raise ValueError("Chat, embedding, telemetry, and image SSH local ports must differ")
        for local_port in local_ports:
            require_available_port("SSH tunnel", int(local_port))
        arguments = [
            ssh,
            "-N",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-p",
            port,
        ]
        for local, remote in forwards:
            arguments.extend(["-L", f"{local}:127.0.0.1:{remote}"])
        key_value = self.environment.get("AGENTFACTORY_INFERENCE_SSH_KEY", "").strip()
        if key_value:
            key = Path(key_value).expanduser().resolve()
            if not key.is_file():
                raise FileNotFoundError(f"SSH private key is not readable: {key}")
            arguments.extend(["-i", str(key)])
        arguments.append(
            f"{self.environment['AGENTFACTORY_INFERENCE_SSH_USER']}@"
            f"{self.environment['AGENTFACTORY_INFERENCE_SSH_HOST']}"
        )
        print("Opening SSH tunnel to external inference host...")
        self.tunnel = subprocess.Popen(arguments, **process_group_options())
        for _attempt in range(20):
            if self.tunnel.poll() is not None:
                raise CommandError(
                    "SSH tunnel exited before the inference control endpoint became available"
                )
            if self._inference_node_ready():
                print("External inference control endpoint is reachable")
                return
            time.sleep(0.5)
        raise CommandError(
            "SSH tunnel opened, but the inference control endpoint validation failed"
        )

    def _inference_node_ready(self) -> bool:
        endpoint = self.environment["AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT"].rstrip("/")
        return all(
            http_ready(f"{endpoint}{path}", timeout=2)
            for path in ("/health", "/models", "/runtime/rocm")
        )

    def _sync_python_dependencies(self) -> None:
        uv = require_command("uv")
        print("Checking Python backend dependencies with uv...")
        run([uv, "sync", "--extra", "web"], cwd=self.project_root, environment=self.environment)
        if not self.python_bin.is_file():
            raise FileNotFoundError(
                f"Python virtual environment was not created at {self.python_bin}"
            )
        run(
            [
                str(self.python_bin),
                "-c",
                "import fastapi, uvicorn, pydantic",
            ],
            cwd=self.project_root,
            environment=self.environment,
        )

    def _sync_frontend_dependencies(self) -> None:
        require_command("node")
        npm = require_command("npm")
        package_json = self.frontend_dir / "package.json"
        if not package_json.is_file():
            raise FileNotFoundError(f"frontend package.json not found: {package_json}")
        print("Checking frontend dependencies with npm...")
        node_modules = self.frontend_dir / "node_modules"
        vite_candidates = (
            node_modules / ".bin" / "vite",
            node_modules / ".bin" / "vite.cmd",
        )
        if not node_modules.is_dir():
            command = "ci" if (self.frontend_dir / "package-lock.json").is_file() else "install"
            run([npm, command], cwd=self.frontend_dir, environment=self.environment)
        elif not any(path.is_file() for path in vite_candidates):
            run([npm, "install"], cwd=self.frontend_dir, environment=self.environment)
        else:
            print("node_modules already exists")

    def _ensure_builtin_web_search_mcp(self) -> None:
        git = require_command("git")
        npm = require_command("npm")
        mcp_dir = self.project_root / ".agentfactory" / "mcp" / "web_search"
        previous_revision = ""
        if (mcp_dir / ".git").is_dir():
            previous_revision = capture(
                [git, "-C", str(mcp_dir), "rev-parse", "HEAD"],
                environment=self.environment,
            )
            print("Using installed built-in web search MCP")
        elif mcp_dir.exists():
            raise ValueError(
                f"web search MCP directory exists but is not a Git checkout: {mcp_dir}"
            )
        else:
            print("Cloning built-in web search MCP...")
            mcp_dir.parent.mkdir(parents=True, exist_ok=True)
            run(
                [git, "clone", "--quiet", WEB_SEARCH_MCP_REPOSITORY, str(mcp_dir)],
                cwd=self.project_root,
                environment=self.environment,
            )
        current_revision = capture(
            [git, "-C", str(mcp_dir), "rev-parse", "HEAD"],
            environment=self.environment,
        )
        needs_dependencies = (
            not (mcp_dir / "node_modules").is_dir()
            or previous_revision != current_revision
        )
        if needs_dependencies:
            print("Installing built-in web search MCP dependencies...")
            install = "ci" if (mcp_dir / "package-lock.json").is_file() else "install"
            run([npm, install], cwd=mcp_dir, environment=self.environment)
        needs_build = (
            not (mcp_dir / "dist" / "index.js").is_file()
            or previous_revision != current_revision
        )
        if needs_build:
            print("Building built-in web search MCP...")
            run([npm, "run", "build"], cwd=mcp_dir, environment=self.environment)
        else:
            print("Built-in web search MCP is ready")

    def _start_backend(self) -> None:
        print(f"Starting backend web runtime service on port {BACKEND_PORT}...")
        self.backend = ManagedProcess.start_logged(
            "backend",
            [str(self.python_bin), "web_frontend/backend/event_api_server.py"],
            cwd=self.project_root,
            environment=self.environment,
            log_path=self.logs_dir / "web-backend.log",
        )
        self._wait_for_ready(self.backend, BACKEND_HEALTH_URL)

    def _start_frontend(self) -> None:
        print(f"Starting frontend development server on port {FRONTEND_PORT}...")
        npm = require_command("npm")
        self.frontend = ManagedProcess.start_logged(
            "frontend",
            [
                npm,
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(FRONTEND_PORT),
                "--strictPort",
            ],
            cwd=self.frontend_dir,
            environment=self.environment,
            log_path=self.logs_dir / "web-frontend.log",
        )
        self._wait_for_ready(self.frontend, FRONTEND_HEALTH_URL)

    def _wait_for_ready(self, process: ManagedProcess, url: str) -> None:
        timeout = positive_integer_setting(
            self.environment,
            "AGENTFACTORY_WEB_BACKEND_STARTUP_TIMEOUT_SECONDS",
            180,
        )
        print(f"Waiting for {process.name} readiness at {url}...")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            return_code = process.process.poll()
            if return_code is not None:
                raise CommandError(
                    f"{process.name} exited with status {return_code} before becoming ready"
                )
            if http_ready(url, timeout=1):
                print(f"{process.name.capitalize()} is ready")
                return
            time.sleep(0.5)
        raise TimeoutError(f"{process.name} did not become ready within {timeout} seconds")

    def _print_ready(self) -> None:
        print("")
        print("===================================")
        print("Application ready")
        print(f"Frontend: http://localhost:{FRONTEND_PORT}")
        print(f"Backend:  http://localhost:{BACKEND_PORT}")
        print("===================================")
        print(f"Backend log: {self.logs_dir / 'web-backend.log'}")
        print(f"Frontend log: {self.logs_dir / 'web-frontend.log'}")
        print("Press Ctrl+C to stop all services")

    def _supervise(self) -> None:
        interval = positive_integer_setting(
            self.environment,
            "AGENTFACTORY_WEB_SERVICE_HEALTH_INTERVAL_SECONDS",
            2,
        )
        failure_limit = positive_integer_setting(
            self.environment,
            "AGENTFACTORY_WEB_BACKEND_HEALTH_FAILURE_LIMIT",
            5,
        )
        failures = 0
        while True:
            for process in (self.backend, self.frontend):
                if process is None:
                    continue
                return_code = process.process.poll()
                if return_code is not None:
                    raise CommandError(
                        f"{process.name} exited with status {return_code}"
                    )
            if http_ready(BACKEND_HEALTH_URL, timeout=1):
                failures = 0
            else:
                failures += 1
                if failures >= failure_limit:
                    raise CommandError(
                        f"backend health check failed {failures} consecutive times"
                    )
            time.sleep(interval)


def process_group_options() -> dict[str, int | bool]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process_tree(process: subprocess.Popen[object], grace_seconds: int) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if taskkill is None:
            process.terminate()
        else:
            subprocess.run(
                [taskkill, "/PID", str(process.pid), "/T"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if taskkill is not None:
            subprocess.run(
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            process.kill()
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)


def require_available_port(service: str, port: int) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("0.0.0.0", port))
    except OSError as exc:
        raise OSError(f"{service} port {port} is already in use") from exc


def http_ready(url: str, *, timeout: float) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def positive_integer_setting(
    environment: dict[str, str],
    name: str,
    default: int,
) -> int:
    value = environment.get(name, str(default))
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if number < 1:
        raise ValueError(f"{name} must be a positive integer")
    return number


def capture(arguments: Sequence[str], *, environment: dict[str, str]) -> str:
    completed = subprocess.run(
        list(arguments),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise CommandError(completed.stderr.strip() or "command failed")
    return completed.stdout.strip()
