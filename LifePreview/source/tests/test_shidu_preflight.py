from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
CREATIVE_HUB_SRC = ROOT / "creative_hub" / "src"
if str(CREATIVE_HUB_SRC) not in sys.path:
    sys.path.insert(0, str(CREATIVE_HUB_SRC))

from creative_hub import shidu_preflight
from creative_hub.shidu_preflight import PreflightCheck, run_preflight


def test_preflight_rejects_missing_runtime_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "missing"

    result = run_preflight(runtime_root=runtime_root, live=False)

    assert result.ready is False
    assert result.checks["artifact_root"].error_code == "runtime_root_missing"
    assert result.runtime_root == runtime_root.resolve().as_posix()
    assert "F:/douyi_mcp" not in result.model_dump_json()


def test_preflight_rejects_legacy_runtime_root() -> None:
    result = run_preflight(runtime_root=Path("F:/douyi_mcp/runtime"), live=False)

    assert result.ready is False
    assert result.checks["artifact_root"].error_code == "legacy_runtime_root"


def test_preflight_report_has_all_fail_closed_checks(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()

    result = run_preflight(runtime_root=runtime_root, live=False)

    assert set(result.checks) == {
        "postgres",
        "ffmpeg",
        "gpu",
        "artifact_root",
        "search_mcp",
        "reader_mcp",
        "tts_mcp",
    }
    assert result.ready is all(
        check.status == "available" for check in result.checks.values()
    )
    assert all("secret" not in check.detail.lower() for check in result.checks.values())


@pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell")
def test_powershell_preflight_writes_utf8_json_without_creating_runtime(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "missing-runtime"
    report_path = tmp_path / "preflight.json"
    script = ROOT / "ops" / "windows" / "test-shidu-preflight.ps1"
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-RuntimeRoot",
            str(runtime_root),
            "-ReportPath",
            str(report_path),
            "-PythonExecutable",
            sys.executable,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )

    assert completed.returncode == 1, completed.stderr
    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    assert payload["ready"] is False
    assert payload["checks"]["artifact_root"]["error_code"] == "runtime_root_missing"
    assert not runtime_root.exists()
    assert "F:/douyi_mcp" not in report_path.read_text(encoding="utf-8-sig")


def test_gpu_preflight_auto_falls_back_to_rocm_smi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...], str]] = []

    def command_check(
        command: str, arguments: list[str], error_prefix: str
    ) -> PreflightCheck:
        calls.append((command, tuple(arguments), error_prefix))
        if command == "nvidia-smi":
            return PreflightCheck(
                status="unavailable",
                detail="nvidia-smi is not installed.",
                error_code="gpu_nvidia_missing",
            )
        if command == "rocm-smi":
            return PreflightCheck(status="available", detail="card0 gfx1100")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.delenv("SHIDU_GPU_BACKEND", raising=False)
    monkeypatch.setattr(shidu_preflight, "_command_check", command_check)

    result = shidu_preflight._gpu_check()

    assert result.status == "available"
    assert result.detail == "ROCm: card0 gfx1100"
    assert [call[0] for call in calls] == ["nvidia-smi", "rocm-smi"]


def test_gpu_preflight_explicit_rocm_prefers_rocm_smi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def command_check(
        command: str, _arguments: list[str], _error_prefix: str
    ) -> PreflightCheck:
        calls.append(command)
        return PreflightCheck(status="available", detail="AMD Radeon PRO W7900")

    monkeypatch.setenv("SHIDU_GPU_BACKEND", "rocm")
    monkeypatch.setattr(shidu_preflight, "_command_check", command_check)

    result = shidu_preflight._gpu_check()

    assert result.status == "available"
    assert result.detail == "ROCm: AMD Radeon PRO W7900"
    assert calls == ["rocm-smi"]


def test_gpu_preflight_explicit_rocm_falls_back_to_rocminfo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def command_check(
        command: str, _arguments: list[str], _error_prefix: str
    ) -> PreflightCheck:
        calls.append(command)
        if command == "rocm-smi":
            return PreflightCheck(
                status="unavailable",
                detail="rocm-smi is not installed.",
                error_code="gpu_rocm_smi_missing",
            )
        raise AssertionError(f"unexpected generic command probe: {command}")

    monkeypatch.setenv("SHIDU_GPU_BACKEND", "rocm")
    monkeypatch.setattr(shidu_preflight, "_command_check", command_check)
    monkeypatch.setattr(
        shidu_preflight.shutil,
        "which",
        lambda command: "rocminfo-bin" if command == "rocminfo" else None,
    )
    monkeypatch.setattr(
        shidu_preflight,
        "_bounded_command_output",
        lambda *_args, **_kwargs: (
            0,
            """
********
Agent 1
********
  Name: AMD Ryzen 9
  Device Type: CPU
********
Agent 2
********
  Name: gfx1100
  Device Type: GPU
""",
        ),
    )

    result = shidu_preflight._gpu_check()

    assert result.status == "available"
    assert result.detail == "ROCm: gfx1100"
    assert calls == ["rocm-smi"]


