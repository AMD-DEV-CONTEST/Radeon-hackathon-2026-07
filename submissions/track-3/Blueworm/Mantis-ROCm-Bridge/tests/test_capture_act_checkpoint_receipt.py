import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "capture_act_checkpoint_receipt.py"
SPEC = importlib.util.spec_from_file_location(
    "capture_act_checkpoint_receipt", TOOL_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


STEP = 5000


def make_checkpoint(root: Path, step: int = STEP) -> Path:
    checkpoint = root / "checkpoint"
    (checkpoint / "pretrained_model").mkdir(parents=True)
    (checkpoint / "training_state").mkdir(parents=True)
    (checkpoint / "pretrained_model" / "model.safetensors").write_bytes(
        b"model-weights"
    )
    (
        checkpoint / "training_state" / "optimizer_state.safetensors"
    ).write_bytes(b"optimizer-state")
    (
        checkpoint / "training_state" / "training_step.json"
    ).write_text(json.dumps({"step": step}), encoding="utf-8")
    (checkpoint / "pretrained_model" / "config.json").write_text(
        '{"policy":"act"}\n', encoding="utf-8"
    )
    return checkpoint


def output_set(prefix: Path) -> list[Path]:
    return list(MODULE.output_paths(prefix).values())


class CollectorFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.checkpoint = make_checkpoint(self.root)
        self.log = self.root / "train.log"
        self.log.write_text(
            "INFO step:5K loss:0.1 grdn:1.0\n", encoding="utf-8"
        )
        self.prefix = self.root / "receipts" / "checkpoint_005000_v1"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def argv(self, *extra: str) -> list[str]:
        return [
            str(self.checkpoint),
            "--expected-step",
            str(STEP),
            "--training-log",
            str(self.log),
            "--output-prefix",
            str(self.prefix),
            "--skip-gpu",
            *extra,
        ]

    def assert_no_outputs(self) -> None:
        self.assertTrue(all(not path.exists() for path in output_set(self.prefix)))


class HappyPathTests(CollectorFixture):
    def test_writes_six_outputs(self) -> None:
        self.assertEqual(MODULE.main(self.argv()), 0)
        self.assertTrue(all(path.is_file() for path in output_set(self.prefix)))

    def test_receipt_contract_and_claim_boundary(self) -> None:
        self.assertEqual(MODULE.main(self.argv()), 0)
        receipt = json.loads(
            MODULE.output_paths(self.prefix)["receipt"].read_text()
        )
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["expected_step"], STEP)
        self.assertEqual(receipt["recorded_step"], STEP)
        self.assertTrue(receipt["step_match"])
        self.assertEqual(receipt["exact_error_match_count"], 0)
        self.assertTrue(receipt["claim_boundary"]["provenance_only"])
        self.assertFalse(receipt["claim_boundary"]["convergence_claimed"])
        self.assertFalse(receipt["claim_boundary"]["inference_claimed"])
        self.assertFalse(receipt["claim_boundary"]["closed_loop_claimed"])

    def test_inventory_is_sorted_and_complete(self) -> None:
        self.assertEqual(MODULE.main(self.argv()), 0)
        lines = (
            MODULE.output_paths(self.prefix)["inventory"]
            .read_text()
            .splitlines()
        )
        paths = [line.split("\t", 1)[0] for line in lines]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(
            paths,
            [
                "pretrained_model/config.json",
                "pretrained_model/model.safetensors",
                "training_state/optimizer_state.safetensors",
                "training_state/training_step.json",
            ],
        )

    def test_checkpoint_hashes_independently_recompute(self) -> None:
        self.assertEqual(MODULE.main(self.argv()), 0)
        manifest = MODULE.output_paths(self.prefix)["sha256sums"].read_text()
        for line in manifest.splitlines():
            digest, relative = line.split("  ", 1)
            actual = hashlib.sha256(
                (self.checkpoint / relative).read_bytes()
            ).hexdigest()
            self.assertEqual(digest, actual)

    def test_artifact_manifest_covers_other_five_outputs(self) -> None:
        self.assertEqual(MODULE.main(self.argv()), 0)
        outputs = MODULE.output_paths(self.prefix)
        lines = outputs["artifacts_sha256sums"].read_text().splitlines()
        self.assertEqual(len(lines), 5)
        expected_names = {
            outputs[key].name
            for key in ("inventory", "sha256sums", "gpu", "receipt", "status")
        }
        observed_names = set()
        for line in lines:
            digest, name = line.split("  ", 1)
            observed_names.add(name)
            self.assertEqual(
                digest,
                hashlib.sha256((outputs["inventory"].parent / name).read_bytes())
                .hexdigest(),
            )
        self.assertEqual(observed_names, expected_names)

    def test_skip_gpu_is_explicit(self) -> None:
        self.assertEqual(MODULE.main(self.argv()), 0)
        outputs = MODULE.output_paths(self.prefix)
        self.assertIn("GPU CAPTURE SKIPPED", outputs["gpu"].read_text())
        receipt = json.loads(outputs["receipt"].read_text())
        self.assertTrue(receipt["gpu"]["skipped"])
        self.assertEqual(receipt["gpu"]["capture_argv"], [])

    def test_checkpoint_directory_is_unchanged(self) -> None:
        before = {
            path.relative_to(self.checkpoint).as_posix(): path.read_bytes()
            for path in self.checkpoint.rglob("*")
            if path.is_file()
        }
        self.assertEqual(MODULE.main(self.argv()), 0)
        after = {
            path.relative_to(self.checkpoint).as_posix(): path.read_bytes()
            for path in self.checkpoint.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)


