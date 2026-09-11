import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


summary = load_script("summarize_pi05_libero_benchmark")
manifest = load_script("build_pi05_libero_benchmark_manifest")
runner = load_script("run_pi05_libero_eval_rocm")
radeon = load_script("summarize_pi05_libero_radeon_compile_ablation")

TIMING_SOURCE = (
    ROOT / "third_party" / "lerobot" / "src" / "lerobot" / "utils" / "inference_timing.py"
)
LEROBOT_ROOT = ROOT / "third_party" / "lerobot"
if not LEROBOT_ROOT.is_dir():
    LEROBOT_ROOT = Path("/workspace/parcel-sorter-rocm/third_party/lerobot")
if not TIMING_SOURCE.is_file():
    TIMING_SOURCE = Path(
        "/workspace/parcel-sorter-rocm/third_party/lerobot/src/lerobot/utils/inference_timing.py"
    )
timing = None
if TIMING_SOURCE.is_file():
    timing_spec = importlib.util.spec_from_file_location(
        "lerobot_inference_timing",
        TIMING_SOURCE,
    )
    timing = importlib.util.module_from_spec(timing_spec)
    assert timing_spec.loader is not None
    timing_spec.loader.exec_module(timing)


class PI05LiberoBenchmarkToolTests(unittest.TestCase):
    def test_radeon_ablation_config_is_frozen_and_drift_balanced(self) -> None:
        payload = radeon.load_config(
            ROOT / "configs" / "pi05_libero_radeon_compile_ablation_v1.json"
        )
        order = payload["experimental_design"]["execution_order"]
        self.assertEqual([item["compile"] for item in order], [False, True, True, False])
        self.assertEqual(payload["experimental_design"]["unique_units"], 40)
        self.assertTrue(payload["experimental_design"]["repeats_are_not_independent_success_samples"])

    def test_radeon_endurance_config_hash_and_repeated_unit_boundary(self) -> None:
        import json

        path = ROOT / "configs" / "pi05_libero_radeon_endurance_v1.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        recorded = payload.pop("config_sha256")
        self.assertEqual(recorded, runner.canonical_sha256(payload))
        design = payload["experimental_design"]
        self.assertEqual(design["unique_units"], 40)
        self.assertEqual(design["attempts"], 120)
        self.assertTrue(design["repeats_are_not_independent_success_samples"])

    @unittest.skipIf(timing is None, "patched LeRobot source is not installed")
    def test_policy_timing_separates_model_inference_from_queue_dispatch(self) -> None:
        records = [
            {
                "started_monotonic_ns": start,
                "latency_ms": latency,
                "queue_observed": True,
                "model_inference_expected": is_inference,
            }
            for start, latency, is_inference in [
                (60, 40.0, True),
                (10, 100.0, True),
                (20, 1.0, False),
                (30, 10.0, True),
                (40, 20.0, True),
                (50, 2.0, False),
            ]
        ]
        result = timing.summarize_policy_timing_records(records)
        self.assertEqual(result["select_action_calls"]["cold_start_ms"], 100.0)
        self.assertEqual(result["model_inference_calls"]["count"], 4)
        self.assertEqual(result["model_inference_calls"]["warm_p50_ms"], 20.0)
        self.assertEqual(result["queued_action_dispatch_calls"]["count"], 2)
        self.assertEqual(result["queued_action_dispatch_calls"]["warm_p50_ms"], 1.5)

    def test_runner_validates_rocm_inference_measurements(self) -> None:
        eval_info = {
            "overall": {
                "policy_timing": {
                    "queue_observed_calls": 30,
                    "select_action_calls": {"count": 30},
                    "model_inference_calls": {
                        "count": 3,
                        "warm_p50_ms": 100.0,
                        "warm_p95_ms": 110.0,
                        "warm_p99_ms": 115.0,
                    },
                    "queued_action_dispatch_calls": {"count": 27},
                },
                "accelerator_memory": {
                    "available": True,
                    "torch_hip_version": "7.2",
                    "peak_allocated_bytes": 1024,
                },
            }
        }
        result = runner.validate_eval_measurements(eval_info)
        self.assertEqual(result["status"], "passed")
        eval_info["overall"]["policy_timing"]["queue_observed_calls"] = 29
        with self.assertRaises(RuntimeError):
            runner.validate_eval_measurements(eval_info)

    def test_runner_rejects_lerobot_source_hash_drift(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src" / "lerobot" / "scripts" / "lerobot_eval.py"
            source.parent.mkdir(parents=True)
            source.write_text("stable", encoding="utf-8")
            payload = {
                "sources": {
                    "lerobot_source_hashes": {
                        "scripts/lerobot_eval.py": runner.sha256_file(source),
                    }
                }
            }
            result = runner.lerobot_source_integrity(payload, root)
            self.assertIn("scripts/lerobot_eval.py", result["verified_files"])
            source.write_text("drift", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                runner.lerobot_source_integrity(payload, root)

    def test_development_and_confirmation_records_are_disjoint(self) -> None:
        tasks = [{"suite": "s", "task_id": 0, "task_name": "t", "horizon": 10}]
        development = manifest.build_run_records(
            tasks, init_state_ids=range(10, 20), seed=1, phase="development"
        )
        confirmation = manifest.build_run_records(
            tasks, init_state_ids=range(0, 10), seed=2, phase="confirmation"
        )
        self.assertFalse(
            {row["experimental_unit"] for row in development}
            & {row["experimental_unit"] for row in confirmation}
        )

    def test_manifest_records_follow_lerobot_task_major_order(self) -> None:
        tasks = [
            {"suite": "s", "task_id": task_id, "task_name": f"t{task_id}", "horizon": 10}
            for task_id in range(2)
        ]
        records = manifest.build_run_records(
            tasks,
            init_state_ids=range(3),
            seed=999,
            phase="confirmation",
        )
        self.assertEqual(
            [(row["task_id"], row["init_state_id"]) for row in records],
            [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)],
        )

    def test_runner_rejects_manifest_order_drift(self) -> None:
        scope = {
            "phase": "confirmation",
            "suites": ["libero_spatial"],
            "task_ids": list(range(10)),
        }
        records = [
            {
                "suite": "libero_spatial",
                "task_id": task_id,
                "init_state_id": state_id,
                "run_order": order,
            }
            for order, (task_id, state_id) in enumerate(
                (task_id, state_id)
                for task_id in range(10)
                for state_id in range(2)
            )
        ]
        payload = {
            "experimental_design": {
                "run_order_protocol": {
                    "confirmation": "lerobot-suite-task-init-state-v1"
                },
                "confirmation": {"init_state_ids": [0, 1]},
            },
            "run_schedule": {"confirmation": records},
        }
        runner.validate_executable_schedule(payload, scope)
        records[0], records[1] = records[1], records[0]
        records[0]["run_order"], records[1]["run_order"] = 0, 1
        with self.assertRaises(RuntimeError):
            runner.validate_executable_schedule(payload, scope)

    def test_flatten_and_wilson_summary(self) -> None:
        payload = {
            "per_task": [
                {
                    "task_group": "libero_spatial",
                    "task_id": 0,
                    "metrics": {"successes": [True, False, True]},
                }
            ]
        }
        outcomes = summary.flatten_successes(payload)
        result = summary.summarize_successes(outcomes)
        self.assertEqual(result["overall"]["successes"], 2)
        self.assertEqual(result["overall"]["episodes"], 3)
        self.assertLess(result["overall"]["wilson_95_percent"][0], 100 * 2 / 3)

    def test_paired_comparison_never_uses_aggregate_only(self) -> None:
        baseline = {("suite", 0, index): False for index in range(6)}
        candidate = {key: True for key in baseline}
        result = summary.paired_comparison(baseline, candidate)
        self.assertEqual(result["candidate_wins"], 6)
        self.assertEqual(result["candidate_losses"], 0)
        self.assertGreater(result["paired_difference_95_percent"][0], 0.0)
        self.assertTrue(result["superiority_at_alpha_0_05"])

    def test_paired_superiority_requires_positive_confidence_bound(self) -> None:
        keys = [("suite", 0, index) for index in range(400)]
        baseline = {key: index < 380 for index, key in enumerate(keys)}
        candidate = dict(baseline)
        for key in keys[380:395]:
            candidate[key] = True
        result = summary.paired_comparison(baseline, candidate)
        self.assertLess(result["exact_one_sided_mcnemar_p"], 0.05)
        self.assertGreater(result["paired_difference_95_percent"][0], 0.0)
        self.assertTrue(result["superiority_at_alpha_0_05"])

        candidate = dict(baseline)
        candidate[keys[380]] = True
        result = summary.paired_comparison(baseline, candidate)
        self.assertFalse(result["superiority_at_alpha_0_05"])

    def test_paired_comparison_rejects_mismatched_units(self) -> None:
        with self.assertRaises(ValueError):
            summary.paired_comparison({("s", 0, 0): True}, {("s", 0, 1): True})

    def test_manifest_hash_validation_detects_mutation(self) -> None:
        import json
        import tempfile

        payload = {"protocol_id": "x"}
        payload["manifest_sha256"] = runner.canonical_sha256(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = runner.load_manifest(path)
            self.assertEqual(loaded["protocol_id"], "x")
            payload["protocol_id"] = "mutated"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                runner.load_manifest(path)

    def test_protocol_patch_matches_frozen_manifest(self) -> None:
        import json

        payload = json.loads(
            (ROOT / "configs" / "pi05_libero_public_benchmark_v2.json").read_text(
                encoding="utf-8"
            )
        )
        actual = runner.sha256_file(
            ROOT / "artifacts" / "patches" / "lerobot-libero-frozen-eval.patch"
        )
        self.assertEqual(actual, payload["sources"]["lerobot_protocol_patch_sha256"])

    def test_wiring_scope_only_uses_development_states(self) -> None:
        manifest_payload = {
            "experimental_design": {
                "development": {"init_state_ids": list(range(10, 20))},
            }
        }
        args = SimpleNamespace(
            phase="wiring",
            episodes=3,
            wiring_suite="libero_spatial",
            wiring_task_id=0,
        )
        scope = runner.resolve_run_scope(args, manifest_payload)
        self.assertEqual(scope["init_state_offset"], 10)
        self.assertEqual(scope["episodes_per_task"], 3)
        self.assertEqual(scope["suites"], ["libero_spatial"])
        self.assertEqual(scope["task_ids"], [0])
        self.assertFalse(scope["score_eligible"])

    def test_wiring_scope_rejects_benchmark_sized_override(self) -> None:
        manifest_payload = {
            "experimental_design": {
                "development": {"init_state_ids": list(range(10, 20))},
            }
        }
        args = SimpleNamespace(
            phase="wiring",
            episodes=10,
            wiring_suite="libero_spatial",
            wiring_task_id=0,
        )
        with self.assertRaises(ValueError):
            runner.resolve_run_scope(args, manifest_payload)

    def test_efficiency_scope_uses_one_development_state_for_all_tasks(self) -> None:
        manifest_payload = {
            "experimental_design": {
                "development": {"init_state_ids": list(range(10, 20))},
            }
        }
        args = SimpleNamespace(phase="efficiency", episodes=None)
        scope = runner.resolve_run_scope(args, manifest_payload)
        self.assertEqual(scope["init_state_offset"], 10)
        self.assertEqual(scope["episodes_per_task"], 1)
        self.assertEqual(scope["suites"], list(runner.LIBERO_SUITES))
        self.assertIsNone(scope["task_ids"])
        self.assertFalse(scope["score_eligible"])

    def test_efficiency_scope_rejects_episode_expansion(self) -> None:
        manifest_payload = {
            "experimental_design": {
                "development": {"init_state_ids": list(range(10, 20))},
            }
        }
        with self.assertRaises(ValueError):
            runner.resolve_run_scope(
                SimpleNamespace(phase="efficiency", episodes=2),
                manifest_payload,
            )

    def test_endurance_scope_and_schedule_repeat_fixed_state_by_cycle(self) -> None:
        suites = list(runner.LIBERO_SUITES)
        records = []
        for repetition in range(3):
            for suite in suites:
                for task_id in range(10):
                    records.append(
                        {
                            "suite": suite,
                            "task_id": task_id,
                            "init_state_id": 20,
                            "repetition": repetition,
                            "run_order": len(records),
                        }
                    )
        payload = {
            "experimental_design": {
                "run_order_protocol": {
                    "radeon_soak": "lerobot-interleaved-task-repeat-v1"
                },
                "radeon_soak": {
                    "init_state_id": 20,
                    "repetitions_per_task": 3,
                },
            },
            "run_schedule": {"radeon_soak": records},
        }
        scope = runner.resolve_run_scope(
            SimpleNamespace(phase="endurance", episodes=None), payload
        )
        self.assertEqual(scope["init_state_offset"], 20)
        self.assertEqual(scope["episodes_per_task"], 3)
        self.assertFalse(scope["score_eligible"])
        runner.validate_executable_schedule(payload, scope)
        records[0], records[1] = records[1], records[0]
        records[0]["run_order"], records[1]["run_order"] = 0, 1
        with self.assertRaises(RuntimeError):
            runner.validate_executable_schedule(payload, scope)

    @unittest.skipUnless(
        (LEROBOT_ROOT / "src" / "lerobot" / "scripts" / "lerobot_eval.py").is_file(),
        "patched LeRobot source is not installed",
    )
    def test_endurance_command_enables_fixed_state_interleaving(self) -> None:
        scope = {
            "phase": "endurance",
            "suites": list(runner.LIBERO_SUITES),
            "task_ids": None,
            "init_state_offset": 20,
            "episodes_per_task": 3,
        }
        args = SimpleNamespace(
            lerobot_root=LEROBOT_ROOT,
            output=ROOT / "outputs" / "dry",
            checkpoint=Path("checkpoint"),
            seed=1,
            compile="false",
        )
        command = runner.build_command(args, {}, scope)
        self.assertIn("--env.init_state_stride=0", command)
        self.assertIn("--eval.interleave_task_episodes=true", command)
        self.assertIn("--eval.n_episodes=3", command)

    @unittest.skipUnless(
        (LEROBOT_ROOT / "src" / "lerobot" / "scripts" / "lerobot_eval.py").is_file(),
        "patched LeRobot source is not installed",
    )
    def test_action_steps_default_to_manifest_and_allow_explicit_ablation(self) -> None:
        manifest = {
            "benchmark": {
                "action_chunk_size": 50,
                "executed_action_steps_per_inference": 10,
            }
        }
        scope = {
            "phase": "efficiency",
            "suites": list(runner.LIBERO_SUITES),
            "task_ids": None,
            "init_state_offset": 10,
            "episodes_per_task": 1,
        }
        args = SimpleNamespace(
            lerobot_root=LEROBOT_ROOT,
            output=ROOT / "outputs" / "dry",
            checkpoint=Path("checkpoint"),
            seed=1,
            compile="false",
            action_steps=None,
        )
        self.assertIn("--policy.n_action_steps=10", runner.build_command(args, manifest, scope))

        args.action_steps = 4
        self.assertIn("--policy.n_action_steps=4", runner.build_command(args, manifest, scope))
        args.action_steps = 51
        with self.assertRaisesRegex(ValueError, "action_steps"):
            runner.build_command(args, manifest, scope)


if __name__ == "__main__":
    unittest.main()
