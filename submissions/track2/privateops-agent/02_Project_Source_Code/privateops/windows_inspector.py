from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any

from privateops.models import ToolResult


MAX_ITEMS = 200
STARTUP_FILE_EXTENSIONS = {".lnk", ".url", ".exe", ".bat", ".cmd", ".ps1", ".vbs"}
SYSTEM_TOOLS = {
    "startup_inventory",
    "process_inventory",
    "service_inventory",
    "scheduled_task_inventory",
    "system_overview",
    "network_listener_inventory",
    "security_status",
}

POWERSHELL_SCRIPTS = {
    "process_inventory": r"""
@(Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 250 | ForEach-Object {
  $processPath = try { $_.Path } catch { $null }
  [ordered]@{ Id = $_.Id; Name = $_.ProcessName; Path = $processPath; CpuSeconds = $_.CPU; WorkingSetBytes = $_.WorkingSet64 }
}) | ConvertTo-Json -Depth 5 -Compress
""",
    "service_inventory": r"""
@(Get-CimInstance Win32_Service | Sort-Object Name | Select-Object -First 300 | ForEach-Object {
  [ordered]@{ Name = $_.Name; DisplayName = $_.DisplayName; State = $_.State; StartMode = $_.StartMode }
}) | ConvertTo-Json -Depth 5 -Compress
""",
    "scheduled_task_inventory": r"""
@(Get-ScheduledTask | Sort-Object TaskPath, TaskName | Select-Object -First 300 | ForEach-Object {
  $triggerNames = @($_.Triggers | ForEach-Object { $_.CimClass.CimClassName })
  [ordered]@{ TaskPath = $_.TaskPath; TaskName = $_.TaskName; State = [string]$_.State; Triggers = $triggerNames }
}) | ConvertTo-Json -Depth 6 -Compress
""",
    "system_overview": r"""
$os = Get-CimInstance Win32_OperatingSystem
$cpu = @(Get-CimInstance Win32_Processor | ForEach-Object { [ordered]@{ Name = $_.Name; Cores = $_.NumberOfCores; LogicalProcessors = $_.NumberOfLogicalProcessors } })
$gpu = @(Get-CimInstance Win32_VideoController | ForEach-Object { [ordered]@{ Name = $_.Name; DriverVersion = $_.DriverVersion } })
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object { [ordered]@{ DeviceId = $_.DeviceID; SizeBytes = $_.Size; FreeBytes = $_.FreeSpace } })
[ordered]@{
  Windows = [ordered]@{ Caption = $os.Caption; Version = $os.Version; BuildNumber = $os.BuildNumber }
  Cpu = $cpu
  MemoryBytes = $os.TotalVisibleMemorySize * 1KB
  Gpu = $gpu
  Disks = $disks
} | ConvertTo-Json -Depth 6 -Compress
""",
    "network_listener_inventory": r"""
@(Get-NetTCPConnection -State Listen | Sort-Object LocalPort, LocalAddress | Select-Object -First 250 | ForEach-Object {
  $processName = try { (Get-Process -Id $_.OwningProcess -ErrorAction Stop).ProcessName } catch { $null }
  [ordered]@{ LocalAddress = $_.LocalAddress; LocalPort = $_.LocalPort; OwningProcess = $_.OwningProcess; ProcessName = $processName }
}) | ConvertTo-Json -Depth 5 -Compress
""",
    "security_status": r"""
$defender = try {
  $status = Get-MpComputerStatus -ErrorAction Stop
  [ordered]@{ AntivirusEnabled = $status.AntivirusEnabled; RealTimeProtectionEnabled = $status.RealTimeProtectionEnabled; SignatureAgeDays = $status.AntivirusSignatureAge }
} catch { $null }
$firewall = try {
  @(Get-NetFirewallProfile -ErrorAction Stop | ForEach-Object { [ordered]@{ Name = $_.Name; Enabled = $_.Enabled } })
} catch { @() }
[ordered]@{ Defender = $defender; Firewall = $firewall } | ConvertTo-Json -Depth 6 -Compress
""",
}