class FailureGateTests(CollectorFixture):
    def test_step_mismatch_fails_closed(self) -> None:
        argv = self.argv()
        argv[argv.index(str(STEP))] = "10000"
        self.assertEqual(MODULE.main(argv), 1)
        self.assert_no_outputs()

    def test_missing_required_model_fails_closed(self) -> None:
        (
            self.checkpoint / "pretrained_model" / "model.safetensors"
        ).unlink()
        self.assertEqual(MODULE.main(self.argv()), 1)
        self.assert_no_outputs()

    def test_empty_required_optimizer_fails_closed(self) -> None:
        (
            self.checkpoint
            / "training_state"
            / "optimizer_state.safetensors"
        ).write_bytes(b"")
        self.assertEqual(MODULE.main(self.argv()), 1)
        self.assert_no_outputs()

    def test_bool_training_step_is_rejected(self) -> None:
        (
            self.checkpoint / "training_state" / "training_step.json"
        ).write_text('{"step": true}', encoding="utf-8")
        self.assertEqual(MODULE.main(self.argv()), 1)
        self.assert_no_outputs()

    def test_missing_training_log_fails_closed(self) -> None:
        self.log.unlink()
        self.assertEqual(MODULE.main(self.argv()), 1)
        self.assert_no_outputs()

    def test_output_inside_checkpoint_fails_closed(self) -> None:
        self.prefix = self.checkpoint / "receipt"
        self.assertEqual(MODULE.main(self.argv()), 1)
        self.assert_no_outputs()

    def test_checkpoint_mutation_during_hashing_fails_closed(self) -> None:
        target = self.checkpoint / "pretrained_model" / "config.json"
        real_hash = MODULE.sha256_file

        def mutate_after_hash(path: Path) -> str:
            digest = real_hash(path)
            if path.resolve() == target.resolve():
                target.write_text('{"policy":"changed"}\n', encoding="utf-8")
            return digest

        with mock.patch.object(MODULE, "sha256_file", side_effect=mutate_after_hash):
            self.assertEqual(MODULE.main(self.argv()), 1)
        self.assert_no_outputs()


