from __future__ import annotations

import unittest
from pathlib import Path

from privateops.windows_inspector import WindowsInspector


class FakeStartupSources:
    def __init__(self, registry=None, folders=None, errors=None):
        self.registry = list(registry or [])
        self.folders = list(folders or [])
        self.errors = list(errors or [])

    def read(self):
        return self.registry, self.folders, self.errors


class FakePowerShellRunner:
    def __init__(self, fixtures=None, error=None):
        self.fixtures = dict(fixtures or {})
        self.error = error
        self.calls = []

    def __call__(self, script_id, script):
        self.calls.append((script_id, script))
        if self.error:
            raise self.error
        return self.fixtures[script_id]


class WindowsInspectorTests(unittest.TestCase):
    def test_startup_inventory_combines_sources_without_command_arguments(self):
        sources = FakeStartupSources(
            registry=[
                {
                    "name": "Updater",
                    "source": "registry",
                    "location": "HKCU Run",
                    "command": '"C:\\Users\\Lucian\\Apps\\Updater.exe" --token secret',
                }
            ],
            folders=[
                {
                    "name": "Helper.lnk",
                    "source": "startup_folder",
                    "location": "Current user Startup",
                    "path": "C:\\Users\\Lucian\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Helper.lnk",
                },
                {
                    "name": "desktop.ini",
                    "source": "startup_folder",
                    "location": "Current user Startup",
                    "path": "C:\\Users\\Lucian\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\desktop.ini",
                },
            ],
        )
        inspector = WindowsInspector(
            platform_name="win32",
            startup_sources=sources,
            user_profile=Path("C:/Users/Lucian"),
        )

        result = inspector.collect("startup_inventory")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output["count"], 2)
        self.assertEqual(result.output["entries"][0]["executable"], "%USERPROFILE%/Apps/Updater.exe")
        self.assertEqual(result.output["entries"][1]["executable"], "%USERPROFILE%/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/Helper.lnk")
        serialized = str(result.to_dict()).lower()
        self.assertNotIn("--token", serialized)
        self.assertNotIn("secret", serialized)
        self.assertFalse(result.output["truncated"])

    def test_startup_inventory_reports_partial_source_errors(self):
        inspector = WindowsInspector(
            platform_name="win32",
            startup_sources=FakeStartupSources(errors=["HKLM Run: access denied"]),
        )

        result = inspector.collect("startup_inventory")

        self.assertEqual(result.status, "attention")
        self.assertEqual(result.output["entries"], [])
        self.assertEqual(result.output["errors"], ["HKLM Run: access denied"])

    def test_system_tool_is_unsupported_outside_windows(self):
        result = WindowsInspector(platform_name="linux").collect("startup_inventory")

        self.assertEqual(result.status, "unsupported")
        self.assertIn("Windows", result.summary)

    def test_fixed_collectors_normalize_only_allowlisted_fields(self):
        runner = FakePowerShellRunner(
            {
                "process_inventory": [
                    {
                        "Id": 42,
                        "Name": "Example",
                        "Path": "C:\\Users\\Lucian\\Example.exe",
                        "CpuSeconds": 1.25,
                        "WorkingSetBytes": 4096,
                        "CommandLine": "Example.exe --password secret",
                    }
                ],
                "service_inventory": [
                    {"Name": "Svc", "DisplayName": "Example Service", "State": "Running", "StartMode": "Auto"}
                ],
                "scheduled_task_inventory": [
                    {"TaskPath": "\\", "TaskName": "Example Task", "State": "Ready", "Triggers": ["MSFT_TaskLogonTrigger"]}
                ],
                "system_overview": {
                    "Windows": {"Caption": "Windows 11", "Version": "10.0", "BuildNumber": "26100"},
                    "Cpu": [{"Name": "AMD Ryzen", "Cores": 8, "LogicalProcessors": 16}],
                    "MemoryBytes": 34359738368,
                    "Gpu": [{"Name": "AMD Radeon", "DriverVersion": "1.2.3"}],
                    "Disks": [{"DeviceId": "C:", "SizeBytes": 1000, "FreeBytes": 400}],
                },
                "network_listener_inventory": [
                    {"LocalAddress": "127.0.0.1", "LocalPort": 8765, "OwningProcess": 10, "ProcessName": "python"}
                ],
                "security_status": {
                    "Defender": {"AntivirusEnabled": True, "RealTimeProtectionEnabled": True, "SignatureAgeDays": 0},
                    "Firewall": [{"Name": "Private", "Enabled": True}],
                },
            }
        )
        inspector = WindowsInspector(
            platform_name="win32",
            powershell_runner=runner,
            user_profile=Path("C:/Users/Lucian"),
        )

        results = {
            name: inspector.collect(name)
            for name in [
                "process_inventory",
                "service_inventory",
                "scheduled_task_inventory",
                "system_overview",
                "network_listener_inventory",
                "security_status",
            ]
        }

        self.assertTrue(all(result.status == "completed" for result in results.values()))
        process = results["process_inventory"].output["items"][0]
        self.assertEqual(process["pid"], 42)
        self.assertEqual(process["executable"], "%USERPROFILE%/Example.exe")
        self.assertNotIn("CommandLine", str(results))
        self.assertNotIn("password", str(results).lower())
        self.assertEqual(results["service_inventory"].output["items"][0]["start_mode"], "Auto")
        self.assertEqual(results["scheduled_task_inventory"].output["items"][0]["task_name"], "Example Task")
        self.assertEqual(results["system_overview"].output["gpu"][0]["name"], "AMD Radeon")
        self.assertEqual(results["network_listener_inventory"].output["items"][0]["port"], 8765)
        self.assertTrue(results["security_status"].output["defender"]["antivirus_enabled"])
        self.assertEqual([call[0] for call in runner.calls], list(results))

    def test_bounded_collector_marks_truncation(self):
        runner = FakePowerShellRunner(
            {
                "process_inventory": [
                    {"Id": index, "Name": f"P{index}", "Path": None, "CpuSeconds": 0, "WorkingSetBytes": 0}
                    for index in range(205)
                ]
            }
        )
        result = WindowsInspector(platform_name="win32", powershell_runner=runner).collect("process_inventory")

        self.assertEqual(result.output["count"], 200)
        self.assertTrue(result.output["truncated"])

    def test_collector_failure_is_visible(self):
        result = WindowsInspector(
            platform_name="win32",
            powershell_runner=FakePowerShellRunner(error=TimeoutError("collector timed out")),
        ).collect("service_inventory")

        self.assertEqual(result.status, "failed")
        self.assertIn("timed out", result.summary)

    def test_unknown_system_tool_is_blocked(self):
        result = WindowsInspector(platform_name="win32").collect("read_browser_passwords")

        self.assertEqual(result.status, "blocked")


if __name__ == "__main__":
    unittest.main()