@pytest.mark.parametrize(
    "output",
    [
        "ROCk module is loaded\n",
        """
********
Agent 1
********
  Name: AMD Ryzen 9
  Device Type: CPU
""",
        """
********
Agent 1
********
  Name: AMD Radeon Graphics
  Device Type: GPU
""",
        """
********
Agent 1
********
  Name: gfx1100
  Device Type: CPU
********
Agent 2
********
  Name: AMD Radeon Graphics
  Device Type: GPU
""",
    ],
)
def test_rocminfo_parser_rejects_output_without_same_agent_gpu_gfx(
    output: str,
) -> None:
    assert shidu_preflight._parse_rocminfo_gpu_name(output) is None


def test_rocminfo_parser_accepts_gpu_gfx_in_same_agent_block() -> None:
    output = """
ROCk module is loaded
********
Agent 1
********
  Name: AMD Ryzen 9
  Device Type: CPU
********
Agent 2
********
  Name: gfx1100
  Marketing Name: AMD Radeon PRO W7900
  Device Type: GPU
"""

    assert shidu_preflight._parse_rocminfo_gpu_name(output) == "gfx1100"


def test_bounded_command_rejects_oversized_output() -> None:
    result = shidu_preflight._bounded_command_output(
        sys.executable,
        ["-c", "print('private-output-' * 10000)"],
        timeout_seconds=5,
        maximum_output_bytes=1024,
    )

    assert result is None


def test_bounded_command_rejects_timeout() -> None:
    result = shidu_preflight._bounded_command_output(
        sys.executable,
        ["-c", "import time; time.sleep(2)"],
        timeout_seconds=0.05,
        maximum_output_bytes=1024,
    )

    assert result is None


@pytest.mark.parametrize("mode", ["success", "timeout", "oversize", "read-error"])
def test_bounded_command_closes_stdout_on_every_exit_path(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    class Stdout:
        def __init__(self) -> None:
            self.closed = False
            self.reads = 0

        def read(self, maximum: int) -> bytes:
            self.reads += 1
            if mode == "read-error":
                raise OSError("simulated pipe failure")
            if mode == "oversize" and self.reads == 1:
                return b"x" * maximum
            if mode == "success" and self.reads == 1:
                return b"ok"
            return b""

        def close(self) -> None:
            self.closed = True

    class Process:
        def __init__(self) -> None:
            self.stdout = Stdout()
            self.returncode = 0
            self.running = True
            self.terminated = False
            self.killed = False

        def poll(self):
            return None if self.running else self.returncode

        def wait(self, timeout: float):
            if mode == "timeout" and not self.terminated:
                raise subprocess.TimeoutExpired("fake", timeout)
            self.running = False
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.running = False

        def kill(self) -> None:
            self.killed = True
            self.running = False

    process = Process()
    monkeypatch.setattr(
        shidu_preflight.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )

    result = shidu_preflight._bounded_command_output(
        "fake",
        [],
        timeout_seconds=0.1,
        maximum_output_bytes=8,
    )

    assert process.stdout.closed is True
    assert result == ((0, "ok") if mode == "success" else None)


def test_rocminfo_check_does_not_leak_untrusted_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shidu_preflight.shutil, "which", lambda _command: "rocminfo")
    monkeypatch.setattr(
        shidu_preflight,
        "_bounded_command_output",
        lambda *_args, **_kwargs: (0, "private-token-without-an-agent"),
    )

    result = shidu_preflight._rocminfo_gpu_check()

    assert result.status == "unavailable"
    assert result.error_code == "gpu_rocminfo_unavailable"
    assert "private-token" not in result.detail


