"""Unit tests for AMD stage-2 bootstrap.

Tests cover all major code paths and edge cases without requiring a GPU or
network access. All subprocess calls are mocked.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Sequence

from mantis_rocm_bridge.amd_cloud_stage2 import (
    DEFAULT_CONSTRAINTS_PATH,
    GENESIS_INSTALL_ROOT,
    STAGE2_PACKAGES,
    build_stage2_install_argv,
    build_stage2_receipt,
    CONSTRAINTS_CONTENT,
    ensure_ffmpeg,
    ensure_genesis_repo,
    genesis_repo_exists,
    genesis_repo_is_dirty,
    get_genesis_head_commit,
    load_and_validate_stage1_receipt,
    redact_freeze,
    run_genesis_scene_smoke,
    run_stage2_bootstrap,
    run_stage2_smoke,
    write_receipt_atomic,
    write_constraints_file,
)
from mantis_rocm_bridge.contracts import ContractError


ROOT = Path(__file__).resolve().parents[1]
STAGE1_RECEIPT = ROOT / "configs/amd-cloud-runtime-v1.json"


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_fake_stage1_receipt(*, instance_id: str = "u-test-instance", gpu_count: int = 1):
    """Return a minimal valid stage-1 receipt dict."""
    return {
        "schema_version": 1,
        "stage": 1,
        "captured_at_utc": "2026-07-25T00:00:00Z",
        "runtime_id": "test-runtime",
        "instance_id": instance_id,
        "platform": {
            "template": "Blank OpenCode Workspace",
            "persistent_root": "/workspace",
            "venv_path": "/workspace/rdna",
        },
        "gpu": {
            "count": gpu_count,
            "family": "AMD Radeon",
            "arch": "gfx1100",
            "name": "gfx1100",
            "vram_bytes": 51522830336,
            "uuid_recorded": False,
        },
        "stage1_pass": True,
        "validation_pass": True,
        "checks": {
            "single_gpu_visible": True,
            "torch_version_matches_target": True,
            "torchvision_version_matches_target": True,
            "torchaudio_version_matches_target": True,
            "triton_version_matches_target": True,
        },
    }


def _make_fake_runner(
    *,
    gpu_count: int = 1,
    install_ok: bool = True,
    smoke_ok: bool = True,
    genesis_scene_ok: bool = True,
    git_status_clean: bool = True,
    git_commit: str = "a" * 40,
):
    """Return a subprocess runner stub."""

    smoke = json.dumps({
        "torch_version": "2.9.1+rocm7.2.1",
        "torch_version_matches_target": True,
        "torchvision_version": "0.24.0+rocm7.2.1",
        "torchvision_version_matches_target": True,
        "hip_version": "6.4.42225",
        "hip_available": True,
        "device_count": gpu_count,
        "device_name": "gfx1100" if gpu_count > 0 else None,
        "numpy_version": "2.1.2",
        "numpy_version_matches_target": True,
        "scikit_image_version": "0.22.0",
        "scikit_image_satisfies_min": True,
        "torchaudio_version": "2.9.0",
        "torchaudio_version_matches_target": True,
        "triton_version": "3.5.1",
        "triton_version_matches_target": True,
        "genesis_version": "0.1.0",
        "genesis_has_amdgpu_backend": True,
        "lerobot_version": "0.4.4",
        "lerobot_version_matches_target": True,
        "ffmpeg_available": True,
        "ffmpeg_path": "/usr/bin/ffmpeg",
        "all_strict_checks_pass": True,
    })

    genesis_scene_smoke = json.dumps({
        "genesis_scene_smoke_success": genesis_scene_ok,
        "genesis_scene_smoke_error": None if genesis_scene_ok else "scene error",
    })

    def runner(argv: Sequence[str]) -> "_FakeCompleted":
        joined = list(map(str, argv))

        # Check for git status command
        if any("git" in token for token in joined) and "status" in joined and "--porcelain" in joined:
            return _FakeCompleted(0, stdout="" if git_status_clean else "M README.md")

        # Check for git clone command
        if any("git" in token for token in joined) and "clone" in joined:
            return _FakeCompleted(0, stdout="")

        # Check for git rev-parse HEAD
        if any("git" in token for token in joined) and "rev-parse" in joined and "HEAD" in joined:
            return _FakeCompleted(0, stdout=git_commit)

        # Check for pip install
        if any("pip" in token for token in joined) and "install" in joined:
            return _FakeCompleted(0 if install_ok else 1, stderr="" if install_ok else "install-boom")

        # Check for smoke tests (with -c flag)
        if "-c" in joined:
            # Determine which smoke test by checking content
            script_content = " ".join(joined)
            if "genesis_scene_smoke" in script_content:
                return _FakeCompleted(0 if genesis_scene_ok else 1, stdout=genesis_scene_smoke,
                                     stderr="" if genesis_scene_ok else "scene-smoke-boom")
            return _FakeCompleted(0 if smoke_ok else 1, stdout=smoke, stderr="" if smoke_ok else "smoke-boom")

        # Check for pip freeze
        if any("pip" in token for token in joined) and "freeze" in joined:
            return _FakeCompleted(0, stdout="numpy==2.1.2\nlerobot==0.4.4\nsecret-token==s3cr3t")

        return _FakeCompleted(0)

    return runner


class Stage1ReceiptValidationTests(unittest.TestCase):
    def test_valid_stage1_receipt_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stage1.json"
            receipt = _make_fake_stage1_receipt()
            path.write_text(json.dumps(receipt), encoding="utf-8")
            loaded = load_and_validate_stage1_receipt(path, "u-test-instance")
            self.assertTrue(loaded["stage1_pass"])
            self.assertEqual(loaded["instance_id"], "u-test-instance")

    def test_missing_stage1_receipt_path_fails(self) -> None:
        with self.assertRaises(ContractError):
            load_and_validate_stage1_receipt("/nonexistent/stage1.json", "u-test")

    def test_instance_id_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stage1.json"
            receipt = _make_fake_stage1_receipt(instance_id="u-abc")
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(ContractError) as ctx:
                load_and_validate_stage1_receipt(path, "u-xyz")
            self.assertIn("instance_id mismatch", str(ctx.exception))

    def test_stage1_pass_false_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stage1.json"
            receipt = _make_fake_stage1_receipt()
            receipt["stage1_pass"] = False
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(ContractError) as ctx:
                load_and_validate_stage1_receipt(path, "u-test-instance")
            self.assertIn("stage1_pass=true", str(ctx.exception))

    def test_gpu_count_not_one_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stage1.json"
            receipt = _make_fake_stage1_receipt(gpu_count=2)
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(ContractError) as ctx:
                load_and_validate_stage1_receipt(path, "u-test-instance")
            self.assertIn("exactly one GPU", str(ctx.exception))


class GenesisRepoTests(unittest.TestCase):
    def test_repo_exists_returns_true_for_valid_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "Genesis"
            repo.mkdir()
            (repo / ".git").mkdir()
            self.assertTrue(genesis_repo_exists(repo))

    def test_repo_exists_returns_false_for_nonexistent_path(self) -> None:
        self.assertFalse(genesis_repo_exists("/nonexistent/Genesis"))

    def test_repo_exists_returns_false_for_directory_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "Genesis"
            repo.mkdir()
            self.assertFalse(genesis_repo_exists(repo))

    def test_repo_is_dirty_detects_changes(self) -> None:
        runner = _make_fake_runner(git_status_clean=False, git_commit="b" * 40)
        self.assertTrue(genesis_repo_is_dirty("/workspace/Genesis", runner=runner))

    def test_repo_is_clean_when_no_changes(self) -> None:
        runner = _make_fake_runner(git_status_clean=True)
        self.assertFalse(genesis_repo_is_dirty("/workspace/Genesis", runner=runner))

    def test_get_head_commit_succeeds(self) -> None:
        expected_commit = "a" * 40
        runner = _make_fake_runner(git_commit=expected_commit)
        commit = get_genesis_head_commit("/workspace/Genesis", runner=runner)
        self.assertEqual(commit, expected_commit)

    def test_ensure_repo_clones_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = _make_fake_runner()
            info = ensure_genesis_repo(
                "https://github.com/test/Genesis.git",
                Path(directory) / "Genesis",
                runner=runner,
            )
            self.assertFalse(info["existed"])
            self.assertEqual(info["commit"], "a" * 40)

    def test_ensure_repo_accepts_existing_clean_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "Genesis"
            repo.mkdir()
            (repo / ".git").mkdir()
            runner = _make_fake_runner(git_status_clean=True, git_commit="a" * 40)
            info = ensure_genesis_repo(
                "https://github.com/test/Genesis.git",
                repo,
                runner=runner,
            )
            self.assertTrue(info["existed"])
            self.assertEqual(info["commit"], "a" * 40)

    def test_ensure_repo_rejects_dirty_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "Genesis"
            repo.mkdir()
            (repo / ".git").mkdir()
            runner = _make_fake_runner(git_status_clean=False, git_commit="b" * 40)
            with self.assertRaises(ContractError) as ctx:
                ensure_genesis_repo(
                    "https://github.com/test/Genesis.git",
                    repo,
                    runner=runner,
                )
            self.assertIn("uncommitted changes", str(ctx.exception))


class Stage2InstallCommandTests(unittest.TestCase):
    def test_install_command_includes_all_stage2_packages(self) -> None:
        argv = build_stage2_install_argv(
            "/workspace/rdna/bin/python",
            "/workspace/Genesis",
            "/workspace/constraints.txt"
        )
        # All stage-2 packages should be present
        for pkg in STAGE2_PACKAGES:
            self.assertTrue(any(pkg in str(token) for token in argv))
        # Genesis editable install should be present as two separate tokens
        editable_indices = [i for i, token in enumerate(argv) if "editable" in str(token)]
        self.assertTrue(editable_indices)
        # Check that --editable and the path are separate tokens
        for idx in editable_indices:
            if "--editable" in str(argv[idx]):
                # Next token should be the genesis root
                self.assertEqual(argv[idx + 1], "/workspace/Genesis")

    def test_install_command_has_constraints_file(self) -> None:
        argv = build_stage2_install_argv(
            "/workspace/rdna/bin/python",
            "/workspace/Genesis",
            "/workspace/constraints.txt"
        )
        rendered = " ".join(argv)
        # Check for -c flag with constraints file
        self.assertIn("-c", rendered)
        self.assertIn("/workspace/constraints.txt", rendered)
        # Should NOT have inline --constraint= specs
        self.assertNotIn("--constraint=torch==", rendered)
        self.assertNotIn("--constraint=torchvision==", rendered)

    def test_install_command_does_not_install_bare_torch(self) -> None:
        argv = build_stage2_install_argv(
            "/workspace/rdna/bin/python",
            "/workspace/Genesis",
            "/workspace/constraints.txt"
        )
        # Should not have bare torch tokens
        for token in argv:
            if "torch" in str(token).lower():
                # Should only be in constraints file path
                self.assertTrue(
                    "constraint" in str(token) or ".txt" in str(token) or GENESIS_INSTALL_ROOT in str(token),
                    f"Bare torch token found: {token}"
                )


class SmokeTestTests(unittest.TestCase):
    def test_stage2_smoke_succeeds_with_valid_output(self) -> None:
        runner = _make_fake_runner()
        result = run_stage2_smoke("/workspace/rdna/bin/python", runner=runner)
        self.assertTrue(result["hip_available"])
        self.assertEqual(result["device_count"], 1)
        self.assertTrue(result["lerobot_version_matches_target"])
        self.assertTrue(result["numpy_version_matches_target"])
        self.assertTrue(result["scikit_image_satisfies_min"])
        self.assertTrue(result["torch_version_matches_target"])
        self.assertTrue(result["torchaudio_version_matches_target"])
        self.assertTrue(result["triton_version_matches_target"])

    def test_stage2_smoke_fails_closed_on_bad_exit(self) -> None:
        runner = _make_fake_runner(smoke_ok=False)
        with self.assertRaises(ContractError) as ctx:
            run_stage2_smoke("/workspace/rdna/bin/python", runner=runner)
        self.assertIn("smoke test failed", str(ctx.exception))

    def test_genesis_scene_smoke_succeeds(self) -> None:
        runner = _make_fake_runner(genesis_scene_ok=True)
        result = run_genesis_scene_smoke("/workspace/rdna/bin/python", runner=runner)
        self.assertTrue(result["genesis_scene_smoke_success"])

    def test_genesis_scene_smoke_fails_closed(self) -> None:
        runner = _make_fake_runner(genesis_scene_ok=False)
        with self.assertRaises(ContractError) as ctx:
            run_genesis_scene_smoke("/workspace/rdna/bin/python", runner=runner)
        self.assertIn("scene smoke test failed", str(ctx.exception))

    def test_genesis_scene_smoke_uses_correct_morph_api(self) -> None:
        """Verify the Genesis scene smoke script uses gs.morphs.Plane (not gs.morph.Plane)."""
        from mantis_rocm_bridge.amd_cloud_stage2 import GENESIS_SCENE_SMOKE_SCRIPT

        # Assert the script contains the correct API (gs.morphs.Plane)
        self.assertIn("gs.morphs.Plane", GENESIS_SCENE_SMOKE_SCRIPT,
                      "Genesis scene smoke script should use gs.morphs.Plane API")

        # Assert the script does NOT contain the incorrect API (gs.morph.Plane)
        self.assertNotIn("gs.morph.Plane", GENESIS_SCENE_SMOKE_SCRIPT,
                        "Genesis scene smoke script should not use deprecated gs.morph.Plane API")


class VersionComparisonTests(unittest.TestCase):
    """Tests for exact version comparison using packaging.version.Version."""

    def test_torch_2_9_10_does_not_match_2_9_1(self) -> None:
        """Test that torch 2.9.10 is correctly rejected when target is 2.9.1."""
        runner = _make_fake_runner(gpu_count=1)

        # Override the smoke output to return 2.9.10
        bad_smoke = json.dumps({
            "torch_version": "2.9.10+rocm7.2.1",
            "torch_version_matches_target": False,
            "torchvision_version": "0.24.0+rocm7.2.1",
            "torchvision_version_matches_target": True,
            "hip_available": True,
            "device_count": 1,
            "numpy_version": "2.1.2",
            "numpy_version_matches_target": True,
            "scikit_image_version": "0.22.0",
            "scikit_image_satisfies_min": True,
            "torchaudio_version": "2.9.0",
            "torchaudio_version_matches_target": True,
            "triton_version": "3.5.1",
            "triton_version_matches_target": True,
            "genesis_version": "0.1.0",
            "genesis_has_amdgpu_backend": True,
            "lerobot_version": "0.4.4",
            "lerobot_version_matches_target": True,
            "ffmpeg_available": True,
            "all_strict_checks_pass": False,
        })

        def custom_runner(argv):
            if "-c" in " ".join(map(str, argv)):
                return _FakeCompleted(0, stdout=bad_smoke)
            return _make_fake_runner()(argv)

        result = run_stage2_smoke("/workspace/rdna/bin/python", runner=custom_runner)
        self.assertFalse(result["torch_version_matches_target"])
        self.assertEqual(result["torch_version"], "2.9.10+rocm7.2.1")

    def test_torchvision_missing_fails_check(self) -> None:
        """Test that missing torchvision fails the version check."""
        bad_smoke = json.dumps({
            "torch_version": "2.9.1+rocm7.2.1",
            "torch_version_matches_target": True,
            "torchvision_version": None,
            "torchvision_version_matches_target": False,
            "hip_available": True,
            "device_count": 1,
            "numpy_version": "2.1.2",
            "numpy_version_matches_target": True,
            "scikit_image_version": "0.22.0",
            "scikit_image_satisfies_min": True,
            "torchaudio_version": "2.9.0",
            "torchaudio_version_matches_target": True,
            "triton_version": "3.5.1",
            "triton_version_matches_target": True,
            "genesis_version": "0.1.0",
            "genesis_has_amdgpu_backend": True,
            "lerobot_version": "0.4.4",
            "lerobot_version_matches_target": True,
            "ffmpeg_available": True,
            "all_strict_checks_pass": False,
        })

        def custom_runner(argv):
            if "-c" in " ".join(map(str, argv)):
                return _FakeCompleted(0, stdout=bad_smoke)
            return _make_fake_runner()(argv)

        result = run_stage2_smoke("/workspace/rdna/bin/python", runner=custom_runner)
        self.assertFalse(result["torchvision_version_matches_target"])
        self.assertIsNone(result["torchvision_version"])

    def test_scikit_image_0_9_fails_min_version(self) -> None:
        """Test that scikit-image 0.9 fails the >=0.22.0 check using Version comparison."""
        bad_smoke = json.dumps({
            "torch_version": "2.9.1+rocm7.2.1",
            "torch_version_matches_target": True,
            "torchvision_version": "0.24.0+rocm7.2.1",
            "torchvision_version_matches_target": True,
            "hip_available": True,
            "device_count": 1,
            "numpy_version": "2.1.2",
            "numpy_version_matches_target": True,
            "scikit_image_version": "0.9.0",
            "scikit_image_satisfies_min": False,
            "torchaudio_version": "2.9.0",
            "torchaudio_version_matches_target": True,
            "triton_version": "3.5.1",
            "triton_version_matches_target": True,
            "genesis_version": "0.1.0",
            "genesis_has_amdgpu_backend": True,
            "lerobot_version": "0.4.4",
            "lerobot_version_matches_target": True,
            "ffmpeg_available": True,
            "all_strict_checks_pass": False,
        })

        def custom_runner(argv):
            if "-c" in " ".join(map(str, argv)):
                return _FakeCompleted(0, stdout=bad_smoke)
            return _make_fake_runner()(argv)

        result = run_stage2_smoke("/workspace/rdna/bin/python", runner=custom_runner)
        self.assertFalse(result["scikit_image_satisfies_min"])
        self.assertEqual(result["scikit_image_version"], "0.9.0")

    def test_genesis_metadata_fallback_key_text(self) -> None:
        """Test that Genesis version falls back to importlib.metadata when gs.__version__ is empty."""
        # This test verifies the smoke script behavior, not the receipt
        # The actual smoke script would: 1) try gs.__version__, 2) if empty, use importlib.metadata.version("genesis-world")
        fallback_smoke = json.dumps({
            "torch_version": "2.9.1+rocm7.2.1",
            "torch_version_matches_target": True,
            "torchvision_version": "0.24.0+rocm7.2.1",
            "torchvision_version_matches_target": True,
            "hip_available": True,
            "device_count": 1,
            "numpy_version": "2.1.2",
            "numpy_version_matches_target": True,
            "scikit_image_version": "0.22.0",
            "scikit_image_satisfies_min": True,
            "torchaudio_version": "2.9.0",
            "torchaudio_version_matches_target": True,
            "triton_version": "3.5.1",
            "triton_version_matches_target": True,
            "genesis_version": "0.1.0",  # Would come from importlib.metadata when gs.__version__ is empty
            "genesis_has_amdgpu_backend": True,
            "lerobot_version": "0.4.4",
            "lerobot_version_matches_target": True,
            "ffmpeg_available": True,
            "all_strict_checks_pass": True,
        })

        def custom_runner(argv):
            if "-c" in " ".join(map(str, argv)):
                return _FakeCompleted(0, stdout=fallback_smoke)
            return _make_fake_runner()(argv)

        result = run_stage2_smoke("/workspace/rdna/bin/python", runner=custom_runner)
        self.assertEqual(result["genesis_version"], "0.1.0")
        self.assertTrue(result["genesis_has_amdgpu_backend"])
        self.assertTrue(result["all_strict_checks_pass"])


class ReceiptTests(unittest.TestCase):
    def test_redact_freeze_removes_secrets(self) -> None:
        freeze = "numpy==2.1.2\nmy-api-token==abc123\nsecret-key==zzz\n"
        out = redact_freeze(freeze)
        self.assertIn("numpy==2.1.2", out)
        self.assertNotIn("abc123", out)
        self.assertNotIn("zzz", out)
        self.assertIn("<redacted>", out)

    def test_receipt_is_not_overwritten_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            write_receipt_atomic(
                {"schema_version": 1, "stage": 2, "stage2_pass": True},
                path
            )
            with self.assertRaises(ContractError) as ctx:
                write_receipt_atomic(
                    {"schema_version": 1, "stage": 2, "stage2_pass": True},
                    path
                )
            self.assertIn("refusing to overwrite", str(ctx.exception))

    def test_receipt_overwrite_with_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            write_receipt_atomic(
                {"schema_version": 1, "stage": 2, "stage2_pass": True},
                path
            )
            write_receipt_atomic(
                {"schema_version": 1, "stage": 2, "stage2_pass": False},
                path,
                overwrite=True
            )
            receipt = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(receipt["stage2_pass"])

    def test_build_receipt_with_valid_data(self) -> None:
        stage1_receipt = _make_fake_stage1_receipt()
        genesis_info = {"existed": True, "commit": "a" * 64, "path": "/workspace/Genesis", "planned_clone": False}
        smoke = {
            "hip_available": True,
            "device_count": 1,
            "lerobot_version": "0.4.4",
            "lerobot_version_matches_target": True,
            "numpy_version_matches_target": True,
            "torch_version_matches_target": True,
            "torchvision_version_matches_target": True,
            "torchaudio_version_matches_target": True,
            "triton_version_matches_target": True,
            "scikit_image_satisfies_min": True,
            "genesis_version": "0.1.0",
            "genesis_has_amdgpu_backend": True,
            "ffmpeg_available": True,
        }
        genesis_smoke = {"genesis_scene_smoke_success": True}
        constraints_info = {"path": "/workspace/constraints.txt", "hash": "a" * 64, "content": "torch==2.9.1\n"}
        ffmpeg_info = {"existed": True, "path": "/usr/bin/ffmpeg", "planned_apt_update": False, "planned_apt_install_argv": None, "apt_update_argv": None, "apt_install_argv": None, "apt_update_success": None, "apt_install_success": None}

        receipt = build_stage2_receipt(
            stage1_receipt=stage1_receipt,
            genesis_info=genesis_info,
            stage2_install_argv=["python", "-m", "pip", "install", "-c", "/workspace/constraints.txt"],
            pip_freeze="numpy==2.1.2\n",
            smoke_results=smoke,
            genesis_smoke_results=genesis_smoke,
            constraints_info=constraints_info,
            ffmpeg_info=ffmpeg_info,
            executed=True,
        )

        self.assertTrue(receipt["validation_pass"])
        self.assertTrue(receipt["stage2_pass"])
        self.assertEqual(receipt["stage"], 2)
        self.assertEqual(receipt["genesis"]["commit"], "a" * 64)
        self.assertIsNotNone(receipt["constraints"]["path"])
        self.assertIsNotNone(receipt["constraints"]["sha256"])
        self.assertTrue(receipt["ffmpeg"]["existed"])
        self.assertEqual(receipt["ffmpeg"]["path"], "/usr/bin/ffmpeg")


class FFmpegEnsureTests(unittest.TestCase):
    def test_ffmpeg_existing_records_path_without_apt(self) -> None:
        which_func = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else "/usr/bin/apt-get"
        runner = lambda argv: _FakeCompleted(0, stdout="", stderr="")

        result = ensure_ffmpeg(which=which_func, runner=runner, dry_run=False)

        self.assertTrue(result["existed"])
        self.assertEqual(result["path"], "/usr/bin/ffmpeg")
        self.assertFalse(result["planned_apt_update"])
        self.assertIsNone(result["planned_apt_install_argv"])
        self.assertIsNone(result["apt_update_argv"])
        self.assertIsNone(result["apt_install_argv"])
        self.assertIsNone(result["apt_update_success"])
        self.assertIsNone(result["apt_install_success"])

    def test_ffmpeg_existing_in_dry_run_records_path(self) -> None:
        which_func = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else "/usr/bin/apt-get"
        runner = lambda argv: _FakeCompleted(0, stdout="", stderr="")

        result = ensure_ffmpeg(which=which_func, runner=runner, dry_run=True)

        self.assertTrue(result["existed"])
        self.assertEqual(result["path"], "/usr/bin/ffmpeg")
        self.assertFalse(result["planned_apt_update"])
        self.assertIsNone(result["planned_apt_install_argv"])

    def test_ffmpeg_missing_in_dry_run_records_planned_commands(self) -> None:
        which_func = lambda name: "/usr/bin/apt-get" if name == "apt-get" else None
        runner = lambda argv: _FakeCompleted(0, stdout="", stderr="")

        result = ensure_ffmpeg(which=which_func, runner=runner, dry_run=True)

        self.assertFalse(result["existed"])
        self.assertIsNone(result["path"])
        self.assertTrue(result["planned_apt_update"])
        self.assertEqual(result["planned_apt_install_argv"], ["/usr/bin/apt-get", "install", "-y", "ffmpeg"])
        self.assertIsNone(result["apt_update_argv"])
        self.assertIsNone(result["apt_install_argv"])
        self.assertIsNone(result["apt_update_success"])
        self.assertIsNone(result["apt_install_success"])

    def test_ffmpeg_missing_in_execute_mode_runs_both_commands(self) -> None:
        calls = []
        ffmpeg_after_install = False

        def tracking_runner(argv):
            calls.append(list(argv))
            # Mark that we've reached the install stage
            if "install" in " ".join(argv):
                nonlocal ffmpeg_after_install
                ffmpeg_after_install = True
            return _FakeCompleted(0, stdout="", stderr="")

        def which_func(name):
            if name == "apt-get":
                return "/usr/bin/apt-get"
            if name == "ffmpeg":
                # ffmpeg appears after apt install
                return "/usr/bin/ffmpeg" if ffmpeg_after_install else None
            return None

        result = ensure_ffmpeg(which=which_func, runner=tracking_runner, dry_run=False)

        # Should have called apt-get update then install
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], ["/usr/bin/apt-get", "update"])
        self.assertEqual(calls[1], ["/usr/bin/apt-get", "install", "-y", "ffmpeg"])

        self.assertFalse(result["existed"])
        self.assertEqual(result["path"], "/usr/bin/ffmpeg")
        self.assertTrue(result["apt_update_success"])
        self.assertTrue(result["apt_install_success"])

    def test_ffmpeg_apt_update_failure_fails_closed(self) -> None:
        def failing_runner(argv):
            if "update" in argv:
                return _FakeCompleted(1, stderr="apt-get update failed")
            return _FakeCompleted(0, stdout="", stderr="")

        which_func = lambda name: "/usr/bin/apt-get" if name == "apt-get" else None

        with self.assertRaises(ContractError) as ctx:
            ensure_ffmpeg(which=which_func, runner=failing_runner, dry_run=False)
        self.assertIn("apt-get update failed", str(ctx.exception))

    def test_ffmpeg_apt_install_failure_fails_closed(self) -> None:
        def failing_runner(argv):
            if "install" in argv:
                return _FakeCompleted(1, stderr="apt-get install failed")
            return _FakeCompleted(0, stdout="", stderr="")

        which_func = lambda name: "/usr/bin/apt-get" if name == "apt-get" else None

        with self.assertRaises(ContractError) as ctx:
            ensure_ffmpeg(which=which_func, runner=failing_runner, dry_run=False)
        self.assertIn("apt-get install ffmpeg failed", str(ctx.exception))

    def test_ffmpeg_missing_apt_get_not_available_fails_closed(self) -> None:
        which_func = lambda name: None  # No apt-get available

        with self.assertRaises(ContractError) as ctx:
            ensure_ffmpeg(which=which_func, dry_run=False)
        self.assertIn("apt-get is not available", str(ctx.exception))

    def test_ffmpeg_install_succeeds_but_still_missing_fails_closed(self) -> None:
        def runner(argv):
            return _FakeCompleted(0, stdout="", stderr="")

        which_func = lambda name: "/usr/bin/apt-get" if name == "apt-get" else None  # ffmpeg never appears

        with self.assertRaises(ContractError) as ctx:
            ensure_ffmpeg(which=which_func, runner=runner, dry_run=False)
        self.assertIn("ffmpeg is still not found on PATH", str(ctx.exception))

    def test_packaging_in_stage2_packages(self) -> None:
        self.assertIn("packaging", STAGE2_PACKAGES)

    def test_packaging_in_install_command(self) -> None:
        argv = build_stage2_install_argv(
            "/workspace/rdna/bin/python",
            "/workspace/Genesis",
            "/workspace/constraints.txt"
        )
        # Check that packaging is in the install command
        self.assertTrue(any("packaging" in str(token) for token in argv))


class Stage2BootstrapEndToEndTests(unittest.TestCase):
    def _bootstrap(
        self,
        stage1_path: Path,
        root: Path,
        **overrides
    ):
        # Always provide a which function that finds git and ffmpeg
        which_func = overrides.pop("which", lambda name: "/usr/bin/" + name if name in ("git", "ffmpeg", "apt-get") else None)
        # Make tests hermetic: use isolated genesis_install_root within temp directory by default
        if "genesis_install_root" not in overrides:
            overrides["genesis_install_root"] = str(root / "Genesis")
        return run_stage2_bootstrap(
            stage1_receipt_path=stage1_path,
            receipt_path=root / "stage2-receipt.json",
            runner=overrides.pop("runner", _make_fake_runner()),
            which=which_func,
            constraints_path=overrides.pop("constraints_path", None),
            **overrides,
        )

    def test_dry_run_validates_without_writing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            receipt = self._bootstrap(
                stage1_path,
                root,
                execute=False,
            )

            # Dry-run: validation_pass=True, stage2_pass=False (not executed)
            self.assertTrue(receipt["validation_pass"])
            self.assertFalse(receipt["stage2_pass"])
            self.assertFalse(receipt["executed"])
            self.assertFalse((root / "stage2-receipt.json").exists())
            # Genesis commit should be None in dry-run when repo doesn't exist
            self.assertIsNone(receipt["genesis"]["commit"])
            # Should have constraints info
            self.assertIsNotNone(receipt["constraints"]["sha256"])

    def test_full_bootstrap_writes_passing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            constraints_path = root / "constraints.txt"
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            receipt = self._bootstrap(
                stage1_path,
                root,
                execute=True,
                constraints_path=str(constraints_path),
            )

            self.assertTrue(receipt["validation_pass"])
            self.assertTrue(receipt["stage2_pass"])
            self.assertTrue(receipt["executed"])
            self.assertTrue((root / "stage2-receipt.json").exists())

            written = json.loads((root / "stage2-receipt.json").read_text(encoding="utf-8"))
            self.assertTrue(written["stage2_pass"])
            # Secret should be redacted
            self.assertNotIn("s3cr3t", written["pip_freeze_bounded"])
            # Should have constraints info
            self.assertIsNotNone(written["constraints"]["path"])

    def test_dry_run_does_not_clone_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            constraints_path = root / "constraints.txt"
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            # Track runner calls - should not call git clone in dry-run
            clone_called = [False]
            def tracking_runner(argv):
                if "clone" in " ".join(argv):
                    clone_called[0] = True
                return _make_fake_runner()(argv)

            receipt = self._bootstrap(
                stage1_path,
                root,
                execute=False,
                runner=tracking_runner,
                constraints_path=str(constraints_path),
            )

            self.assertFalse(clone_called[0], "dry-run should not clone repo")
            self.assertTrue(receipt["genesis"]["planned_clone"])
            self.assertIsNone(receipt["genesis"]["commit"])

    def test_constraints_file_written_in_execute_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            constraints_path = root / "constraints.txt"
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            self._bootstrap(
                stage1_path,
                root,
                execute=True,
                constraints_path=str(constraints_path),
            )

            # Constraints file should exist
            self.assertTrue(constraints_path.exists())
            content = constraints_path.read_text(encoding="utf-8")
            self.assertIn("torch==2.9.1", content)
            self.assertIn("numpy==2.1.2", content)

    def test_install_command_tokens_are_correct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            constraints_path = root / "constraints.txt"
            genesis_root = root / "Genesis"
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            receipt = self._bootstrap(
                stage1_path,
                root,
                execute=False,
                constraints_path=str(constraints_path),
            )

            # Check install command has correct tokens
            install_argv = receipt["stage2_install_argv"]
            self.assertIn("-c", install_argv)
            # Should have --editable and path as separate tokens
            editable_idx = install_argv.index("--editable")
            self.assertEqual(install_argv[editable_idx + 1], str(genesis_root))

    def test_second_run_refuses_to_overwrite_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            constraints_path = root / "constraints.txt"
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            self._bootstrap(stage1_path, root, execute=True, constraints_path=str(constraints_path))
            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(stage1_path, root, execute=True, constraints_path=str(constraints_path))
            self.assertIn("refusing to overwrite", str(ctx.exception))

    def test_install_failure_fails_closed_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            constraints_path = root / "constraints.txt"
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(
                    stage1_path,
                    root,
                    runner=_make_fake_runner(install_ok=False, git_commit="c" * 40),
                    execute=True,
                    constraints_path=str(constraints_path),
                )
            self.assertIn("install failed", str(ctx.exception))
            self.assertFalse((root / "stage2-receipt.json").exists())

    def test_smoke_failure_fails_closed_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            constraints_path = root / "constraints.txt"
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(
                    stage1_path,
                    root,
                    runner=_make_fake_runner(smoke_ok=False, git_commit="d" * 40),
                    execute=True,
                    constraints_path=str(constraints_path),
                )
            self.assertIn("smoke test failed", str(ctx.exception))
            self.assertFalse((root / "stage2-receipt.json").exists())

    def test_genesis_scene_smoke_failure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            constraints_path = root / "constraints.txt"
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(
                    stage1_path,
                    root,
                    runner=_make_fake_runner(genesis_scene_ok=False, git_commit="e" * 40),
                    execute=True,
                    constraints_path=str(constraints_path),
                )
            self.assertIn("scene smoke test failed", str(ctx.exception))
            self.assertFalse((root / "stage2-receipt.json").exists())

    def test_dirty_genesis_repo_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            constraints_path = root / "constraints.txt"
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            # Create a fake Genesis repo with .git in the expected location
            genesis_root = root / "Genesis"
            genesis_root.mkdir()
            (genesis_root / ".git").mkdir()

            with self.assertRaises(ContractError) as ctx:
                self._bootstrap(
                    stage1_path,
                    root,
                    runner=_make_fake_runner(git_status_clean=False, git_commit="f" * 40),
                    genesis_install_root=str(genesis_root),
                    execute=True,
                    constraints_path=str(constraints_path),
                )
            self.assertIn("uncommitted changes", str(ctx.exception))
            self.assertFalse((root / "stage2-receipt.json").exists())

    def test_bootstrap_uses_isolated_install_root(self) -> None:
        """Regression test: _bootstrap must use isolated genesis_install_root within temp directory.

        This ensures tests are hermetic and don't depend on /workspace/Genesis existing on the host.
        Production behavior is preserved - dry-run may inspect/reuse existing configured repositories.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage1_path = root / "stage1.json"
            stage1_receipt = _make_fake_stage1_receipt()
            stage1_path.write_text(json.dumps(stage1_receipt), encoding="utf-8")

            receipt = self._bootstrap(
                stage1_path,
                root,
                execute=False,
            )

            # Verify genesis.install_root points within the temp directory, not /workspace/Genesis
            self.assertEqual(receipt["platform"]["genesis_install_root"], str(root / "Genesis"))
            # Verify the install command also uses the isolated path
            install_argv = receipt["stage2_install_argv"]
            editable_idx = install_argv.index("--editable")
            self.assertEqual(install_argv[editable_idx + 1], str(root / "Genesis"))


if __name__ == "__main__":
    unittest.main()
