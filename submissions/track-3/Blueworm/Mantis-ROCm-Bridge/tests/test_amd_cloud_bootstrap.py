from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Sequence

from mantis_rocm_bridge.amd_cloud_bootstrap import (
    STAGE1_WHEEL_KEYS,
    STAGE1_DEPENDENCY_PACKAGE_NAMES,
    CONTROLLED_NETWORK_BOUNDARY,
    ContractError,
    assert_dependency_command_is_non_accel,
    assert_install_command_is_offline,
    assert_single_visible_gpu,
    build_dependency_install_argv,
    build_local_rocm_install_argv,
    detect_visible_gpu_count,
    load_stage1_inventory,
    parse_visible_gpu_count,
    redact_freeze,
    run_stage1_bootstrap,
    sha256_file,
    verify_stage1_wheels,
    write_receipt_atomic,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/amd-cloud-runtime-v1.json"

# Canonical stage-1 wheel paths transcribed in the runtime config.
WHEEL_PATHS = {
    "torch": "/torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl",
    "torchvision": "/torchvision-0.24.0+rocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl",
    "torchaudio": "/torchaudio-2.9.0+rocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl",
    "triton": "/triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl",
}


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_fake_runner(*, gpu_count: int = 1, smoke_device_count: int = 1, install_ok: bool = True, dep_install_ok: bool = True):
    """Return a subprocess runner stub that never touches a real GPU or shell."""

    rocminfo = "\n\n".join(
        [f"Agent {i + 1}\n  Name: gfx1100" for i in range(max(gpu_count, 0))]
    )
    smoke = json.dumps(
        {
            "torch_version": "2.9.1+rocm7.2.1",
            "torchvision_version": "0.24.0+rocm7.2.1",
            "torchaudio_version": "2.9.0+rocm7.2.1",
            "triton_version": "3.5.1+rocm7.2.1",
            "hip_version": "6.4.42225",
            "cuda_available": smoke_device_count > 0,
            "device_count": smoke_device_count,
            "device_name": "gfx1100" if smoke_device_count > 0 else None,
        }
    )

    def runner(argv: Sequence[str]) -> "_FakeCompleted":
        joined = list(argv)
        if joined and str(joined[0]).endswith("rocminfo"):
            return _FakeCompleted(0, stdout=rocminfo)
        if "-c" in joined:
            return _FakeCompleted(0, stdout=smoke)
        if "freeze" in joined:
            # A secret-looking line exercises end-to-end redaction in the receipt.
            return _FakeCompleted(
                0,
                stdout=(
                    "torch==2.9.1+rocm7.2.1\n"
                    "torchvision==0.24.0+rocm7.2.1\n"
                    "torchaudio==2.9.0+rocm7.2.1\n"
                    "triton==3.5.1+rocm7.2.1\n"
                    "secret-api-token==s3cr3tvalu3-canary\n"
                ),
            )
        if "install" in joined:
            # Check if this is phase-2 (local rocm install has --no-index --no-deps)
            is_phase2 = "--no-index" in joined and "--no-deps" in joined
            if is_phase2:
                return _FakeCompleted(0 if install_ok else 1, stderr="" if install_ok else "phase2-boom")
            else:
                # Phase-1 dependency install
                return _FakeCompleted(0 if dep_install_ok else 1, stderr="" if dep_install_ok else "phase1-boom")
        return _FakeCompleted(0)

    return runner


def _fake_which(name: str) -> str | None:
    return f"/usr/bin/{name}" if name in ("rocminfo", "amd-smi", "rocm-smi") else None


def _write_fake_wheels(root: Path) -> dict[str, str]:
    """Materialize fake wheels mirroring the instance / layout; return real hashes."""

    hashes: dict[str, str] = {}
    for key, path in WHEEL_PATHS.items():
        target = root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = f"fake-wheel-bytes::{key}::{path}".encode("utf-8")
        target.write_bytes(content)
        hashes[key] = hashlib.sha256(content).hexdigest()
    return hashes


def _temp_config(root: Path, *, hash_overrides: dict[str, str] | None = None) -> Path:
    base = json.loads(CONFIG.read_text(encoding="utf-8"))
    hashes = _write_fake_wheels(root)
    hashes.update(hash_overrides or {})
    for key, digest in hashes.items():
        base["stage0_inventory"]["official_wheels"][key]["sha256"] = digest
    cfg = root / "amd-cloud-runtime-v1.json"
    cfg.write_text(json.dumps(base, indent=2, sort_keys=True), encoding="utf-8")
    return cfg


class InventoryLoadingTests(unittest.TestCase):
    def test_runtime_config_loads_four_stage1_wheels(self) -> None:
        inventory = load_stage1_inventory(CONFIG)
        self.assertEqual([w["key"] for w in inventory["wheels"]], list(STAGE1_WHEEL_KEYS))
        self.assertEqual(inventory["instance_id"], "u-11422-e97d3fd5")
        self.assertEqual(inventory["venv_path"], "/workspace/rdna")
        self.assertEqual(inventory["gpu"]["vram_bytes"], 51522830336)
        for wheel in inventory["wheels"]:
            self.assertTrue(wheel["path"].startswith("/"))
            self.assertEqual(len(wheel["sha256"]), 64)

    def test_status_stage0_is_accepted(self) -> None:
        """Original stage0_inventory_verified status is accepted."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = _temp_config(root)
            data = json.loads(cfg.read_text(encoding="utf-8"))
            data["status"] = "stage0_inventory_verified"
            cfg.write_text(json.dumps(data), encoding="utf-8")
            # Should load without error
            inventory = load_stage1_inventory(cfg)
            self.assertEqual(inventory["venv_path"], "/workspace/rdna")

    def test_status_stage2_is_accepted(self) -> None:
        """Promoted stage2_runtime_verified status is accepted (monotonic progression)."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = _temp_config(root)
            data = json.loads(cfg.read_text(encoding="utf-8"))
            data["status"] = "stage2_runtime_verified"
            cfg.write_text(json.dumps(data), encoding="utf-8")
            # Should load without error
            inventory = load_stage1_inventory(cfg)
            self.assertEqual(inventory["venv_path"], "/workspace/rdna")

    def test_status_invalid_unknown_is_rejected(self) -> None:
        """Unknown or invalid statuses are rejected (fail-closed)."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = _temp_config(root)
            data = json.loads(cfg.read_text(encoding="utf-8"))
            data["status"] = "awaiting_platform_recovery"
            cfg.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ContractError) as ctx:
                load_stage1_inventory(cfg)
            self.assertIn("stage-1 bootstrap requires", str(ctx.exception))
            self.assertIn("awaiting_platform_recovery", str(ctx.exception))


class WheelHashTests(unittest.TestCase):
    def test_verify_passes_when_fake_wheels_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hashes = _write_fake_wheels(root)
            wheels = [
                {"key": key, "path": path, "sha256": hashes[key]}
                for key, path in WHEEL_PATHS.items()
            ]
            verified = verify_stage1_wheels(wheels, root=root)
            self.assertEqual(len(verified), 4)
            self.assertTrue(all(item["verified"] for item in verified))

    def test_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hashes = _write_fake_wheels(root)
            wheels = [
                {"key": key, "path": path, "sha256": hashes[key]}
                for key, path in WHEEL_PATHS.items()
            ]
            bad = "0" * 64
            wheels[0]["sha256"] = bad  # torch digest is now wrong
            with self.assertRaises(ContractError) as ctx:
                verify_stage1_wheels(wheels, root=root)
            self.assertIn("sha256 mismatch", str(ctx.exception))

    def test_missing_wheel_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheels = [
                {"key": key, "path": path, "sha256": "f" * 64}
                for key, path in WHEEL_PATHS.items()
            ]
            with self.assertRaises(ContractError) as ctx:
                verify_stage1_wheels(wheels, root=root)
            self.assertIn("missing on disk", str(ctx.exception))

    def test_sha256_file_is_real_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blob"
            path.write_bytes(b"abc")
            self.assertEqual(sha256_file(path), hashlib.sha256(b"abc").hexdigest())


class GpuDetectionTests(unittest.TestCase):
    def test_parse_counts_only_gfx_agents(self) -> None:
        text = (
            "Agent 1\n  Name:          AMD CPU\n\n"
            "Agent 2\n  Name:          gfx1100\n"
        )
        self.assertEqual(parse_visible_gpu_count(text), 1)

    def test_parse_counts_multiple_gpus(self) -> None:
        text = "Agent 1\n  Name: gfx1100\n\nAgent 2\n  Name: gfx1100\n"
        self.assertEqual(parse_visible_gpu_count(text), 2)

    def test_parse_zero_when_no_gfx(self) -> None:
        self.assertEqual(parse_visible_gpu_count("Agent 1\n  Name: AMD CPU\n"), 0)

    def test_detect_uses_runner_and_which(self) -> None:
        count = detect_visible_gpu_count(
            runner=_make_fake_runner(gpu_count=1), which=_fake_which
        )
        self.assertEqual(count, 1)

    def test_assert_single_gpu_rejects_non_one(self) -> None:
        for value in (0, 2, -1):
            with self.assertRaises(ContractError):
                assert_single_visible_gpu(value)
        assert_single_visible_gpu(1)  # exactly one is accepted


class OfflineInstallCommandTests(unittest.TestCase):
    def _wheels(self) -> list[dict[str, str]]:
        return [
            {"key": key, "path": path, "sha256": "a" * 64}
            for key, path in WHEEL_PATHS.items()
        ]

    def test_dependency_install_command_is_whitelist_only(self) -> None:
        argv = build_dependency_install_argv("/workspace/rdna/bin/python")
        # No --no-index; phase 1 can reach network
        self.assertNotIn("--no-index", argv)
        # All whitelisted dependencies are present
        for name in STAGE1_DEPENDENCY_PACKAGE_NAMES:
            self.assertTrue(any(name in str(token) for token in argv))
        assert_dependency_command_is_non_accel(argv)

    def test_dependency_command_rejects_accel_packages(self) -> None:
        bad = ["python", "-m", "pip", "install", "filelock", "torch"]
        with self.assertRaises(ContractError):
            assert_dependency_command_is_non_accel(bad)

    def test_dependency_command_rejects_unknown_packages(self) -> None:
        bad = ["python", "-m", "pip", "install", "filelock", "unknown-pkg"]
        with self.assertRaises(ContractError):
            assert_dependency_command_is_non_accel(bad)

    def test_dependency_command_rejects_incomplete_whitelist(self) -> None:
        bad = ["python", "-m", "pip", "install", "filelock", "numpy"]
        with self.assertRaises(ContractError):
            assert_dependency_command_is_non_accel(bad)

    def test_local_rocm_install_command_is_offline_and_local_only(self) -> None:
        argv = build_local_rocm_install_argv("/workspace/rdna/bin/python", self._wheels())
        self.assertIn("--no-index", argv)
        self.assertIn("--no-deps", argv)
        for path in WHEEL_PATHS.values():
            self.assertIn(path, argv)
        # No bare network torch token is present.
        rendered = " ".join(argv)
        self.assertNotIn(" install torch", rendered)
        self.assertNotIn("torch==", rendered)
        assert_install_command_is_offline(argv, self._wheels())

    def test_bare_network_torch_install_is_rejected(self) -> None:
        bad = ["python", "-m", "pip", "install", "--no-index", "--find-links", "/", "torch"]
        with self.assertRaises(ContractError):
            assert_install_command_is_offline(bad, self._wheels())

    def test_version_pinned_torch_from_network_is_rejected(self) -> None:
        bad = ["python", "-m", "pip", "install", "torch==2.9.1"]
        with self.assertRaises(ContractError):
            assert_install_command_is_offline(bad, self._wheels())

    def test_missing_no_index_is_rejected(self) -> None:
        bad = ["python", "-m", "pip", "install", "--find-links", "/"]
        bad += list(WHEEL_PATHS.values())
        with self.assertRaises(ContractError):
            assert_install_command_is_offline(bad, self._wheels())

    def test_local_wheel_path_is_not_flagged_as_network_torch(self) -> None:
        # The local wheel path contains 'torch' but must not trip the guard.
        argv = build_local_rocm_install_argv("/workspace/rdna/bin/python", self._wheels())
        assert_install_command_is_offline(argv, self._wheels())


class ReceiptAtomicWriteTests(unittest.TestCase):
    def test_receipt_is_not_overwritten_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            write_receipt_atomic({"schema_version": 1, "stage1_pass": True}, path)
            self.assertTrue(path.exists())
            with self.assertRaises(ContractError) as ctx:
                write_receipt_atomic({"schema_version": 1, "stage1_pass": True}, path)
            self.assertIn("refusing to overwrite", str(ctx.exception))
            # Original content is preserved unchanged.
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["stage1_pass"])

    def test_overwrite_flag_replaces_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            write_receipt_atomic({"schema_version": 1, "n": 1}, path)
            write_receipt_atomic({"schema_version": 1, "n": 2}, path, overwrite=True)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["n"], 2)


class RedactionTests(unittest.TestCase):
    def test_secret_looking_lines_are_redacted(self) -> None:
        freeze = "torch==2.9.1\nmy-api-token==abc123\nsecret-key==zzz\n"
        out = redact_freeze(freeze)
        self.assertIn("torch==2.9.1", out)
        self.assertNotIn("abc123", out)
        self.assertNotIn("zzz", out)
        self.assertIn("<redacted>", out)


class Stage1BootstrapEndToEndTests(unittest.TestCase):
    def _bootstrap(self, root: Path, **overrides):
        cfg = _temp_config(root, hash_overrides=overrides.pop("hash_overrides", None))
        return run_stage1_bootstrap(
            config_path=cfg,
            receipt_path=root / "stage1-receipt.json",
            venv_path=root / "rdna",
            find_links_root=root,
            python_exe="/usr/bin/python3",
            runner=overrides.pop("runner", _make_fake_runner()),
            which=overrides.pop("which", _fake_which),
            root=root,
            **overrides,
        )

    def test_dry_run_validates_without_writing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = self._bootstrap(root, execute=False)
            # Dry-run: validation_pass=True (static checks pass) and stage1_pass=False (not executed)
            self.assertTrue(receipt["validation_pass"])
            self.assertFalse(receipt["stage1_pass"])
            self.assertFalse(receipt["executed"])
            self.assertTrue(receipt["checks"]["wheel_hashes_verified"])
            # All static validation checks are True
            self.assertTrue(receipt["checks"]["single_rocm_tool_present"])
            self.assertTrue(receipt["checks"]["single_gpu_visible"])
            self.assertTrue(receipt["checks"]["install_command_offline"])
            self.assertTrue(receipt["checks"]["no_network_torch_install"])
            # All execution checks (including version checks) are False when not executed
            self.assertFalse(receipt["checks"]["venv_created"])
            self.assertFalse(receipt["checks"]["offline_rocm_wheel_stack_installed"])
            self.assertFalse(receipt["checks"]["torch_hip_smoke_passed"])
            self.assertFalse(receipt["checks"]["single_amd_device_visible_to_torch"])
            # All version checks are False when smoke data is missing (they belong to execution_checks)
            self.assertFalse(receipt["checks"]["torch_version_matches_target"])
            self.assertFalse(receipt["checks"]["torchvision_version_matches_target"])
            self.assertFalse(receipt["checks"]["torchaudio_version_matches_target"])
            self.assertFalse(receipt["checks"]["triton_version_matches_target"])
            self.assertFalse((root / "stage1-receipt.json").exists())
            # Dry-run receipt carries no executed smoke values.
            self.assertIsNone(receipt["torch_smoke"]["device_name"])
            self.assertIsNone(receipt["pip_freeze_bounded"])
            # New receipt fields exist
            self.assertIn("dependency_install_argv", receipt)
            self.assertIn("local_rocm_install_argv", receipt)
            self.assertEqual(receipt["controlled_network_boundary"], CONTROLLED_NETWORK_BOUNDARY)

    def test_full_bootstrap_writes_passing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = self._bootstrap(root)
            self.assertTrue(receipt["validation_pass"])
            self.assertTrue(receipt["stage1_pass"])
            self.assertTrue(receipt["executed"])
            # All static validation checks pass
            self.assertTrue(receipt["checks"]["single_rocm_tool_present"])
            self.assertTrue(receipt["checks"]["single_gpu_visible"])
            self.assertTrue(receipt["checks"]["wheel_hashes_verified"])
            self.assertTrue(receipt["checks"]["install_command_offline"])
            self.assertTrue(receipt["checks"]["no_network_torch_install"])
            # All execution checks pass
            self.assertTrue(receipt["checks"]["venv_created"])
            self.assertTrue(receipt["checks"]["offline_rocm_wheel_stack_installed"])
            self.assertTrue(receipt["checks"]["torch_hip_smoke_passed"])
            self.assertTrue(receipt["checks"]["single_amd_device_visible_to_torch"])
            # Version checks pass (they belong to execution_checks and gate stage1_pass)
            self.assertTrue(receipt["checks"]["torch_version_matches_target"])
            self.assertTrue(receipt["checks"]["torchvision_version_matches_target"])
            self.assertTrue(receipt["checks"]["torchaudio_version_matches_target"])
            self.assertTrue(receipt["checks"]["triton_version_matches_target"])
            self.assertEqual(receipt["verified_wheels"][0]["key"], "torch")
            # HIP is non-empty
            self.assertIsNotNone(receipt["torch_smoke"]["hip_version"])
            self.assertNotEqual(receipt["torch_smoke"]["hip_version"], "")
            # Device count is 1
            self.assertEqual(receipt["torch_smoke"]["device_count"], 1)
            written = json.loads(
                (root / "stage1-receipt.json").read_text(encoding="utf-8")
            )
            self.assertTrue(written["validation_pass"])
            self.assertTrue(written["stage1_pass"])
            self.assertFalse(written["gpu"]["uuid_recorded"])
            # No GPU UUID value is ever recorded, only the boolean flag.
            self.assertNotIn("uuid", written["gpu"])
            # The canary freeze secret must be redacted, not leaked verbatim.
            rendered = json.dumps(written)
            self.assertNotIn("s3cr3tvalu3-canary", rendered)
            self.assertIn("<redacted>", written["pip_freeze_bounded"])
            # New receipt fields are present
            self.assertIn("dependency_install_argv", written)
            self.assertIn("local_rocm_install_argv", written)
            self.assertEqual(written["controlled_network_boundary"], CONTROLLED_NETWORK_BOUNDARY)

    def test_second_run_refuses_to_overwrite_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bootstrap(root)
            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(root)
            self.assertIn("refusing to overwrite", str(ctx.exception))

    def test_hash_mismatch_aborts_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Override the torch expected digest to a wrong value.
            bad = {"torch": "d" * 64}
            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(root, hash_overrides=bad)
            self.assertIn("sha256 mismatch", str(ctx.exception))
            self.assertFalse((root / "stage1-receipt.json").exists())

    def test_gpu_count_not_one_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(root, runner=_make_fake_runner(gpu_count=2))
            self.assertIn("exactly one visible GPU", str(ctx.exception))

    def test_no_rocm_tool_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(root, which=lambda _name: None)
            self.assertIn("no ROCm tool", str(ctx.exception))

    def test_install_failure_fails_closed_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(root, runner=_make_fake_runner(install_ok=False))
            self.assertIn("phase-2 offline ROCm wheel install failed", str(ctx.exception))
            self.assertFalse((root / "stage1-receipt.json").exists())

    def test_dependency_install_failure_fails_closed_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(root, runner=_make_fake_runner(dep_install_ok=False))
            self.assertIn("phase-1 dependency install failed", str(ctx.exception))
            self.assertFalse((root / "stage1-receipt.json").exists())

    def test_missing_triton_version_fails_stage1_with_execute_true(self) -> None:
        """Ensure missing triton_version causes execution check failure and prevents receipt writing.

        Version checks belong to execution_checks, so missing triton_version makes
        triton_version_matches_target=False, which fails stage1_pass even though
        validation_pass is True (static checks all pass).
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Create a runner that returns smoke with triton_version=None
            def runner_with_missing_triton(argv: Sequence[str]) -> "_FakeCompleted":
                joined = list(argv)
                if joined and str(joined[0]).endswith("rocminfo"):
                    return _FakeCompleted(0, stdout="Agent 1\n  Name: gfx1100")
                if "-c" in joined:
                    # Return smoke JSON with triton_version=None
                    smoke = json.dumps({
                        "torch_version": "2.9.1+rocm7.2.1",
                        "torchvision_version": "0.24.0+rocm7.2.1",
                        "torchaudio_version": "2.9.0+rocm7.2.1",
                        "triton_version": None,  # Missing triton
                        "hip_version": "6.4.42225",
                        "cuda_available": True,
                        "device_count": 1,
                        "device_name": "gfx1100",
                    })
                    return _FakeCompleted(0, stdout=smoke)
                if "freeze" in joined:
                    return _FakeCompleted(0, stdout="torch==2.9.1+rocm7.2.1\n")
                if "install" in joined:
                    return _FakeCompleted(0)
                return _FakeCompleted(0)

            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(root, runner=runner_with_missing_triton)
            # The error message should reflect that stage1_pass failed, not validation_pass
            self.assertIn("stage-1 verification did not pass", str(ctx.exception))
            self.assertFalse((root / "stage1-receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