@pytest.mark.parametrize(
    ("endpoint", "discovery_path", "expected"),
    [
        ("http://127.0.0.1:18110", "/discover", "http://127.0.0.1:18110/discover"),
        (
            "http://127.0.0.1:18110/invoke",
            "/discover",
            "http://127.0.0.1:18110/discover",
        ),
        (
            "http://127.0.0.1:8788/mcp",
            "/phase2/discover",
            "http://127.0.0.1:8788/phase2/discover",
        ),
    ],
)
def test_discovery_url_accepts_only_known_invocation_paths(
    endpoint: str,
    discovery_path: str,
    expected: str,
) -> None:
    assert shidu_preflight._discovery_url(endpoint, discovery_path) == expected


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:18110/other",
        "http://127.0.0.1:18110/invoke?token=secret",
        "http://user:secret@127.0.0.1:18110/invoke",
    ],
)
def test_discovery_url_rejects_unknown_or_secret_bearing_endpoints(
    endpoint: str,
) -> None:
    with pytest.raises(ValueError):
        shidu_preflight._discovery_url(endpoint, "/discover")


def test_gpu_preflight_explicit_nvidia_keeps_nvidia_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...], str]] = []

    def command_check(
        command: str, arguments: list[str], error_prefix: str
    ) -> PreflightCheck:
        calls.append((command, tuple(arguments), error_prefix))
        return PreflightCheck(status="available", detail="NVIDIA RTX 4090, 555")

    monkeypatch.setenv("SHIDU_GPU_BACKEND", "nvidia")
    monkeypatch.setattr(shidu_preflight, "_command_check", command_check)

    result = shidu_preflight._gpu_check()

    assert result.status == "available"
    assert result.detail == "NVIDIA: NVIDIA RTX 4090, 555"
    assert calls == [
        (
            "nvidia-smi",
            ("--query-gpu=name,driver_version", "--format=csv,noheader"),
            "gpu_nvidia",
        )
    ]


def test_gpu_preflight_rejects_unknown_backend_without_probing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHIDU_GPU_BACKEND", "cuda")
    monkeypatch.setattr(
        shidu_preflight,
        "_command_check",
        lambda *_args, **_kwargs: pytest.fail("invalid backend must not be probed"),
    )

    result = shidu_preflight._gpu_check()

    assert result.status == "unavailable"
    assert result.error_code == "gpu_backend_invalid"
    assert "cuda" not in result.detail


def test_live_preflight_discovers_exact_mcp_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("SHIDU_DATABASE_URL", "postgresql://configured")
    monkeypatch.setenv(
        "SHIDU_SEARCH_MCP_ENDPOINT", "http://127.0.0.1:18110"
    )
    monkeypatch.setenv(
        "SHIDU_READER_MCP_ENDPOINT", "http://127.0.0.1:18111"
    )
    monkeypatch.setenv(
        "SHIDU_TTS_MCP_ENDPOINT", "http://127.0.0.1:8788"
    )
    contracts = {
        "http://127.0.0.1:18110/discover": {
            "service_version": "shidu-search-mcp.v1",
            "tool_name": "coding_plan.search",
            "schema_digest": (
                "6f5b772b2612821f6290ec65f784bc6b8fd9ce6fd3e6c80164cbb5eca2c54c8f"
            ),
        },
        "http://127.0.0.1:18111/discover": {
            "service_version": "shidu-reader-mcp.v1",
            "tool_name": "coding_plan.read_page",
            "schema_digest": (
                "e498bbc04216f04c3c991ed99dbd14eb16a161d4f33c3d97ff34cf943f313e13"
            ),
            "security_capabilities": {
                "address_binding": "caller-pinned-ip-v1",
                "redirect_handling": "forbidden",
                "prefetch_validation": "required",
            },
        },
        "http://127.0.0.1:8788/phase2/discover": {
            "service_version": "qwen3-tts-mcp.phase2.v1",
            "model_id": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            "tool_name": "qwen_tts.custom_voice",
            "schema_digest": (
                "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa"
            ),
            "speakers": ["Serena", "Uncle_Fu"],
        },
    }
    monkeypatch.setattr(
        "creative_hub.shidu_preflight._load_json_url",
        lambda url, timeout_seconds=5.0: contracts[url],
    )
    monkeypatch.setattr(
        "creative_hub.shidu_preflight._postgres_live_check",
        lambda: (True, "PostgreSQL round trip succeeded."),
    )
    monkeypatch.setattr(
        "creative_hub.shidu_preflight._command_check",
        lambda *_args, **_kwargs: PreflightCheck(
            status="available", detail="available"
        ),
    )

    result = run_preflight(runtime_root=runtime_root, live=True)

    assert result.ready is True
    assert result.checks["postgres"].status == "available"
    assert result.checks["search_mcp"].status == "available"
    assert result.checks["reader_mcp"].status == "available"
    assert result.checks["tts_mcp"].status == "available"
