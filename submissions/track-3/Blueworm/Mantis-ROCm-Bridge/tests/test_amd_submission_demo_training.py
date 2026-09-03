from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/run_amd_submission_demo_training.sh"
CONTRACT = ROOT / "configs/act-rocm-submission-demo-training-10k-diagnostic-v2.json"
PREDECESSOR_CONTRACT = (
    ROOT / "configs/act-rocm-submission-demo-training-10k-diagnostic-v1.json"
)


class AmdSubmissionDemoTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def _embedded_python(self, output_name: str) -> str:
        pattern = re.compile(
            rf'> "\$\{{evidence_root\}}/{re.escape(output_name)}" <<\'PY\'\n(.*?)\nPY',
            flags=re.DOTALL,
        )
        match = pattern.search(self.source)
        self.assertIsNotNone(match, f"missing embedded Python for {output_name}")
        return match.group(1)

    def _function_embedded_python(self, function_name: str) -> str:
        pattern = re.compile(
            rf"{re.escape(function_name)}\(\) \{{.*?<<'PY'\n(.*?)\nPY\n\}}",
            flags=re.DOTALL,
        )
        match = pattern.search(self.source)
        self.assertIsNotNone(match, f"missing embedded Python in {function_name}")
        return match.group(1)

    def test_default_is_verify_only_and_run_is_explicit(self) -> None:
        self.assertIn("mode=${1:-verify-only}", self.source)
        self.assertIn('"${mode}" != "verify-only"', self.source)
        self.assertIn('"${mode}" != "run"', self.source)
        self.assertIn("VERIFY_ONLY_COMPLETE_NO_TRAINING", self.source)
        self.assertIn("training_invocations.txt", self.source)

    def test_contract_and_source_hashes_are_pinned(self) -> None:
        self.assertIn(
            "EXPECTED_CONTRACT_SHA256=158be58ad9c2dc94509c028ac992a709c74457144c02ee66908c1dbb7bf523fb",
            self.source,
        )
        self.assertIn("EXPECTED_SUPERVISOR_SHA256", self.source)
        self.assertIn("EXPECTED_LIVE_INFER_SHA256", self.source)
        self.assertIn("source_and_contracts.SHA256SUMS", self.source)
        for dependency in (
            "check_amd_persistence.py",
            "capture_act_checkpoint_receipt.py",
            "extract_lerobot_train_metrics.py",
            "amd_persistence.py",
            "camera_mounts.py",
            "contracts.py",
            "genesis_smoke.py",
            "gripper.py",
            "stack_bowls_env.py",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, self.source)

    def test_fresh_durable_mount_and_persistence_gates_are_required(self) -> None:
        self.assertIn("/workspace/persistent/mantis-track3/", self.source)
        self.assertIn("readlink -f /workspace/persistent", self.source)
        self.assertIn("/persistent", self.source)
        self.assertIn("check_amd_persistence.py", self.source)
        self.assertIn("refusing existing training root", self.source)
        self.assertIn("refusing existing evidence root", self.source)
        self.assertIn('[[ ! -f "${executable}" || ! -x "${executable}" ]]', self.source)
        self.assertIn('[[ ! -d "${dataset_root}" || -L "${dataset_root}" ]]', self.source)

    def test_durable_root_boundary_accepts_base_only_for_persistent_root(self) -> None:
        pattern = re.compile(
            r"^is_strict_descendant\(\) \{.*?^\}",
            flags=re.DOTALL | re.MULTILINE,
        )
        match = pattern.search(self.source)
        self.assertIsNotNone(match, "missing is_strict_descendant")
        function = match.group(0)
        completed = subprocess.run(
            [
                "bash",
                "-c",
                f"""{function}
root=/workspace/persistent/mantis-track3
is_strict_descendant "$root" "$root/child"
is_strict_descendant "$root" "$root/nested/child"
! is_strict_descendant "$root" "$root"
! is_strict_descendant "$root" "$root/"
! is_strict_descendant "$root" "${{root}}-sibling/child"
! is_strict_descendant "$root" "$root/../escape"
! is_strict_descendant "$root" "relative/path"
""",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            '[[ "${persistent_root}" != "${durable_root}" ]]', self.source
        )
        self.assertNotIn(
            'for path in "${persistent_root}" "${dataset_root}"', self.source
        )

    def test_executable_identity_accepts_venv_symlink_and_rejects_drift(self) -> None:
        embedded = self._embedded_python("executable_identity.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            venv = root / "venv"
            other_venv = root / "other-venv"
            for path in (venv, other_venv):
                subprocess.run(
                    [sys.executable, "-m", "venv", "--without-pip", str(path)],
                    check=True,
                )
            python_bin = venv / "bin/python"
            train_bin = venv / "bin/lerobot-train"
            train_bin.write_text(
                f"#!{python_bin}\nraise SystemExit('fixture only')\n",
                encoding="utf-8",
            )
            train_bin.chmod(0o755)

            def run_identity() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [str(python_bin), "-", str(python_bin), str(train_bin)],
                    input=embedded,
                    text=True,
                    capture_output=True,
                    check=False,
                )

            accepted = run_identity()
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            result = json.loads(accepted.stdout)
            self.assertTrue(result["pass"])
            self.assertEqual(
                Path(result["observed"]["sys_prefix"]).resolve(), venv.resolve()
            )

            train_bin.chmod(0o644)
            non_executable = run_identity()
            self.assertEqual(non_executable.returncode, 2, non_executable.stderr)
            self.assertFalse(json.loads(non_executable.stdout)["pass"])

            train_bin.chmod(0o755)
            train_bin.write_text(
                f"#!{other_venv / 'bin/python'}\nraise SystemExit('fixture only')\n",
                encoding="utf-8",
            )
            wrong_venv = run_identity()
            self.assertEqual(wrong_venv.returncode, 2, wrong_venv.stderr)
            wrong_result = json.loads(wrong_venv.stdout)
            self.assertFalse(wrong_result["checks"]["train_shebang_same_venv_bin"])

    def test_runtime_dataset_and_gpu_identity_fail_closed(self) -> None:
        for marker in (
            "total_episodes",
            "total_frames",
            "observation.state",
            "torch.version.hip",
            "genesis_revision",
            "GPU use \\(%\\): 0",
            "GPU Memory Allocated \\(VRAM%\\): 0",
            "kfd_owners_${phase}.json",
            '"device": "/dev/kfd"',
            '"scan_complete": not scan_errors',
            "matching_processes_${phase}.txt",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)
        self.assertEqual(
            set(self.contract["dataset"]["camera_shapes_hwc"]),
            {
                "observation.images.env_cam",
                "observation.images.left_wrist_cam",
                "observation.images.right_wrist_cam",
            },
        )
        self.assertIn('expected["camera_shapes_hwc"].items()', self.source)
        self.assertIn('"repo_id_field_present"', self.source)
        self.assertIn('"repo_id_policy_supported"', self.source)
        self.assertIn('"local_v3_missing"', self.source)
        self.assertNotIn('"local_v3_null"', self.source)
        self.assertIn("dataset_payload.SHA256SUMS", self.source)
        self.assertIn("dataset_payload.verify.log", self.source)
        self.assertNotIn("/sys/kernel/debug/kfd/proc", self.source)

    def test_kfd_owner_audit_uses_proc_fds_and_fails_closed(self) -> None:
        embedded = self._function_embedded_python("capture_kfd_owners")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root = root / "proc"
            owner = proc_root / "101"
            idle = proc_root / "202"
            (owner / "fd").mkdir(parents=True)
            (idle / "fd").mkdir(parents=True)
            (owner / "comm").write_text("trainer\n", encoding="utf-8")
            os.symlink("/dev/kfd", owner / "fd/3")

            def run_audit(
                selected_root: Path, name: str
            ) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        sys.executable,
                        "-",
                        str(selected_root),
                        str(root / f"{name}.json"),
                        str(root / f"{name}.txt"),
                    ],
                    input=embedded,
                    text=True,
                    capture_output=True,
                    check=False,
                )

            busy = run_audit(proc_root, "busy")
            self.assertEqual(busy.returncode, 0, busy.stderr)
            busy_result = json.loads((root / "busy.json").read_text())
            self.assertTrue(busy_result["scan_complete"])
            self.assertEqual(busy_result["owner_count"], 1)
            self.assertEqual(busy_result["owners"][0]["pid"], 101)
            self.assertEqual((root / "busy.txt").read_text(), "1\n")

            (owner / "fd/3").unlink()
            idle_result = run_audit(proc_root, "idle")
            self.assertEqual(idle_result.returncode, 0, idle_result.stderr)
            idle_receipt = json.loads((root / "idle.json").read_text())
            self.assertTrue(idle_receipt["scan_complete"])
            self.assertEqual(idle_receipt["owner_count"], 0)
            self.assertEqual((root / "idle.txt").read_text(), "0\n")

            invalid = run_audit(root / "missing-proc", "invalid")
            self.assertEqual(invalid.returncode, 2, invalid.stderr)
            invalid_receipt = json.loads((root / "invalid.json").read_text())
            self.assertFalse(invalid_receipt["scan_complete"])
            self.assertTrue(invalid_receipt["scan_errors"])

    def test_dataset_identity_accepts_only_exact_missing_key_hwc_layout(self) -> None:
        embedded = self._embedded_python("dataset_identity.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = dict(self.contract["dataset"])
            dataset = root / "datasets" / expected["repo_id"]
            (dataset / "meta").mkdir(parents=True)
            expected["root"] = str(dataset)
            contract = root / "contract.json"
            contract_data = {
                "dataset": expected,
                "required_environment": {"HF_LEROBOT_HOME": str(dataset.parent)},
            }
            contract.write_text(json.dumps(contract_data), encoding="utf-8")
            info = {
                "codebase_version": expected["codebase_version"],
                "total_episodes": expected["episodes"],
                "total_frames": expected["frames"],
                "features": {
                    "observation.state": {"shape": [expected["state_dimension"]]},
                    "action": {"shape": [expected["action_dimension"]]},
                    **{
                        name: {"shape": shape}
                        for name, shape in expected["camera_shapes_hwc"].items()
                    },
                },
            }

            def run_identity(
                selected_info: dict[str, object],
                selected_dataset: Path = dataset,
            ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
                (selected_dataset / "meta").mkdir(parents=True, exist_ok=True)
                (selected_dataset / "meta/info.json").write_text(
                    json.dumps(selected_info), encoding="utf-8"
                )
                completed = subprocess.run(
                    [sys.executable, "-", str(contract), str(selected_dataset)],
                    input=embedded,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                return completed, json.loads(completed.stdout)

            def clone_info() -> dict[str, object]:
                return json.loads(json.dumps(info))

            accepted, accepted_result = run_identity(clone_info())
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertTrue(accepted_result["pass"])
            self.assertFalse(accepted_result["observed"]["repo_id_field_present"])
            self.assertEqual(
                accepted_result["observed"]["repo_id_policy"], "local_v3_missing"
            )

            explicit_null = clone_info()
            explicit_null["repo_id"] = None
            rejected_null, null_result = run_identity(explicit_null)
            self.assertEqual(rejected_null.returncode, 2, rejected_null.stderr)
            self.assertIn("repo_id_policy_supported", null_result["issues"])
            self.assertTrue(null_result["observed"]["repo_id_field_present"])

            exact_string = clone_info()
            exact_string["repo_id"] = expected["repo_id"]
            accepted_string, string_result = run_identity(exact_string)
            self.assertEqual(accepted_string.returncode, 0, accepted_string.stderr)
            self.assertEqual(string_result["observed"]["repo_id_policy"], "metadata_exact")

            for invalid_repo_id in ("wrong/repository", 7, [expected["repo_id"]]):
                with self.subTest(invalid_repo_id=invalid_repo_id):
                    wrong_repo = clone_info()
                    wrong_repo["repo_id"] = invalid_repo_id
                    rejected_repo, repo_result = run_identity(wrong_repo)
                    self.assertEqual(rejected_repo.returncode, 2, rejected_repo.stderr)
                    self.assertIn("repo_id_policy_supported", repo_result["issues"])

            negative_shapes = {
                "chw": [3, 240, 320],
                "wrong_resolution": [240, 321, 3],
                "wrong_channel_count": [240, 320, 4],
            }
            for name, shape in negative_shapes.items():
                with self.subTest(camera_shape=name):
                    wrong_camera = clone_info()
                    wrong_camera["features"]["observation.images.env_cam"]["shape"] = shape
                    rejected_camera, camera_result = run_identity(wrong_camera)
                    self.assertEqual(rejected_camera.returncode, 2, rejected_camera.stderr)
                    self.assertIn(
                        "camera_observation.images.env_cam", camera_result["issues"]
                    )
                    self.assertIn("repo_id_policy_supported", camera_result["issues"])

            missing_camera = clone_info()
            del missing_camera["features"]["observation.images.left_wrist_cam"]
            rejected_camera, camera_result = run_identity(missing_camera)
            self.assertEqual(rejected_camera.returncode, 2, rejected_camera.stderr)
            self.assertIn(
                "camera_observation.images.left_wrist_cam", camera_result["issues"]
            )

            scalar_drift_cases = (
                ("codebase_version", "v2.1", "codebase_version_exact"),
                ("total_episodes", expected["episodes"] + 1, "episodes_exact"),
                ("total_frames", expected["frames"] + 1, "frames_exact"),
            )
            for key, value, issue in scalar_drift_cases:
                with self.subTest(identity_field=key):
                    drifted = clone_info()
                    drifted[key] = value
                    rejected, result = run_identity(drifted)
                    self.assertEqual(rejected.returncode, 2, rejected.stderr)
                    self.assertIn(issue, result["issues"])
                    self.assertIn("repo_id_policy_supported", result["issues"])

            for feature, shape, issue in (
                ("observation.state", [15], "state_16d"),
                ("action", [15], "action_16d"),
            ):
                with self.subTest(feature=feature):
                    drifted = clone_info()
                    drifted["features"][feature]["shape"] = shape
                    rejected, result = run_identity(drifted)
                    self.assertEqual(rejected.returncode, 2, rejected.stderr)
                    self.assertIn(issue, result["issues"])
                    self.assertIn("repo_id_policy_supported", result["issues"])

            wrong_dataset = dataset.parent / "wrong-basename"
            wrong_basename, wrong_result = run_identity(clone_info(), wrong_dataset)
            self.assertEqual(wrong_basename.returncode, 2, wrong_basename.stderr)
            self.assertIn("root_exact", wrong_result["issues"])
            self.assertIn("root_basename_repo_id_exact", wrong_result["issues"])
            self.assertIn("repo_id_policy_supported", wrong_result["issues"])

            contract_data["required_environment"]["HF_LEROBOT_HOME"] = str(root / "other-cache")
            contract.write_text(json.dumps(contract_data), encoding="utf-8")
            wrong_cache, wrong_cache_result = run_identity(clone_info())
            self.assertEqual(wrong_cache.returncode, 2, wrong_cache.stderr)
            self.assertIn("cache_parent_exact", wrong_cache_result["issues"])
            self.assertIn("repo_id_policy_supported", wrong_cache_result["issues"])

    def test_v2_contract_changes_only_versioned_identity_and_fresh_roots(self) -> None:
        predecessor = json.loads(PREDECESSOR_CONTRACT.read_text(encoding="utf-8"))
        current = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertNotEqual(current["training_id"], predecessor["training_id"])
        self.assertTrue(current["training_id"].endswith("_v2"))
        self.assertNotEqual(
            current["output"]["training_root"], predecessor["output"]["training_root"]
        )
        self.assertNotEqual(
            current["output"]["evidence_root"], predecessor["output"]["evidence_root"]
        )
        self.assertTrue(current["output"]["training_root"].endswith("_v2"))
        self.assertTrue(current["output"]["evidence_root"].endswith("-v2"))
        predecessor["training_id"] = current["training_id"]
        predecessor["output"] = current["output"]
        self.assertEqual(current, predecessor)

    def test_genesis_revision_resolves_from_distribution_direct_url(self) -> None:
        embedded = self._embedded_python("runtime_identity.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_repo = root / "Genesis"
            fake_repo.mkdir()
            site_packages = root / "site-packages"
            for package in ("genesis", "lerobot", "torch"):
                (site_packages / package).mkdir(parents=True, exist_ok=True)
            (site_packages / "genesis/__init__.py").write_text("", encoding="utf-8")
            (site_packages / "lerobot/__init__.py").write_text(
                '__version__ = "0.6.2"\n', encoding="utf-8"
            )
            (site_packages / "torch/__init__.py").write_text(
                """
__version__ = "2.9.1+rocm7.2.1.gitff65f5bc"
class _Version:
    hip = "7.2.53211-e1a6bc5663"
version = _Version()
class _Cuda:
    @staticmethod
    def device_count(): return 1
    @staticmethod
    def get_device_name(index): return "AMD Radeon Graphics"
    @staticmethod
    def is_available(): return True
cuda = _Cuda()
""".lstrip(),
                encoding="utf-8",
            )
            metadata = site_packages / "genesis_world-1.3.0.dist-info"
            metadata.mkdir()
            (metadata / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: genesis-world\nVersion: 1.3.0\n",
                encoding="utf-8",
            )
            (metadata / "direct_url.json").write_text(
                json.dumps({"dir_info": {}, "url": fake_repo.as_uri()}),
                encoding="utf-8",
            )
            (fake_repo / "SOURCE").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(fake_repo)], check=True)
            subprocess.run(
                ["git", "-C", str(fake_repo), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(fake_repo), "config", "user.name", "Test"], check=True
            )
            subprocess.run(["git", "-C", str(fake_repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(fake_repo), "commit", "-qm", "fixture"], check=True
            )
            revision = subprocess.check_output(
                ["git", "-C", str(fake_repo), "rev-parse", "HEAD"], text=True
            ).strip()
            contract = root / "contract.json"
            runtime = dict(self.contract["runtime"])
            runtime["genesis_revision"] = revision
            runtime["persistent_root"] = str(root)
            contract.write_text(json.dumps({"runtime": runtime}), encoding="utf-8")
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(site_packages)

            def run_identity() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-", str(contract), str(root / "unrelated/project")],
                    input=embedded,
                    text=True,
                    capture_output=True,
                    check=False,
                    env=environment,
                )

            completed = run_identity()
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertTrue(result["pass"])
            self.assertEqual(
                result["observed"]["genesis_git_root"], str(fake_repo.resolve())
            )
            self.assertNotEqual(
                Path(result["observed"]["genesis_module_file"]).parent,
                fake_repo.resolve(),
            )
            self.assertEqual(result["observed"]["genesis_revision"], revision)

            (metadata / "direct_url.json").write_text(
                json.dumps({"dir_info": {}, "url": "https://example.invalid/Genesis"}),
                encoding="utf-8",
            )
            non_local = run_identity()
            self.assertEqual(non_local.returncode, 2, non_local.stderr)
            non_local_result = json.loads(non_local.stdout)
            self.assertFalse(non_local_result["checks"]["genesis_direct_url_local_file"])

            non_git = root / "not-a-git-checkout"
            non_git.mkdir()
            (metadata / "direct_url.json").write_text(
                json.dumps({"dir_info": {}, "url": non_git.as_uri()}),
                encoding="utf-8",
            )
            no_git = run_identity()
            self.assertEqual(no_git.returncode, 2, no_git.stderr)
            no_git_result = json.loads(no_git.stdout)
            self.assertFalse(no_git_result["checks"]["genesis_checkout_git_marker"])

    def test_exact_contract_training_command_is_encoded(self) -> None:
        expected = {
            "--dataset.repo_id=${repo_id}",
            "--policy.type=act",
            "--policy.device=cuda",
            "--output_dir=${training_root}",
            "--seed=${seed}",
            "--steps=${steps}",
            "--batch_size=${batch_size}",
            "--num_workers=${num_workers}",
            "--save_freq=${save_freq}",
            "--log_freq=${log_freq}",
            "--eval_steps=${eval_steps}",
            "--save_checkpoint=true",
            "--wandb.enable=false",
            "--policy.chunk_size=${chunk_size}",
            "--policy.n_action_steps=${action_steps}",
            "--policy.n_obs_steps=${obs_steps}",
            "--policy.push_to_hub=false",
        }
        for argument in expected:
            with self.subTest(argument=argument):
                self.assertIn(f'"{argument}"', self.source)
        self.assertNotIn("--dataset.root=", self.source)
        self.assertEqual(self.contract["policy"]["steps"], 10000)
        self.assertEqual(self.contract["policy"]["save_freq"], 5000)
        self.assertEqual(self.contract["policy"]["eval_steps"], 0)

    def test_one_launch_and_no_restart_or_foreign_process_stop(self) -> None:
        invocations = re.findall(
            r'^"\$\{train_command\[@\]\}" > "\$\{evidence_root\}/train\.log" 2>&1 &$',
            self.source,
            flags=re.MULTILINE,
        )
        self.assertEqual(len(invocations), 1)
        lowered = self.source.lower()
        self.assertNotIn("pkill", lowered)
        self.assertNotIn("killall", lowered)
        self.assertNotIn("reboot", lowered)
        self.assertNotIn("shutdown", lowered)
        self.assertNotIn("restart", lowered)
        self.assertNotIn("rm -", lowered)
        self.assertIn('kill "${telemetry_pid}"', self.source)

    def test_two_milestones_are_exact_and_individually_receipted(self) -> None:
        self.assertEqual(self.contract["required_milestones"], [5000, 10000])
        self.assertIn(
            "for ((step_value=save_freq; step_value<=steps; step_value+=save_freq))",
            self.source,
        )
        self.assertIn("capture_act_checkpoint_receipt.py", self.source)
        self.assertIn("checkpoint_${step}_v1", self.source)
        self.assertIn("checkpoint_audit.json", self.source)
        self.assertIn('expected_last = root / f"{steps:06d}"', self.source)

        embedded = self._embedded_python("checkpoint_audit.json")
        with tempfile.TemporaryDirectory() as directory:
            training = Path(directory) / "training"
            checkpoints = training / "checkpoints"
            for step in (5000, 10000):
                checkpoint = checkpoints / f"{step:06d}"
                for relative in (
                    "pretrained_model/model.safetensors",
                    "pretrained_model/config.json",
                    "pretrained_model/policy_preprocessor.json",
                    "pretrained_model/policy_postprocessor.json",
                    "training_state/optimizer_state.safetensors",
                ):
                    path = checkpoint / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("fixture\n", encoding="utf-8")
                (checkpoint / "training_state/training_step.json").write_text(
                    json.dumps({"step": step}), encoding="utf-8"
                )
            (checkpoints / "last").symlink_to("010000")
            output = Path(directory) / "audit.json"
            completed = subprocess.run(
                [sys.executable, "-", str(training), str(output), "10000", "5000"],
                input=embedded,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(result["pass"])
            self.assertEqual(result["expected"], ["005000", "010000"])

    def test_terminal_evidence_and_failure_signatures_are_present(self) -> None:
        for marker in (
            "gpu_${phase}.txt",
            "gpu_during.txt",
            "gpu_after.txt",
            "train.exit_code.txt",
            "metrics.json",
            "training_output.SHA256SUMS",
            "final_evidence.SHA256SUMS",
            "PASS_TRAINING_COMPLETE",
            "out of memory",
            "non-finite",
            "deadline_admission.json",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)

    def test_launch_and_terminal_drift_checks_are_fail_closed(self) -> None:
        self.assertIn("check_persistent_mount launch", self.source)
        self.assertIn("check_idle_gpu launch", self.source)
        self.assertIn("persistence_launch.json", self.source)
        self.assertIn("persistent_mount_after.txt", self.source)
        self.assertIn("kfd_owner_count_after.txt", self.source)
        self.assertIn("matching_processes_after.txt", self.source)
        self.assertIn("finalization_rc=93", self.source)

    def test_final_manifest_failure_changes_terminal_status(self) -> None:
        self.assertIn('local manifest_rc=$?', self.source)
        self.assertIn('if [[ "${manifest_rc}" -ne 0 ]]', self.source)
        self.assertIn("finalization_rc=94", self.source)
        self.assertIn("FAIL_FINALIZATION", self.source)
        self.assertIn('exit "${rc}"', self.source)
        self.assertNotIn('exit "${original_rc}"', self.source)

    def test_public_or_destructive_actions_are_absent(self) -> None:
        lowered = self.source.lower()
        for forbidden in ("git push", "gh pr", "submit", "publish", "docker push"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
