from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
from typing import Any, Mapping


class ShellRuntimeUnavailable(RuntimeError):
    """Raised when the host platform has no supported command interpreter."""


@dataclass(frozen=True, slots=True)
class ShellCommandAnalysis:
    command_binary: str
    contains_shell_control: bool
    high_risk_binary: bool


class ShellRuntime(ABC):
    shell_id: str
    display_name: str

    def __init__(self, executable: Path) -> None:
        self.executable = executable

    @abstractmethod
    def command_argv(self, command: str) -> list[str]:
        ...

    @abstractmethod
    def process_options(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def analyze(self, command: str) -> ShellCommandAnalysis:
        ...

    @abstractmethod
    def terminate_tree(self, process: subprocess.Popen[str]) -> None:
        ...

    @abstractmethod
    def kill_tree(self, process: subprocess.Popen[str]) -> None:
        ...

    def environment(self, source: Mapping[str, str]) -> dict[str, str]:
        return dict(source)


class PosixBashRuntime(ShellRuntime):
    shell_id = "bash"
    display_name = "Bash"
    _HIGH_RISK_COMMANDS = frozenset(
        {"rm", "dd", "mkfs", "sudo", "chmod", "chown", "curl", "wget", "scp", "ssh"}
    )
    _CONTROL_TOKENS = ("|", "&&", "||", ";", "$(", "`", ">", "<")

    def command_argv(self, command: str) -> list[str]:
        return [str(self.executable), "-c", command]

    def process_options(self) -> dict[str, Any]:
        return {"start_new_session": True}

    def analyze(self, command: str) -> ShellCommandAnalysis:
        binary = Path(_first_shell_word(command)).name
        return ShellCommandAnalysis(
            command_binary=binary,
            contains_shell_control=any(token in command for token in self._CONTROL_TOKENS),
            high_risk_binary=binary.casefold() in self._HIGH_RISK_COMMANDS,
        )

    def terminate_tree(self, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            process.terminate()

    def kill_tree(self, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            process.kill()


def _first_shell_word(command: str) -> str:
    lexer = shlex.shlex(command, posix=True)
    lexer.commenters = ""
    lexer.whitespace_split = True
    return next(lexer, "")


class WindowsPowerShellRuntime(ShellRuntime):
    shell_id = "powershell"
    display_name = "PowerShell"
    _HIGH_RISK_COMMANDS = frozenset(
        {
            "clear-disk",
            "format-volume",
            "invoke-restmethod",
            "invoke-webrequest",
            "remove-item",
            "remove-partition",
            "restart-computer",
            "stop-computer",
        }
    )
    _CONTROL_TOKENS = ("|", "&&", "||", ";", "$(", ">", "<")
    _UTF8_SETUP = (
        "$utf8 = [System.Text.UTF8Encoding]::new($false); "
        "[Console]::InputEncoding = $utf8; "
        "[Console]::OutputEncoding = $utf8; "
        "$OutputEncoding = $utf8"
    )

    def __init__(self, executable: Path, *, taskkill_executable: Path | None) -> None:
        super().__init__(executable)
        self._taskkill_executable = taskkill_executable

    def command_argv(self, command: str) -> list[str]:
        script = f"{self._UTF8_SETUP}; {command}"
        return [
            str(self.executable),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]

    def process_options(self) -> dict[str, Any]:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}

    def environment(self, source: Mapping[str, str]) -> dict[str, str]:
        environment = dict(source)
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        return environment

    def analyze(self, command: str) -> ShellCommandAnalysis:
        binary = _powershell_command_binary(command)
        return ShellCommandAnalysis(
            command_binary=binary,
            contains_shell_control=any(token in command for token in self._CONTROL_TOKENS),
            high_risk_binary=binary.casefold() in self._HIGH_RISK_COMMANDS,
        )

    def terminate_tree(self, process: subprocess.Popen[str]) -> None:
        if not self._taskkill(process, force=False):
            process.terminate()

    def kill_tree(self, process: subprocess.Popen[str]) -> None:
        if not self._taskkill(process, force=True):
            process.kill()

    def _taskkill(self, process: subprocess.Popen[str], *, force: bool) -> bool:
        if self._taskkill_executable is None or process.poll() is not None:
            return process.poll() is not None
        command = [str(self._taskkill_executable), "/PID", str(process.pid), "/T"]
        if force:
            command.append("/F")
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.returncode == 0


def resolve_shell_runtime() -> ShellRuntime:
    if os.name == "nt":
        executable = _find_executable(("pwsh.exe", "pwsh", "powershell.exe", "powershell"))
        if executable is None:
            raise ShellRuntimeUnavailable(
                "PowerShell is required for the shell tool on Windows, but neither pwsh nor "
                "Windows PowerShell is available on PATH"
            )
        return WindowsPowerShellRuntime(
            executable,
            taskkill_executable=_find_executable(("taskkill.exe", "taskkill")),
        )
    executable = _find_executable(("bash",))
    if executable is None:
        raise ShellRuntimeUnavailable(
            "Bash is required for the shell tool on macOS and Linux, but it is not available on PATH"
        )
    return PosixBashRuntime(executable)


def host_shell_display_name() -> str:
    return "PowerShell" if os.name == "nt" else "Bash"


def _find_executable(candidates: tuple[str, ...]) -> Path | None:
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return Path(resolved).resolve()
    return None


def _powershell_command_binary(command: str) -> str:
    text = command.lstrip()
    if text.startswith("&"):
        text = text[1:].lstrip()
    if not text:
        return ""
    if text[0] in {'"', "'"}:
        quote = text[0]
        end = text.find(quote, 1)
        token = text[1:end] if end >= 0 else text[1:]
    else:
        token = text.split(maxsplit=1)[0]
    return Path(token.rstrip(";")).name
