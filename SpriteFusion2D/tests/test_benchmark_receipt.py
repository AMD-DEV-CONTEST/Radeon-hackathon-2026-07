"""P01: auditable benchmark receipts — unit tests, no GPU required."""

from __future__ import annotations

import contextlib
import io
import json
import os
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import torch

from benchmarks import benchmark_snapper
from benchmarks.receipt import (
    RECEIPT_FORMAT,
    RECEIPT_SCHEMA_VERSION,
    ReceiptError,
    build_receipt,
    compute_sample_stats,
    format_failure,
    git_repo_state,
    hash_source_files,
    receipt_dumps,
    sanitize_command,
    sanitize_text,
    sha256_bytes,
    sha256_file,
    tensor_fingerprint,
    validate_receipt,
    write_receipt,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

FAKE_HOME = os.path.join(os.sep, "home", "alice")
FAKE_REPO = os.path.join(os.sep, "work", "spritefusion-2d")


def make_parts(**overrides):
    samples = [0.10, 0.20, 0.30]
    parts = dict(
        benchmark={"name": "snapper", "algorithm": "optimized"},
        command=("python", "-m", "benchmarks.benchmark_snapper"),
        environment={
            "python": "3.12",
            "torch": "2.2.0",
            "device": {"requested": "cpu", "selected": "cpu", "type": "cpu"},
            "gpu": None,
            "working_dir": None,
        },
        sources=[{"role": "core", "path": "pixel_snapper_core.py", "sha256": "abc"}],
        inputs=[{"role": "image", "sha256": "in", "shape": [1, 8, 8, 3]}],
        outputs=[{"role": "frame_0", "sha256": "out", "shape": [1, 8, 8, 3]}],
        timing={
            "warmup_runs": 1,
            "runs": 3,
            "include_host_to_device": True,
            "synchronize": {"before_each_run": True, "after_each_run": True},
            "samples_seconds": samples,
            "stats": compute_sample_stats(samples).to_dict(),
            "peak_memory_bytes": None,
        },
        failures=[],
        git={
            "available": True,
            "commit_sha": "c" * 40,
            "branch": "main",
            "dirty": False,
        },
        sanitized=True,
        timestamp_utc="2026-08-06T00:00:00+00:00",
    )
    parts.update(overrides)
    return parts


class SampleStatsTests(unittest.TestCase):
    def test_matches_standard_library_statistics(self):
        samples = [0.10, 0.20, 0.30, 0.40, 0.50]
        stats = compute_sample_stats(samples)
        self.assertEqual(stats.median_seconds, statistics.median(samples))
        self.assertEqual(stats.mean_seconds, statistics.mean(samples))
        self.assertEqual(stats.min_seconds, min(samples))
        self.assertEqual(stats.max_seconds, max(samples))
        self.assertEqual(stats.pstdev_seconds, statistics.pstdev(samples))

    def test_median_is_average_for_even_count(self):
        stats = compute_sample_stats([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(stats.median_seconds, 2.5)

    def test_p90_is_nearest_rank(self):
        # ceil(0.9 * 10) = 9 -> 9th smallest value.
        self.assertEqual(compute_sample_stats(list(range(1, 11))).p90_seconds, 9.0)
        # ceil(0.9 * 4) = 4 -> the maximum.
        self.assertEqual(compute_sample_stats([1.0, 2.0, 3.0, 4.0]).p90_seconds, 4.0)
        self.assertEqual(compute_sample_stats([2.0]).p90_seconds, 2.0)

    def test_empty_samples_yield_none(self):
        stats = compute_sample_stats([])
        self.assertIsNone(stats.median_seconds)
        self.assertIsNone(stats.mean_seconds)
        self.assertIsNone(stats.min_seconds)
        self.assertIsNone(stats.max_seconds)
        self.assertIsNone(stats.pstdev_seconds)
        self.assertIsNone(stats.p90_seconds)
        self.assertEqual(
            stats.to_dict(),
            {
                "median_seconds": None,
                "mean_seconds": None,
                "min_seconds": None,
                "max_seconds": None,
                "pstdev_seconds": None,
                "p90_seconds": None,
            },
        )


class HashingTests(unittest.TestCase):
    def test_sha256_bytes_is_deterministic(self):
        self.assertEqual(sha256_bytes(b"abc"), sha256_bytes(b"abc"))
        self.assertEqual(len(sha256_bytes(b"abc")), 64)
        self.assertNotEqual(sha256_bytes(b"abc"), sha256_bytes(b"abd"))

    def test_sha256_file_matches_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.bin"
            path.write_bytes(b"file payload")
            self.assertEqual(sha256_file(path), sha256_bytes(b"file payload"))

    def test_tensor_fingerprint_is_deterministic(self):
        first = tensor_fingerprint(torch.zeros((1, 4, 4, 3)))
        second = tensor_fingerprint(torch.zeros((1, 4, 4, 3)))
        self.assertEqual(first, second)
        self.assertEqual(first["shape"], [1, 4, 4, 3])
        self.assertEqual(first["dtype"], "torch.float32")
        changed = tensor_fingerprint(torch.ones((1, 4, 4, 3)))
        self.assertNotEqual(first["sha256"], changed["sha256"])

    def test_hash_source_files_records_missing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "present.py").write_text("x = 1", encoding="utf-8")
            entries = hash_source_files(root, ["present.py", "missing.py"])
        self.assertEqual(entries[0]["path"], "present.py")
        self.assertEqual(entries[0]["sha256"], sha256_bytes(b"x = 1"))
        self.assertNotIn("missing", entries[0])
        self.assertEqual(entries[1]["path"], "missing.py")
        self.assertIsNone(entries[1]["sha256"])
        self.assertTrue(entries[1]["missing"])


class GitStateTests(unittest.TestCase):
    def test_reads_real_repository_state(self):
        state = git_repo_state(REPO_ROOT)
        self.assertTrue(state.available)
        self.assertRegex(state.commit_sha, r"^[0-9a-f]{40}$")
        self.assertTrue(state.branch)
        self.assertIsNotNone(state.dirty)
        self.assertIsInstance(state.status, tuple)

    def test_unavailable_when_git_missing(self):
        with mock.patch(
            "benchmarks.receipt.subprocess.run", side_effect=OSError("no git")
        ):
            state = git_repo_state(REPO_ROOT)
        self.assertFalse(state.available)
        self.assertIsNone(state.commit_sha)
        self.assertEqual(state.to_dict()["status"], [])

    def test_unavailable_outside_a_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = git_repo_state(tmpdir)
        self.assertFalse(state.available)


class SanitizationTests(unittest.TestCase):
    def test_sanitize_command_scrubs_absolute_paths(self):
        argv = [
            os.path.join(os.sep, "opt", "venv", "bin", "python"),
            "-m",
            "benchmarks.benchmark_snapper",
            "--input",
            os.path.join(FAKE_HOME, "Pictures", "source.png"),
            "--receipt",
            os.path.join(FAKE_REPO, "benchmarks", "out.json"),
            "--device",
            "cpu",
        ]
        scrubbed = sanitize_command(argv, repo_root=FAKE_REPO, home=FAKE_HOME)
        self.assertEqual(scrubbed[0], "python")
        self.assertEqual(scrubbed[4], "source.png")
        self.assertEqual(scrubbed[6], "<REPO_ROOT>/benchmarks/out.json")
        self.assertEqual(scrubbed[7:], ("--device", "cpu"))

    def test_sanitize_command_collapses_home_paths_to_basename(self):
        argv = [os.path.join(FAKE_HOME, "venv", "bin", "python")]
        scrubbed = sanitize_command(argv, repo_root=FAKE_REPO, home=FAKE_HOME)
        self.assertEqual(scrubbed[0], "python")

    def test_sanitize_text_scrubs_home_repo_and_other_users(self):
        text = (
            f"error in {FAKE_HOME}/src"
            f" under {FAKE_REPO}/x"
            r" at C:\Users\bob\cache"
        )
        result = sanitize_text(text, repo_root=FAKE_REPO, home=FAKE_HOME)
        self.assertIn("<HOME>/src", result)
        self.assertIn("<REPO_ROOT>/x", result)
        self.assertIn(r"<USERS_DIR>\cache", result)
        self.assertNotIn("alice", result)
        self.assertNotIn("bob", result)


class FailureRecordTests(unittest.TestCase):
    def test_format_failure_sanitizes_paths(self):
        try:
            raise RuntimeError(f"boom in {FAKE_HOME}/src")
        except RuntimeError as exception:
            record = format_failure(exception, repo_root=FAKE_REPO, home=FAKE_HOME)
        self.assertEqual(record["exception_type"], "RuntimeError")
        self.assertIn("<HOME>/src", record["message"])
        self.assertIn("Traceback", record["traceback"])

    def test_format_failure_can_keep_raw_text(self):
        try:
            raise ValueError("raw message")
        except ValueError as exception:
            record = format_failure(exception, sanitize=False)
        self.assertEqual(record["message"], "raw message")
        self.assertIn("raw message", record["traceback"])


class ReceiptDocumentTests(unittest.TestCase):
    def test_build_receipt_ok_status(self):
        receipt = build_receipt(**make_parts())
        self.assertEqual(receipt["format"], RECEIPT_FORMAT)
        self.assertEqual(receipt["schema_version"], RECEIPT_SCHEMA_VERSION)
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["failures"], [])
        validate_receipt(receipt)

    def test_build_receipt_error_status_from_failures(self):
        receipt = build_receipt(
            **make_parts(
                failures=[
                    {
                        "exception_type": "RuntimeError",
                        "message": "boom",
                        "run_index": 0,
                        "phase": "measure",
                    }
                ]
            )
        )
        self.assertEqual(receipt["status"], "error")
        self.assertEqual(len(receipt["failures"]), 1)

    def test_validate_receipt_rejects_malformed_documents(self):
        valid = build_receipt(**make_parts())
        validate_receipt(valid)
        for key in ("format", "status", "timing"):
            broken = dict(valid)
            del broken[key]
            with self.assertRaises(ReceiptError):
                validate_receipt(broken)
        wrong_format = dict(valid)
        wrong_format["format"] = "other"
        with self.assertRaises(ReceiptError):
            validate_receipt(wrong_format)
        wrong_version = dict(valid)
        wrong_version["schema_version"] = 99
        with self.assertRaises(ReceiptError):
            validate_receipt(wrong_version)
        wrong_status = dict(valid)
        wrong_status["status"] = "pending"
        with self.assertRaises(ReceiptError):
            validate_receipt(wrong_status)
        broken_timing = build_receipt(**make_parts())
        del broken_timing["timing"]["samples_seconds"]
        with self.assertRaises(ReceiptError):
            validate_receipt(broken_timing)

    def test_same_input_produces_stable_document_and_json(self):
        first = build_receipt(**make_parts())
        second = build_receipt(**make_parts())
        self.assertEqual(first, second)
        self.assertEqual(receipt_dumps(first), receipt_dumps(second))
        round_trip = json.loads(receipt_dumps(first))
        self.assertEqual(round_trip, first)
        validate_receipt(round_trip)

    def test_write_receipt_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "receipt.json"
            write_receipt(build_receipt(**make_parts()), path)
            self.assertTrue(path.is_file())
            validate_receipt(json.loads(path.read_text(encoding="utf-8")))


class MeasureBenchmarkTests(unittest.TestCase):
    def test_sync_boundaries_and_samples_with_fake_clock(self):
        sync_calls = []
        clock = _FakeClock(delta=1)

        def sync():
            sync_calls.append(len(sync_calls))

        def fn():
            return []

        samples, failures, peak = benchmark_snapper.measure_benchmark(
            fn,
            warmup_runs=1,
            runs=3,
            device=torch.device("cpu"),
            clock=clock,
            sync=sync,
        )
        self.assertEqual(samples, [1.0, 1.0, 1.0])
        self.assertEqual(failures, [])
        self.assertIsNone(peak)
        # One sync before and one after every warm-up and measured run.
        self.assertEqual(len(sync_calls), 2 * (1 + 3))

    def test_measured_run_failure_records_partial_samples(self):
        calls = {"count": 0}

        def fn():
            calls["count"] += 1
            if calls["count"] == 3:
                raise RuntimeError("boom")
            return []

        samples, failures, _peak = benchmark_snapper.measure_benchmark(
            fn,
            warmup_runs=1,
            runs=3,
            device=torch.device("cpu"),
        )
        self.assertEqual(len(samples), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["phase"], "measure")
        self.assertEqual(failures[0]["run_index"], 1)
        self.assertEqual(failures[0]["exception_type"], "RuntimeError")
        self.assertEqual(failures[0]["message"], "boom")

    def test_warmup_failure_records_no_samples(self):
        def fn():
            raise ValueError("warmup failed")

        samples, failures, _peak = benchmark_snapper.measure_benchmark(
            fn,
            warmup_runs=2,
            runs=3,
            device=torch.device("cpu"),
        )
        self.assertEqual(samples, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["phase"], "warmup")
        self.assertEqual(failures[0]["run_index"], 0)


class _FakeClock:
    def __init__(self, delta: int):
        self.current = 100
        self.delta = delta

    def __call__(self) -> float:
        self.current += self.delta
        return float(self.current)


class CliSmokeTests(unittest.TestCase):
    """End-to-end CPU runs of the benchmark CLI (no GPU required)."""

    SMALL_ARGS = [
        "--device",
        "cpu",
        "--synthetic-size",
        "8",
        "--colors",
        "4",
        "--pixel-size",
        "1",
        "--iterations",
        "3",
        "--warmup",
        "1",
        "--runs",
        "2",
    ]

    def run_cli(self, *extra: str) -> tuple[int, str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = benchmark_snapper.main([*self.SMALL_ARGS, *extra])
        return code, stdout.getvalue()

    @staticmethod
    def extract_json(output: str) -> dict:
        lines = output.splitlines()
        start = next(
            index for index, line in enumerate(lines) if line.strip().startswith("{")
        )
        return json.loads("\n".join(lines[start:]))

    def test_cpu_small_image_produces_ok_receipt(self):
        code, output = self.run_cli("--json")
        self.assertEqual(code, 0)
        receipt = self.extract_json(output)
        validate_receipt(receipt)
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["timing"]["warmup_runs"], 1)
        self.assertEqual(receipt["timing"]["runs"], 2)
        samples = receipt["timing"]["samples_seconds"]
        self.assertEqual(len(samples), 2)
        stats = receipt["timing"]["stats"]
        self.assertEqual(stats["median_seconds"], statistics.median(samples))
        self.assertEqual(stats["p90_seconds"], max(samples))
        self.assertTrue(receipt["sanitized"])
        self.assertIsNone(receipt["environment"]["working_dir"])
        self.assertIsNone(receipt["environment"]["gpu"])
        self.assertFalse(receipt["environment"]["cuda_available"])
        self.assertEqual(receipt["environment"]["device"]["type"], "cpu")
        self.assertEqual(receipt["inputs"][0]["shape"], [1, 8, 8, 3])
        self.assertEqual(receipt["inputs"][0]["source"], "synthetic")
        self.assertEqual(len(receipt["outputs"]), 1)
        self.assertTrue(receipt["git"]["available"])
        self.assertEqual(
            {entry["role"] for entry in receipt["sources"]}, {"core", "tooling"}
        )
        self.assertTrue(receipt["timing"]["include_host_to_device"])
        self.assertEqual(
            receipt["timing"]["synchronize"],
            {"before_each_run": True, "after_each_run": True},
        )
        self.assertIn("--synthetic-size", receipt["command"])
        self.assertIn("8", receipt["command"])

    def test_receipt_file_is_written_and_hashes_are_stable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "receipts" / "run.json"
            code, _output = self.run_cli("--receipt", str(path))
            self.assertEqual(code, 0)
            self.assertTrue(path.is_file())
            first = json.loads(path.read_text(encoding="utf-8"))

            _code, second_output = self.run_cli("--json")
            second = self.extract_json(second_output)

        self.assertEqual(first["inputs"][0]["sha256"], second["inputs"][0]["sha256"])
        self.assertEqual(first["outputs"][0]["sha256"], second["outputs"][0]["sha256"])
        self.assertEqual(first["sources"], second["sources"])
        self.assertEqual(
            first["timing"]["stats"],
            compute_sample_stats(first["timing"]["samples_seconds"]).to_dict(),
        )

    def test_no_sanitize_records_working_directory(self):
        code, output = self.run_cli("--no-sanitize", "--json")
        self.assertEqual(code, 0)
        receipt = self.extract_json(output)
        self.assertFalse(receipt["sanitized"])
        self.assertEqual(receipt["environment"]["working_dir"], str(Path.cwd()))


if __name__ == "__main__":
    unittest.main()