class WindowsStartupSources:
    def read(self) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
        registry_entries: list[dict[str, str]] = []
        folder_entries: list[dict[str, str]] = []
        errors: list[str] = []
        try:
            import winreg
        except ImportError:
            return registry_entries, folder_entries, ["Windows registry API is unavailable."]

        registry_locations = [
            (winreg.HKEY_CURRENT_USER, "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_CURRENT_USER, "HKCU", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
            (winreg.HKEY_LOCAL_MACHINE, "HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, "HKLM", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
        ]
        for hive, hive_name, key_path in registry_locations:
            label = f"{hive_name} {key_path.rsplit('\\', 1)[-1]}"
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    index = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        registry_entries.append(
                            {
                                "name": str(name),
                                "source": "registry",
                                "location": label,
                                "command": str(value),
                            }
                        )
                        index += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                errors.append(f"{label}: {exc}")

        folders = [
            ("Current user Startup", Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"),
            ("All users Startup", Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs/StartUp"),
        ]
        for label, folder in folders:
            if not str(folder) or not folder.exists():
                continue
            try:
                for path in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
                    if path.is_file():
                        folder_entries.append(
                            {
                                "name": path.name,
                                "source": "startup_folder",
                                "location": label,
                                "path": str(path),
                            }
                        )
            except OSError as exc:
                errors.append(f"{label}: {exc}")
        return registry_entries, folder_entries, errors


class WindowsInspector:
    def __init__(
        self,
        platform_name: str | None = None,
        startup_sources: Any | None = None,
        user_profile: Path | None = None,
        powershell_runner: Any | None = None,
    ):
        self.platform_name = platform_name or platform.system().lower()
        self.startup_sources = startup_sources or WindowsStartupSources()
        self.user_profile = user_profile or Path(os.environ.get("USERPROFILE", ""))
        self.powershell_runner = powershell_runner or self._run_powershell_json

    def collect(self, tool_name: str) -> ToolResult:
        if tool_name not in SYSTEM_TOOLS:
            return ToolResult(tool_name, "blocked", "Unknown system tools are blocked.")
        if not self._is_windows():
            return ToolResult(tool_name, "unsupported", "This read-only system tool requires Windows.")
        if tool_name == "startup_inventory":
            return self.startup_inventory()
        return self._fixed_inventory(tool_name)

    def startup_inventory(self) -> ToolResult:
        registry_entries, folder_entries, errors = self.startup_sources.read()
        entries = []
        for item in registry_entries:
            entries.append(
                {
                    "name": str(item.get("name", "")),
                    "source": "registry",
                    "location": str(item.get("location", "")),
                    "executable": self._display_path(self._command_executable(str(item.get("command", "")))),
                }
            )
        for item in folder_entries:
            if Path(str(item.get("name", ""))).suffix.lower() not in STARTUP_FILE_EXTENSIONS:
                continue
            entries.append(
                {
                    "name": str(item.get("name", "")),
                    "source": "startup_folder",
                    "location": str(item.get("location", "")),
                    "executable": self._display_path(str(item.get("path", ""))),
                }
            )
        truncated = len(entries) > MAX_ITEMS
        entries = entries[:MAX_ITEMS]
        status = "attention" if errors else "completed"
        summary = f"Observed {len(entries)} Windows startup entries."
        if errors:
            summary += f" {len(errors)} source(s) could not be read."
        return ToolResult(
            "startup_inventory",
            status,
            summary,
            {
                "entries": entries,
                "count": len(entries),
                "truncated": truncated,
                "errors": list(errors),
            },
        )

    def _is_windows(self) -> bool:
        return self.platform_name.lower() in {"windows", "win32"}

    def _fixed_inventory(self, tool_name: str) -> ToolResult:
        try:
            raw = self.powershell_runner(tool_name, POWERSHELL_SCRIPTS[tool_name])
            output = self._normalize_fixed(tool_name, raw)
        except (OSError, TimeoutError, ValueError, subprocess.SubprocessError) as exc:
            return ToolResult(tool_name, "failed", f"Windows collector failed: {exc}")
        count = int(output.get("count", 1))
        return ToolResult(tool_name, "completed", f"Observed {count} item(s) from Windows.", output)

    def _normalize_fixed(self, tool_name: str, raw: Any) -> dict[str, Any]:
        if tool_name == "process_inventory":
            return self._bounded_items(
                [
                    {
                        "pid": int(item.get("Id", 0)),
                        "name": str(item.get("Name", "")),
                        "executable": self._display_path(str(item.get("Path") or "")),
                        "cpu_seconds": float(item.get("CpuSeconds") or 0),
                        "working_set_bytes": int(item.get("WorkingSetBytes") or 0),
                    }
                    for item in self._object_list(raw)
                ]
            )
        if tool_name == "service_inventory":
            return self._bounded_items(
                [
                    {
                        "name": str(item.get("Name", "")),
                        "display_name": str(item.get("DisplayName", "")),
                        "state": str(item.get("State", "")),
                        "start_mode": str(item.get("StartMode", "")),
                    }
                    for item in self._object_list(raw)
                ]
            )
        if tool_name == "scheduled_task_inventory":
            return self._bounded_items(
                [
                    {
                        "task_path": str(item.get("TaskPath", "")),
                        "task_name": str(item.get("TaskName", "")),
                        "state": str(item.get("State", "")),
                        "triggers": [str(value) for value in (item.get("Triggers") or [])],
                    }
                    for item in self._object_list(raw)
                ]
            )
        if tool_name == "network_listener_inventory":
            return self._bounded_items(
                [
                    {
                        "address": str(item.get("LocalAddress", "")),
                        "port": int(item.get("LocalPort", 0)),
                        "pid": int(item.get("OwningProcess", 0)),
                        "process_name": str(item.get("ProcessName") or ""),
                    }
                    for item in self._object_list(raw)
                ]
            )
        if tool_name == "system_overview":
            if not isinstance(raw, dict):
                raise ValueError("System overview returned malformed data.")
            windows = raw.get("Windows") or {}
            return {
                "windows": {
                    "caption": str(windows.get("Caption", "")),
                    "version": str(windows.get("Version", "")),
                    "build_number": str(windows.get("BuildNumber", "")),
                },
                "cpu": [
                    {
                        "name": str(item.get("Name", "")),
                        "cores": int(item.get("Cores", 0)),
                        "logical_processors": int(item.get("LogicalProcessors", 0)),
                    }
                    for item in self._object_list(raw.get("Cpu"))
                ],
                "memory_bytes": int(raw.get("MemoryBytes") or 0),
                "gpu": [
                    {"name": str(item.get("Name", "")), "driver_version": str(item.get("DriverVersion", ""))}
                    for item in self._object_list(raw.get("Gpu"))
                ],
                "disks": [
                    {
                        "device_id": str(item.get("DeviceId", "")),
                        "size_bytes": int(item.get("SizeBytes") or 0),
                        "free_bytes": int(item.get("FreeBytes") or 0),
                    }
                    for item in self._object_list(raw.get("Disks"))
                ],
                "count": 1,
                "truncated": False,
            }
        if tool_name == "security_status":
            if not isinstance(raw, dict):
                raise ValueError("Security status returned malformed data.")
            defender = raw.get("Defender") or {}
            return {
                "defender": {
                    "antivirus_enabled": bool(defender.get("AntivirusEnabled", False)),
                    "real_time_protection_enabled": bool(defender.get("RealTimeProtectionEnabled", False)),
                    "signature_age_days": int(defender.get("SignatureAgeDays") or 0),
                },
                "firewall": [
                    {"name": str(item.get("Name", "")), "enabled": bool(item.get("Enabled", False))}
                    for item in self._object_list(raw.get("Firewall"))
                ],
                "count": 1,
                "truncated": False,
            }
        raise ValueError("Unknown fixed collector.")

    @staticmethod
    def _object_list(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        values = value if isinstance(value, list) else [value]
        if not all(isinstance(item, dict) for item in values):
            raise ValueError("Windows collector returned malformed list data.")
        return values

    @staticmethod
    def _bounded_items(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"items": items[:MAX_ITEMS], "count": min(len(items), MAX_ITEMS), "truncated": len(items) > MAX_ITEMS}

    @staticmethod
    def _run_powershell_json(script_id: str, script: str) -> Any:
        prefix = "$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", prefix + script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            error = completed.stderr.strip() or f"{script_id} exited with {completed.returncode}."
            raise OSError(error)
        try:
            return json.loads(completed.stdout or "null")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{script_id} returned invalid JSON.") from exc

    def _display_path(self, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        profile = str(self.user_profile).strip().replace("\\", "/").rstrip("/")
        if profile and normalized.lower().startswith(profile.lower()):
            normalized = "%USERPROFILE%" + normalized[len(profile):]
        return normalized

    @staticmethod
    def _command_executable(command: str) -> str:
        value = os.path.expandvars(command.strip())
        if value.startswith('"'):
            end = value.find('"', 1)
            return value[1:end] if end > 1 else value.strip('"')
        executable = re.match(r"(?i)^(.+?\.exe)\b", value)
        if executable:
            return executable.group(1)
        return value.split(maxsplit=1)[0] if value else ""
