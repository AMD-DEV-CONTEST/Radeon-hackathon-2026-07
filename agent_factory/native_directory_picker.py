from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


class NativeDirectoryPickerUnavailableError(RuntimeError):
    """Raised when the host cannot display a native directory picker."""


class NativeDirectoryPicker:
    def select(self, initial_path: str | None = None) -> Path | None:
        initial_directory = _initial_directory(initial_path)
        command = _picker_command(initial_directory)
        completed = subprocess.run(
            command.argv,
            capture_output=True,
            text=True,
            check=False,
            creationflags=command.creation_flags,
        )
        if completed.returncode != 0:
            if command.cancelled(completed.returncode, completed.stderr):
                return None
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(detail or "native directory picker failed")
        selected = completed.stdout.strip()
        if not selected:
            return None
        path = Path(selected).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"selected directory not found: {path}")
        return path


class _PickerCommand:
    def __init__(
        self,
        argv: Sequence[str],
        *,
        cancellation_codes: frozenset[int],
        cancellation_markers: tuple[str, ...] = (),
        creation_flags: int = 0,
    ) -> None:
        self.argv = list(argv)
        self.cancellation_codes = cancellation_codes
        self.cancellation_markers = cancellation_markers
        self.creation_flags = creation_flags

    def cancelled(self, return_code: int, stderr: str) -> bool:
        if return_code not in self.cancellation_codes:
            return False
        if not self.cancellation_markers:
            return True
        normalized = stderr.casefold()
        return any(marker.casefold() in normalized for marker in self.cancellation_markers)


def _picker_command(initial_directory: Path) -> _PickerCommand:
    system = platform.system()
    if system == "Darwin":
        executable = _required_executable("osascript")
        script = (
            "on run argv\n"
            "set initialDirectory to POSIX file (item 1 of argv)\n"
            'set selectedDirectory to choose folder with prompt "Select workspace folder" '
            "default location initialDirectory\n"
            "return POSIX path of selectedDirectory\n"
            "end run"
        )
        return _PickerCommand(
            [executable, "-e", script, str(initial_directory)],
            cancellation_codes=frozenset({1}),
            cancellation_markers=("user canceled", "-128"),
        )
    if system == "Windows":
        executable = _first_executable(("powershell.exe", "pwsh.exe", "pwsh"))
        script = (
            "$dialog = New-Object -ComObject Shell.Application; "
            "$folder = $dialog.BrowseForFolder(0, 'Select workspace folder', 0, $args[0]); "
            "if ($null -ne $folder) { $folder.Self.Path }"
        )
        return _PickerCommand(
            [executable, "-NoLogo", "-NoProfile", "-STA", "-Command", script, str(initial_directory)],
            cancellation_codes=frozenset(),
            creation_flags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if system == "Linux":
        zenity = shutil.which("zenity")
        if zenity:
            return _PickerCommand(
                [
                    zenity,
                    "--file-selection",
                    "--directory",
                    "--title=Select workspace folder",
                    f"--filename={initial_directory}{os.sep}",
                ],
                cancellation_codes=frozenset({1}),
            )
        kdialog = shutil.which("kdialog")
        if kdialog:
            return _PickerCommand(
                [kdialog, "--getexistingdirectory", str(initial_directory), "--title", "Select workspace folder"],
                cancellation_codes=frozenset({1}),
            )
        raise NativeDirectoryPickerUnavailableError(
            "native directory picker requires zenity or kdialog on Linux"
        )
    raise NativeDirectoryPickerUnavailableError(
        f"native directory picker is not supported on {system or 'this platform'}"
    )


def _initial_directory(value: str | None) -> Path:
    if value:
        candidate = Path(value).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
    return Path.home().resolve()


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise NativeDirectoryPickerUnavailableError(f"native directory picker requires {name}")
    return executable


def _first_executable(names: Sequence[str]) -> str:
    for name in names:
        executable = shutil.which(name)
        if executable:
            return executable
    raise NativeDirectoryPickerUnavailableError(
        f"native directory picker requires one of: {', '.join(names)}"
    )
