"""R01 Radeon probe: unit tests with an injected Env (no real GPU required)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from sprite_workshop.radeon_probe import (
    DEFAULT_EXPECTED_SHA256,
    EXIT_BACKEND_UNAVAILABLE,
    EXIT_ENVIRONMENT,
    EXIT_PASS,
    MASKED,
    HttpResult,
    ProbeEnv,
    SubprocessResult,
    is_loopback_endpoint,
    mask_endpoint,
    render_human,
    run_probe,
)

GIB = 1024**3


class FakeCuda:
    def is_available(self) -> bool:
        return True

    def device_count(self) -> int:
        return 1

    def get_device_name(self, index: int) -> str:
        return "AMD Radeon Fake 9000"

    def get_device_properties(self, index: int) -> types.SimpleNamespace:
        return types.SimpleNamespace(total_memory=24 * GIB)

    def mem_get_info(self) -> tuple[int, int]:
        return (18 * GIB, 24 * GIB)

    def init(self) -> None:
        return None

    def synchronize(self) -> None:
        return None


class FakeVersion:
    hip: str | None = "7.2.0"
    rocm: str | None = None


class FakeTorch:
    __version__ = "2.9.1"
    version = FakeVersion()
    cuda = FakeCuda()


class FakeCudaOff:
    def is_available(self) -> bool:
        return False

    def device_count(self) -> int:
        return 0

    def get_device_name(self, index: int) -> str:
        raise AssertionError("no device")

    def get_device_properties(self, index: int) -> types.SimpleNamespace:
        raise AssertionError("no device")

    def mem_get_info(self) -> tuple[int, int]:
        raise AssertionError("no device")


class FakeTorchCpu:
    __version__ = "2.9.1"
    version = types.SimpleNamespace(hip=None, rocm=None)
    cuda = FakeCudaOff()


class FakeCudaBroken:
    def is_available(self) -> bool:
        raise RuntimeError("driver probe failed")

    def device_count(self) -> int:
        raise RuntimeError("driver probe failed")

    def get_device_name(self, index: int) -> str:
        raise RuntimeError("driver probe failed")


class FakeTorchBrokenGpu:
    __version__ = "2.9.1"
    version = FakeVersion()
    cuda = FakeCudaBroken()


def fake_torch() -> FakeTorch:
    return FakeTorch()


def fake_torch_cpu() -> FakeTorchCpu:
    return FakeTorchCpu()


def fake_torch_broken_gpu() -> FakeTorchBrokenGpu:
    return FakeTorchBrokenGpu()


def no_torch() -> FakeTorch:
    raise ImportError("no module named 'torch'")


def run_ok(argv, timeout: float) -> SubprocessResult:
    return SubprocessResult(
        0,
        json.dumps(
            {
                "torch": "2.9.1",
                "cpu_matmul": 1.0,
                "gpu_matmul": 2.0,
                "gpu": "AMD Radeon Fake 9000",
            }
        ),
        "",
        0.12,
    )


def run_timeout(argv, timeout: float) -> SubprocessResult:
    return SubprocessResult(-1, "", "", 120.0, timed_out=True)


def run_fail(argv, timeout: float) -> SubprocessResult:
    return SubprocessResult(1, "", "HIP error at /var/secret/driver.cpp:12", 0.2)


def run_bad_json(argv, timeout: float) -> SubprocessResult:
    return SubprocessResult(0, "not json at all", "", 0.1)


def run_spawn_error(argv, timeout: float) -> SubprocessResult:
    return SubprocessResult(0, "", "", 0.0, spawn_error="FileNotFoundError")


def http_ok(url, timeout: float) -> HttpResult:
    return HttpResult(
        200,
        {
            "system": {
                "comfyui_version": "0.30.0",
                "vram_total": 24 * GIB,
            },
            "devices": [{"name": "gfx1100"}],
        },
        None,
        0.03,
    )


def http_down(url, timeout: float) -> HttpResult:
    return HttpResult(None, None, "URLError", 0.02)


def http_http500(url, timeout: float) -> HttpResult:
    return HttpResult(500, None, None, 0.02)


def http_bad_json(url, timeout: float) -> HttpResult:
    return HttpResult(200, None, None, 0.02)


def make_env(**overrides) -> ProbeEnv:
    base = dict(
        environ={},
        sys_executable=sys.executable,
        reveal_paths=False,
        reveal_endpoints=False,
        model_path=None,
        comfyui_endpoint="http://127.0.0.1:8188",
        smoke_timeout=120.0,
        http_timeout=5.0,
        expected_sha256=None,
        verify_sha256=False,
        import_torch=fake_torch,
        run_subprocess=run_ok,
        http_get=http_ok,
    )
    base.update(overrides)
    return ProbeEnv(**base)


def by_name(report, name: str):
    for check in report.checks:
        if check.name == name:
            return check
    raise AssertionError(f"missing check {name!r}")


class ProbeEnvTestCase(unittest.TestCase):
    def test_from_os_defaults(self) -> None:
        env = ProbeEnv.from_os(environ={})
        self.assertEqual(env.comfyui_endpoint, "http://127.0.0.1:8188")
        self.assertEqual(env.smoke_timeout, 120.0)
        self.assertEqual(env.http_timeout, 5.0)
        self.assertFalse(env.reveal_paths)
        self.assertFalse(env.reveal_endpoints)
        self.assertFalse(env.verify_sha256)
        self.assertIsNone(env.model_path)
        self.assertEqual(env.expected_sha256, DEFAULT_EXPECTED_SHA256)

    def test_from_os_parses_flags_and_values(self) -> None:
        env = ProbeEnv.from_os(
            environ={
                "RADEON_PROBE_VERIFY_SHA256": "1",
                "RADEON_PROBE_MODEL_PATH": "~/models/ckpt.safetensors",
                "RADEON_PROBE_COMFYUI_ENDPOINT": "http://box.example:8188",
                "RADEON_PROBE_SMOKE_TIMEOUT": "30",
                "RADEON_PROBE_HTTP_TIMEOUT": "2.5",
                "RADEON_PROBE_REVEAL_PATHS": "true",
                "RADEON_PROBE_REVEAL_ENDPOINTS": "yes",
            }
        )
        self.assertTrue(env.verify_sha256)
        self.assertTrue(env.reveal_paths)
        self.assertTrue(env.reveal_endpoints)
        self.assertEqual(env.model_path, Path("~/models/ckpt.safetensors").expanduser())
        self.assertEqual(env.comfyui_endpoint, "http://box.example:8188")
        self.assertEqual(env.smoke_timeout, 30.0)
        self.assertEqual(env.http_timeout, 2.5)

    def test_from_os_ignores_bad_floats(self) -> None:
        env = ProbeEnv.from_os(
            environ={
                "RADEON_PROBE_SMOKE_TIMEOUT": "abc",
                "RADEON_PROBE_HTTP_TIMEOUT": "",
            }
        )
        self.assertEqual(env.smoke_timeout, 120.0)
        self.assertEqual(env.http_timeout, 5.0)

    def test_from_os_overrides_win(self) -> None:
        env = ProbeEnv.from_os(
            environ={"RADEON_PROBE_MODEL_PATH": "a.safetensors"},
            model_path=Path("b.safetensors"),
        )
        self.assertEqual(env.model_path, Path("b.safetensors"))


class MaskingTestCase(unittest.TestCase):
    def test_model_path_masked_by_default_in_json_and_human(self) -> None:
        env = make_env(model_path=Path("C:/secret/models/ckpt.safetensors"))
        report = run_probe(env)
        model = by_name(report, "model")
        self.assertEqual(model.detail["path"], MASKED)
        self.assertNotIn("ckpt.safetensors", report.to_json())
        self.assertNotIn("C:/secret", render_human(report, env))

    def test_reveal_paths_shows_real_path(self) -> None:
        env = make_env(
            model_path=Path("C:/secret/models/ckpt.safetensors"), reveal_paths=True
        )
        report = run_probe(env)
        model = by_name(report, "model")
        self.assertEqual(
            model.detail["path"], str(Path("C:/secret/models/ckpt.safetensors"))
        )

    def test_python_executable_masked_by_default(self) -> None:
        report = run_probe(make_env())
        python = by_name(report, "python")
        self.assertEqual(python.detail["executable"], MASKED)
        self.assertNotIn(sys.executable, report.to_json())

    def test_non_loopback_endpoint_masked_in_both_outputs(self) -> None:
        env = make_env(comfyui_endpoint="http://192.168.50.10:8188")
        report = run_probe(env)
        comfyui = by_name(report, "comfyui")
        self.assertIn(MASKED, comfyui.detail["endpoint"])
        self.assertNotIn("192.168.50.10", report.to_json())
        self.assertNotIn("192.168.50.10", render_human(report, env))

    def test_loopback_endpoint_shown_by_default(self) -> None:
        report = run_probe(make_env())
        comfyui = by_name(report, "comfyui")
        self.assertEqual(
            comfyui.detail["endpoint"], "http://127.0.0.1:8188/system_stats"
        )

    def test_reveal_endpoints_shows_non_loopback(self) -> None:
        env = make_env(
            comfyui_endpoint="http://box.example:8188", reveal_endpoints=True
        )
        report = run_probe(env)
        comfyui = by_name(report, "comfyui")
        self.assertEqual(
            comfyui.detail["endpoint"], "http://box.example:8188/system_stats"
        )

    def test_is_loopback_endpoint(self) -> None:
        for url in (
            "http://127.0.0.1:8188/",
            "http://localhost:8188/",
            "http://[::1]:8188/",
            "http://127.0.0.2:8188/",
        ):
            self.assertTrue(is_loopback_endpoint(url), url)
        self.assertFalse(is_loopback_endpoint("http://10.0.0.5:8188/"))
        self.assertFalse(is_loopback_endpoint("http://[2001:db8::1]:8188/"))

    def test_mask_endpoint(self) -> None:
        env = make_env()
        self.assertEqual(
            mask_endpoint("http://192.168.1.9:8188/system_stats", env),
            "http://<redacted>/system_stats",
        )
        self.assertEqual(
            mask_endpoint("http://127.0.0.1:8188/system_stats", env),
            "http://127.0.0.1:8188/system_stats",
        )


class ExitCodeTestCase(unittest.TestCase):
    def test_all_ok_exit_zero(self) -> None:
        report = run_probe(make_env())
        self.assertEqual(report.exit_code, EXIT_PASS)
        self.assertEqual(report.verdict, "PASS")

    def test_missing_torch_exit_5(self) -> None:
        report = run_probe(make_env(import_torch=no_torch))
        self.assertEqual(report.exit_code, EXIT_BACKEND_UNAVAILABLE)
        self.assertEqual(report.verdict, "BACKEND_UNAVAILABLE")
        self.assertEqual(by_name(report, "torch").status, "fail")
        self.assertEqual(by_name(report, "hip").status, "skip")
        self.assertEqual(by_name(report, "gpu").status, "skip")
        self.assertEqual(by_name(report, "vram").status, "skip")
        self.assertEqual(by_name(report, "smoke").status, "skip")

    def test_cpu_torch_without_hip_exit_5(self) -> None:
        report = run_probe(make_env(import_torch=fake_torch_cpu))
        self.assertEqual(report.exit_code, EXIT_BACKEND_UNAVAILABLE)
        self.assertEqual(by_name(report, "torch").status, "ok")
        self.assertEqual(by_name(report, "hip").status, "fail")
        self.assertEqual(by_name(report, "gpu").status, "fail")

    def test_gpu_query_error_exit_4(self) -> None:
        report = run_probe(make_env(import_torch=fake_torch_broken_gpu))
        self.assertEqual(report.exit_code, EXIT_ENVIRONMENT)
        self.assertEqual(by_name(report, "gpu").status, "fail")

    def test_smoke_timeout_exit_4(self) -> None:
        report = run_probe(make_env(run_subprocess=run_timeout))
        self.assertEqual(report.exit_code, EXIT_ENVIRONMENT)
        smoke = by_name(report, "smoke")
        self.assertEqual(smoke.status, "fail")
        self.assertTrue(smoke.detail["timed_out"])

    def test_smoke_failure_exit_4(self) -> None:
        report = run_probe(make_env(run_subprocess=run_fail))
        self.assertEqual(report.exit_code, EXIT_ENVIRONMENT)
        self.assertEqual(by_name(report, "smoke").detail["returncode"], 1)

    def test_comfyui_down_exit_5(self) -> None:
        report = run_probe(make_env(http_get=http_down))
        self.assertEqual(report.exit_code, EXIT_BACKEND_UNAVAILABLE)
        self.assertEqual(by_name(report, "comfyui").status, "fail")

    def test_model_missing_exit_5(self) -> None:
        env = make_env(model_path=Path("Z:/definitely/not/here.safetensors"))
        report = run_probe(env)
        self.assertEqual(report.exit_code, EXIT_BACKEND_UNAVAILABLE)
        self.assertEqual(by_name(report, "model").status, "fail")

    def test_worst_severity_wins(self) -> None:
        env = make_env(
            model_path=Path("Z:/definitely/not/here.safetensors"),
            http_get=http_down,
            run_subprocess=run_timeout,
        )
        report = run_probe(env)
        self.assertEqual(report.exit_code, EXIT_BACKEND_UNAVAILABLE)


class SmokeTestCase(unittest.TestCase):
    def test_ok_reports_operators(self) -> None:
        report = run_probe(make_env())
        smoke = by_name(report, "smoke")
        self.assertEqual(smoke.status, "ok")
        self.assertIsNotNone(smoke.detail["cpu_matmul"])
        self.assertIsNotNone(smoke.detail["gpu_matmul"])

    def test_nonzero_hides_stderr_by_default(self) -> None:
        report = run_probe(make_env(run_subprocess=run_fail))
        payload = report.to_json()
        self.assertNotIn("driver.cpp", payload)
        self.assertNotIn("secret", payload)
        self.assertIn("suppressed", payload)

    def test_nonzero_reveals_stderr_when_both_flags_on(self) -> None:
        env = make_env(
            run_subprocess=run_fail, reveal_paths=True, reveal_endpoints=True
        )
        report = run_probe(env)
        smoke = by_name(report, "smoke")
        self.assertIn("driver.cpp", smoke.detail["stderr_tail"])

    def test_invalid_stdout_is_failure(self) -> None:
        report = run_probe(make_env(run_subprocess=run_bad_json))
        self.assertEqual(by_name(report, "smoke").status, "fail")
        self.assertEqual(report.exit_code, EXIT_ENVIRONMENT)

    def test_spawn_error_is_failure(self) -> None:
        report = run_probe(make_env(run_subprocess=run_spawn_error))
        smoke = by_name(report, "smoke")
        self.assertEqual(smoke.status, "fail")
        self.assertEqual(smoke.detail["spawn_error"], "FileNotFoundError")


class ComfyUITestCase(unittest.TestCase):
    def test_ok_reports_version(self) -> None:
        report = run_probe(make_env())
        comfyui = by_name(report, "comfyui")
        self.assertEqual(comfyui.status, "ok")
        self.assertEqual(comfyui.detail["http_status"], 200)
        self.assertEqual(comfyui.detail["comfyui_version"], "0.30.0")
        self.assertEqual(comfyui.detail["device_count"], 1)

    def test_connection_error_is_failure(self) -> None:
        report = run_probe(make_env(http_get=http_down))
        comfyui = by_name(report, "comfyui")
        self.assertEqual(comfyui.status, "fail")
        self.assertEqual(comfyui.detail["error"], "URLError")

    def test_non_200_is_failure(self) -> None:
        report = run_probe(make_env(http_get=http_http500))
        self.assertEqual(by_name(report, "comfyui").status, "fail")

    def test_non_json_body_is_failure(self) -> None:
        report = run_probe(make_env(http_get=http_bad_json))
        self.assertEqual(by_name(report, "comfyui").status, "fail")


class ModelTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "ckpt.safetensors"
        self.path.write_bytes(b"x" * 4096)
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_model_path_is_skip(self) -> None:
        report = run_probe(make_env())
        self.assertEqual(by_name(report, "model").status, "skip")
        self.assertEqual(report.exit_code, EXIT_PASS)

    def test_present_without_verify_is_ok(self) -> None:
        env = make_env(model_path=self.path)
        report = run_probe(env)
        model = by_name(report, "model")
        self.assertEqual(model.status, "ok")
        self.assertIsNone(model.detail["sha256"])

    def test_verify_match_is_ok(self) -> None:
        env = make_env(
            model_path=self.path, verify_sha256=True, expected_sha256=self.sha
        )
        report = run_probe(env)
        model = by_name(report, "model")
        self.assertEqual(model.status, "ok")
        self.assertEqual(model.detail["sha256"], self.sha)
        self.assertEqual(report.exit_code, EXIT_PASS)

    def test_verify_mismatch_exit_4(self) -> None:
        env = make_env(
            model_path=self.path,
            verify_sha256=True,
            expected_sha256="0" * 64,
        )
        report = run_probe(env)
        self.assertEqual(report.exit_code, EXIT_ENVIRONMENT)
        self.assertEqual(report.verdict, "ENVIRONMENT_ERROR")
        self.assertEqual(by_name(report, "model").status, "fail")

    def test_verify_without_expected_hash_warns(self) -> None:
        env = make_env(model_path=self.path, verify_sha256=True, expected_sha256=None)
        report = run_probe(env)
        model = by_name(report, "model")
        self.assertEqual(model.status, "warn")
        self.assertEqual(report.exit_code, EXIT_PASS)

    def test_default_expected_hash_is_hex64(self) -> None:
        self.assertEqual(len(DEFAULT_EXPECTED_SHA256), 64)
        int(DEFAULT_EXPECTED_SHA256, 16)


class ReportTestCase(unittest.TestCase):
    def test_json_shape_and_masking_meta(self) -> None:
        report = run_probe(make_env())
        payload = json.loads(report.to_json())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["exit_code"], report.exit_code)
        self.assertEqual(payload["masking"], {"paths": "masked", "endpoints": "masked"})
        self.assertEqual(len(payload["checks"]), 8)
        names = {check["name"] for check in payload["checks"]}
        self.assertEqual(
            names,
            {"python", "torch", "hip", "gpu", "vram", "smoke", "comfyui", "model"},
        )

    def test_every_check_has_stable_fields(self) -> None:
        for check in run_probe(make_env()).checks:
            self.assertIn(check.status, {"ok", "warn", "skip", "fail"})
            self.assertIn(check.exit_code, {0, 4, 5})
            self.assertTrue(check.summary)

    def test_human_output_lists_checks_and_verdict(self) -> None:
        env = make_env()
        report = run_probe(env)
        text = render_human(report, env)
        for name in (
            "python",
            "torch",
            "hip",
            "gpu",
            "vram",
            "smoke",
            "comfyui",
            "model",
        ):
            self.assertIn(name, text)
        self.assertIn("verdict: PASS (exit 0)", text)

    def test_probe_from_os_runs(self) -> None:
        from sprite_workshop.radeon_probe import probe_from_os

        report = probe_from_os()
        self.assertEqual(report.schema_version, 1)
        self.assertIn(report.exit_code, {0, 4, 5})


class CliTestCase(unittest.TestCase):
    def _run_cli(self, *extra: str):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "check_radeon.py"
        clean_env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("RADEON_PROBE_")
        }
        return subprocess.run(
            [sys.executable, str(script), *extra],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env=clean_env,
            cwd=str(root),
        )

    def test_cli_emits_structured_json_and_allowed_exit(self) -> None:
        proc = self._run_cli("--json")
        self.assertIn(
            proc.returncode, {0, 2, 4, 5}, msg=proc.stderr[-500:] or proc.stdout[-500:]
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["exit_code"], proc.returncode)
        self.assertTrue(payload["checks"])
        self.assertEqual(payload["masking"]["paths"], "masked")

    def test_cli_human_output_masks_and_reports(self) -> None:
        proc = self._run_cli()
        self.assertIn(proc.returncode, {0, 2, 4, 5}, msg=proc.stderr[-500:])
        self.assertIn("verdict:", proc.stdout)
        self.assertNotIn(sys.executable, proc.stdout)

    def test_cli_usage_error_exits_2(self) -> None:
        proc = self._run_cli("--definitely-not-a-flag")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage", proc.stderr.lower())


if __name__ == "__main__":
    unittest.main()
