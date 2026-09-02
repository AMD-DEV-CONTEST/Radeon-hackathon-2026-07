from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from autotuner.config import TuneConfig, engine_profile
from autotuner.models import Candidate


class ServerManager:
    def __init__(
        self,
        config: TuneConfig,
        candidate: Candidate,
        trial_directory: Path,
        enable_profile: bool,
    ) -> None:
        self.config = config
        self.candidate = candidate
        self.trial_directory = trial_directory
        self.enable_profile = enable_profile
        self.process: Optional[subprocess.Popen[str]] = None
        self.log_handle: Any = None
        self.profile_directory = ""

    def __enter__(self) -> "ServerManager":
        if self.config.manage_server:
            self.start()
        self.wait_until_ready()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()

    def start(self) -> None:
        profile = engine_profile(self.config, self.candidate.engine)
        command = self._build_command(profile)
        environment = os.environ.copy()
        environment.update(
            {
                str(key): str(value)
                for key, value in profile.get("environment", {}).items()
            }
        )
        if self.candidate.attention_backend.lower() != "auto":
            environment["VLLM_ATTENTION_BACKEND"] = (
                self.candidate.attention_backend
            )
        if self.enable_profile and shutil.which("rocprofv3"):
            profile_path = self.trial_directory / "profile"
            profile_path.mkdir(parents=True, exist_ok=True)
            self.profile_directory = str(profile_path)
            command = [
                "rocprofv3",
                "--stats",
                "--hip-trace",
                "--output-format",
                "csv",
                "--output-directory",
                str(profile_path),
                "--",
            ] + command
        self.trial_directory.mkdir(parents=True, exist_ok=True)
        self.log_handle = (self.trial_directory / "server.log").open(
            "w", encoding="utf8"
        )
        self.process = subprocess.Popen(
            command,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=environment,
            start_new_session=True,
        )

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=20)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=5)
        if self.log_handle:
            self.log_handle.close()
        if self.config.manage_server and self.config.cooldown_seconds:
            time.sleep(self.config.cooldown_seconds)

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.config.startup_timeout_seconds
        models_url = self.config.endpoint + "/models"
        last_error = ""
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                raise RuntimeError(
                    "Inference server exited during startup. Review "
                    + str(self.trial_directory / "server.log")
                )
            try:
                with urllib.request.urlopen(models_url, timeout=5) as response:
                    if 200 <= response.status < 300:
                        return
            except (OSError, urllib.error.URLError) as error:
                last_error = str(error)
            time.sleep(2)
        raise TimeoutError(
            f"Inference server did not become ready: {last_error}"
        )

    def _build_command(self, profile: Dict[str, Any]) -> List[str]:
        replacements = {
            name: str(value)
            for name, value in self.candidate.to_dict().items()
        }
        replacements.update(
            {
                "host": self.config.host,
                "port": str(self.config.port),
            }
        )
        command = [
            str(item).format(**replacements)
            for item in profile.get("command", [])
        ]
        if not command:
            raise ValueError(
                f"Engine {self.candidate.engine} has no launch command"
            )
        adapter = str(profile.get("adapter", "vllm"))
        if adapter == "external":
            return command
        if adapter != "vllm":
            raise ValueError(f"Unsupported engine adapter: {adapter}")
        command.extend(
            [
                "--host",
                self.config.host,
                "--port",
                str(self.config.port),
                "--max-model-len",
                str(self.candidate.max_model_len),
                "--max-num-seqs",
                str(self.candidate.max_num_seqs),
                "--gpu-memory-utilization",
                str(self.candidate.gpu_memory_utilization),
            ]
        )
        if self.candidate.kv_cache_dtype != "auto":
            command.extend(
                ["--kv-cache-dtype", self.candidate.kv_cache_dtype]
            )
        if self.candidate.quantization not in {"none", "auto"}:
            command.extend(
                ["--quantization", self.candidate.quantization]
            )
        if self.candidate.speculative_model:
            speculative = json.dumps(
                {
                    "model": self.candidate.speculative_model,
                    "num_speculative_tokens": (
                        self.candidate.num_speculative_tokens
                    ),
                },
                separators=(",", ":"),
            )
            command.extend(["--speculative-config", speculative])
        return command