class ErrorTaxonomyTests(unittest.TestCase):
    def test_exact_taxonomy_is_case_insensitive(self) -> None:
        text = (
            "Traceback\n"
            "CUDA out of memory\n"
            "hip OUT OF memory\n"
            "RuntimeError\n"
            "loss:nan grdn:inf\n"
        )
        self.assertEqual(MODULE.scan_log_errors(text), 6)

    def test_benign_inf_words_are_not_errors(self) -> None:
        text = "information inference loss:infinite grdn:infinite\n"
        self.assertEqual(MODULE.scan_log_errors(text), 0)

    def test_matches_are_recorded_but_do_not_abort(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = make_checkpoint(root)
            log = root / "train.log"
            log.write_text("Traceback\nloss:nan\n", encoding="utf-8")
            prefix = root / "receipt"
            argv = [
                str(checkpoint),
                "--expected-step",
                str(STEP),
                "--training-log",
                str(log),
                "--output-prefix",
                str(prefix),
                "--skip-gpu",
            ]
            self.assertEqual(MODULE.main(argv), 0)
            receipt = json.loads(
                MODULE.output_paths(prefix)["receipt"].read_text()
            )
            self.assertEqual(receipt["exact_error_match_count"], 2)


class NoClobberPublicationTests(CollectorFixture):
    def test_each_preexisting_final_is_refused(self) -> None:
        for index, path in enumerate(output_set(self.prefix)):
            with self.subTest(path=path.name):
                if index:
                    self.prefix = self.root / "receipts" / f"case_{index}"
                    path = output_set(self.prefix)[index]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("PREEXISTING", encoding="utf-8")
                with self.assertRaises(SystemExit) as raised:
                    MODULE.main(self.argv())
                self.assertEqual(raised.exception.code, 2)
                self.assertEqual(path.read_text(), "PREEXISTING")
                for other in output_set(self.prefix):
                    if other != path:
                        self.assertFalse(other.exists())

    def test_unrelated_stage_prefix_file_is_preserved(self) -> None:
        sentinel = self.prefix.parent / (
            "." + self.prefix.name + ".inventory.txt.stage.preexisting"
        )
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("SENTINEL", encoding="utf-8")
        self.assertEqual(MODULE.main(self.argv()), 0)
        self.assertEqual(sentinel.read_text(), "SENTINEL")

    def test_concurrent_first_final_is_not_overwritten_or_deleted(self) -> None:
        real_link = os.link
        competing_content = b"CONCURRENT_WRITER"

        def competing_link(source, destination, **kwargs):
            Path(destination).write_bytes(competing_content)
            return real_link(source, destination, **kwargs)

        with mock.patch.object(MODULE.os, "link", side_effect=competing_link):
            self.assertEqual(MODULE.main(self.argv()), 1)

        first = output_set(self.prefix)[0]
        self.assertEqual(first.read_bytes(), competing_content)
        self.assertTrue(all(not path.exists() for path in output_set(self.prefix)[1:]))
        self.assertEqual(list(first.parent.glob(".*.stage.*")), [])

    def test_later_collision_rolls_back_only_invocation_files(self) -> None:
        real_link = os.link
        calls = 0
        competing_content = b"SECOND_WRITER"

        def collide_on_second(source, destination, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                Path(destination).write_bytes(competing_content)
            return real_link(source, destination, **kwargs)

        with mock.patch.object(MODULE.os, "link", side_effect=collide_on_second):
            self.assertEqual(MODULE.main(self.argv()), 1)

        paths = output_set(self.prefix)
        self.assertFalse(paths[0].exists())
        self.assertEqual(paths[1].read_bytes(), competing_content)
        self.assertTrue(all(not path.exists() for path in paths[2:]))
        self.assertEqual(list(paths[0].parent.glob(".*.stage.*")), [])

    def test_replaced_published_inode_is_not_deleted_during_rollback(self) -> None:
        real_link = os.link
        calls = 0
        replacement = b"REPLACEMENT"

        def replace_then_fail(source, destination, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_link(source, destination, **kwargs)
            first = output_set(self.prefix)[0]
            first.unlink()
            first.write_bytes(replacement)
            Path(destination).write_bytes(b"COLLISION")
            return real_link(source, destination, **kwargs)

        with mock.patch.object(MODULE.os, "link", side_effect=replace_then_fail):
            self.assertEqual(MODULE.main(self.argv()), 1)

        paths = output_set(self.prefix)
        self.assertEqual(paths[0].read_bytes(), replacement)
        self.assertEqual(paths[1].read_bytes(), b"COLLISION")
        self.assertTrue(all(not path.exists() for path in paths[2:]))
        self.assertEqual(list(paths[0].parent.glob(".*.stage.*")), [])


class GpuCaptureTests(CollectorFixture):
    def make_stub(self, returncode: int) -> tuple[Path, Path]:
        record = self.root / "argv.json"
        stub = self.root / "rocm-smi-stub"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['ROCM_STUB_RECORD']).write_text(json.dumps(sys.argv[1:]))\n"
            "print('GPU[0] mock telemetry')\n"
            f"raise SystemExit({returncode})\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return stub, record

    def test_exact_rocm_smi_argv(self) -> None:
        stub, record = self.make_stub(0)
        argv = self.argv()
        argv.remove("--skip-gpu")
        argv.extend(["--rocm-smi", str(stub)])
        with mock.patch.dict(os.environ, {"ROCM_STUB_RECORD": str(record)}):
            self.assertEqual(MODULE.main(argv), 0)
        self.assertEqual(json.loads(record.read_text()), list(MODULE.GPU_FLAGS))
        receipt = json.loads(
            MODULE.output_paths(self.prefix)["receipt"].read_text()
        )
        self.assertEqual(
            receipt["gpu"]["capture_argv"], [str(stub), *MODULE.GPU_FLAGS]
        )

    def test_nonzero_rocm_smi_fails_closed(self) -> None:
        stub, record = self.make_stub(7)
        argv = self.argv()
        argv.remove("--skip-gpu")
        argv.extend(["--rocm-smi", str(stub)])
        with mock.patch.dict(os.environ, {"ROCM_STUB_RECORD": str(record)}):
            self.assertEqual(MODULE.main(argv), 1)
        self.assert_no_outputs()


class ParserTests(unittest.TestCase):
    def test_no_arguments_exits_two(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            MODULE.main([])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
