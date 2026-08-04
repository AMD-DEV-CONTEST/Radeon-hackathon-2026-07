from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.benchmark_agent import (  # noqa: E402
    model_request_configuration as benchmark_request_configuration,
)
from evaluation.benchmark_agent import (  # noqa: E402
    validate_request_configuration_evidence as validate_benchmark_configuration,
)
from evaluation.compare_benchmarks import (  # noqa: E402
    build_comparison,
    comparison_exit_code,
    runtime_gpu_summary,
)
from evaluation.run_agent_eval import _case_score  # noqa: E402
from evaluation.run_agent_eval import (  # noqa: E402
    model_request_configuration as quality_request_configuration,
)
from evaluation.run_agent_eval import (  # noqa: E402
    validate_request_configuration_evidence as validate_quality_configuration,
)


def _comparison_fixture(
    run_id: str,
    *,
    latency_ms: float = 100.0,
    throughput: float = 10.0,
    token_rate: float = 100.0,
    quality_score: float = 300.0,
    citation_hit_rate: float = 1.0,
    thinking_enabled: bool = False,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "model_name": "local-model",
        "model_base_url": "http://127.0.0.1:8000/v1",
        "cases_path": "evaluation/fixtures/benchmark-cases.jsonl",
        "policy_corpus_sha256": "a" * 64,
        "suite_version": "suite",
        "suite_sha256": "b" * 64,
        "case_ids": ["KQ-001"],
        "request_case_ids": ["KQ-001"],
        "request_configuration": {
            "thinking_enabled": thinking_enabled,
            "schema_constrained": True,
        },
        "configuration": {"workload": "fixed"},
        "provenance": {
            "commit": "c" * 40,
            "project_tree": "d" * 40,
            "source_tree_sha256": "e" * 64,
        },
        "artifacts": {
            "model_file_sha256": "f" * 64,
            "llama_server_sha256": "1" * 64,
        },
        "quality_report": {
            "sha256": "2" * 64,
            "total_score": quality_score,
        },
        "quality_gate": {
            "thresholds": {
                "min_success_rate": 1.0,
                "min_citation_hit_rate": 0.95,
            }
        },
        "runs": [
            {
                "concurrency": 1,
                "requests": [{"case_id": "KQ-001"}],
                "summary": {
                    "success_rate": 1.0,
                    "citation_hit_rate": citation_hit_rate,
                    "latency_ms": {"p50": latency_ms, "p95": latency_ms},
                    "successful_throughput_requests_per_second": throughput,
                    "model_call_metrics": {
                        "successful_calls": 1,
                        "effective_rate_sample_count": 1,
                        "effective_output_tokens_per_second_p50": token_rate,
                        "effective_output_tokens_per_second_p95": token_rate,
                        "server_decode_rate_sample_count": 0,
                        "server_decode_tokens_per_second_p50": None,
                        "server_decode_tokens_per_second_p95": None,
                        "ttft_sample_count": 0,
                        "ttft_ms_p50": None,
                        "ttft_ms_p95": None,
                    },
                },
            }
        ],
    }


class RequestConfigurationEvidenceTests(unittest.TestCase):
    def test_quality_and_benchmark_record_dynamic_thinking_and_schema(self) -> None:
        settings = type("SettingsStub", (), {"model_enable_thinking": True})()

        expected = {"thinking_enabled": True, "schema_constrained": True}
        self.assertEqual(quality_request_configuration(settings), expected)
        self.assertEqual(benchmark_request_configuration(settings), expected)

    def test_evaluators_require_explicit_schema_constrained_trace_field(self) -> None:
        expected = {"thinking_enabled": True, "schema_constrained": True}
        model_call = {
            "thinking_enabled": True,
            "response_format": "json_schema",
        }
        benchmark_runs = [{"requests": [{"model_calls": [model_call]}]}]
        quality_rows = [
            {"trace": [{"response": {"model_calls": [model_call]}}]}
        ]

        with self.assertRaisesRegex(RuntimeError, "missing schema_constrained"):
            validate_benchmark_configuration(benchmark_runs, expected)
        with self.assertRaisesRegex(RuntimeError, "missing schema_constrained"):
            validate_quality_configuration(quality_rows, expected)

    def test_evaluators_record_direct_schema_trace_evidence(self) -> None:
        expected = {"thinking_enabled": False, "schema_constrained": True}
        model_call = {
            **expected,
            "response_format": "json_schema",
        }

        benchmark_evidence = validate_benchmark_configuration(
            [{"requests": [{"model_calls": [model_call]}]}],
            expected,
        )
        quality_evidence = validate_quality_configuration(
            [{"trace": [{"response": {"model_calls": [model_call]}}]}],
            expected,
        )

        self.assertTrue(benchmark_evidence["schema_constrained"])
        self.assertTrue(quality_evidence["schema_constrained"])


class OptimizationAcceptanceTests(unittest.TestCase):
    def test_accepts_material_core_improvement_with_thinking_ab(self) -> None:
        baseline = _comparison_fixture("baseline", thinking_enabled=False)
        optimized = _comparison_fixture(
            "optimized",
            latency_ms=90.0,
            thinking_enabled=True,
        )

        report = build_comparison(
            baseline,
            optimized,
            material_threshold_percent=5.0,
        )

        assessment = report["assessment"]
        self.assertTrue(assessment["accepted"])
        self.assertEqual(assessment["optimization_winner"], "optimized")
        self.assertEqual(assessment["rejection_reasons"], [])

    def test_rejects_material_regression_even_with_core_improvement(self) -> None:
        baseline = _comparison_fixture("baseline")
        optimized = _comparison_fixture(
            "optimized",
            latency_ms=90.0,
            token_rate=90.0,
        )

        report = build_comparison(
            baseline,
            optimized,
            material_threshold_percent=5.0,
        )

        assessment = report["assessment"]
        self.assertFalse(assessment["accepted"])
        self.assertEqual(assessment["optimization_winner"], "not_accepted")
        self.assertIn(
            "core_material_regression_observed",
            assessment["rejection_reasons"],
        )

    def test_optional_timing_regression_does_not_reject_core_improvement(self) -> None:
        baseline = _comparison_fixture("baseline")
        optimized = _comparison_fixture("optimized", latency_ms=90.0)
        for report, decode_rate in ((baseline, 100.0), (optimized, 90.0)):
            model_metrics = report["runs"][0]["summary"]["model_call_metrics"]
            model_metrics.update(
                {
                    "server_decode_rate_sample_count": 1,
                    "server_decode_tokens_per_second_p50": decode_rate,
                    "server_decode_tokens_per_second_p95": decode_rate,
                }
            )

        report = build_comparison(
            baseline,
            optimized,
            material_threshold_percent=5.0,
        )

        assessment = report["assessment"]
        self.assertTrue(assessment["accepted"])
        self.assertEqual(assessment["materially_regressed_core_metrics"], [])
        self.assertIn(
            "c1.server_decode_tokens_per_second_p50",
            assessment["materially_regressed_metrics"],
        )

    def test_material_threshold_is_inclusive_at_positive_five_percent(self) -> None:
        report = build_comparison(
            _comparison_fixture("baseline"),
            _comparison_fixture("optimized", latency_ms=95.0),
            material_threshold_percent=5.0,
        )

        self.assertTrue(report["assessment"]["accepted"])

    def test_material_threshold_is_inclusive_at_negative_five_percent(self) -> None:
        report = build_comparison(
            _comparison_fixture("baseline"),
            _comparison_fixture(
                "optimized",
                latency_ms=95.0,
                token_rate=95.0,
            ),
            material_threshold_percent=5.0,
        )

        assessment = report["assessment"]
        self.assertFalse(assessment["accepted"])
        self.assertIn(
            "core_material_regression_observed",
            assessment["rejection_reasons"],
        )

    def test_quality_regression_writes_negative_assessment(self) -> None:
        baseline = _comparison_fixture("baseline")
        optimized = _comparison_fixture(
            "optimized",
            latency_ms=90.0,
            quality_score=299.0,
        )

        report = build_comparison(
            baseline,
            optimized,
            material_threshold_percent=5.0,
        )

        assessment = report["assessment"]
        self.assertFalse(assessment["accepted"])
        self.assertIn("quality_regression_observed", assessment["rejection_reasons"])
        self.assertEqual(
            assessment["quality_regressions"][0]["metric"],
            "quality_report.total_score",
        )

    def test_require_accepted_controls_exit_status(self) -> None:
        negative_report = build_comparison(
            _comparison_fixture("baseline"),
            _comparison_fixture("optimized"),
            material_threshold_percent=5.0,
        )
        accepted_report = build_comparison(
            _comparison_fixture("baseline"),
            _comparison_fixture("optimized", latency_ms=90.0),
            material_threshold_percent=5.0,
        )

        self.assertEqual(
            comparison_exit_code(negative_report, require_accepted=False), 0
        )
        self.assertEqual(
            comparison_exit_code(negative_report, require_accepted=True), 1
        )
        self.assertEqual(
            comparison_exit_code(accepted_report, require_accepted=True), 0
        )


class RuntimeGpuEvidenceTests(unittest.TestCase):
    def test_accepts_rocm_offload_and_positive_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            server.write_text(
                "ggml_cuda_init: found 1 ROCm device gfx1100\n"
                "load_tensors: offloaded 41/41 layers to GPU\n",
                encoding="utf-8",
            )
            monitor.write_text(
                "GPU[0] : GPU use (%): 87\n"
                "GPU[0] : VRAM Total Used Memory (B): 123456789\n",
                encoding="utf-8",
            )

            summary = runtime_gpu_summary(server, monitor, "test")

            self.assertEqual(summary["peak_gpu_use_percent"], 87.0)
            self.assertEqual(summary["peak_vram_used_reported"], 123456789.0)

    def test_rejects_cpu_only_or_idle_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            server.write_text("server started on CPU\n", encoding="utf-8")
            monitor.write_text(
                "GPU[0] : GPU use (%): 0\n"
                "GPU[0] : VRAM Total Used Memory (B): 0\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "ROCm/HIP"):
                runtime_gpu_summary(server, monitor, "test")

    def test_rejects_wrapper_claim_and_ambiguous_failed_offload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            monitor.write_text(
                "GPU[0] : GPU use (%): 87\n"
                "GPU[0] : VRAM Total Used Memory (B): 123456789\n",
                encoding="utf-8",
            )
            server.write_text(
                "Starting local ROCm model demo on 127.0.0.1:8000\n"
                "failed to offload 0 layers to GPU 1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "backend marker"):
                runtime_gpu_summary(server, monitor, "test")

            server.write_text(
                "ggml_cuda_init: found 1 ROCm device gfx1100\n"
                "failed to offload 0 layers to GPU 1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "GPU-offloaded"):
                runtime_gpu_summary(server, monitor, "test")

            server.write_text(
                "model_path=/models/ggml_cuda_init: ROCm.gguf\n"
                "note=load_tensors: offloaded 41/41 layers to GPU\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "backend marker"):
                runtime_gpu_summary(server, monitor, "test")

    def test_requires_positive_telemetry_inside_each_evaluation_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            server.write_text(
                "ggml_cuda_init: found 1 ROCm device gfx1100\n"
                "load_tensors: offloaded 41/41 layers to GPU\n",
                encoding="utf-8",
            )
            monitor.write_text(
                "sample=1 run_id=run-1 collected_at_utc=2030-01-01T00:00:00Z\n"
                "GPU[0] : GPU use (%): 87\n"
                "GPU[0] : VRAM Total Used Memory (B): 123456789\n"
                "sample=2 run_id=run-1 collected_at_utc=2030-01-01T00:00:10Z\n"
                "GPU[0] : GPU use (%): 0\n"
                "GPU[0] : VRAM Total Used Memory (B): 0\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "agent_quality window"):
                runtime_gpu_summary(
                    server,
                    monitor,
                    "test",
                    required_windows={
                        "agent_quality": (
                            datetime(2030, 1, 1, 0, 0, 9, tzinfo=UTC),
                            datetime(2030, 1, 1, 0, 0, 11, tzinfo=UTC),
                        )
                    },
                )

    def test_requires_one_gpu_index_across_quality_and_benchmark_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            server.write_text(
                "ggml_cuda_init: found 2 ROCm devices\n"
                "llm_load_tensors: offloaded 41/41 layers to GPU\n",
                encoding="utf-8",
            )
            monitor.write_text(
                "sample=1 run_id=run-1 collected_at_utc=2030-01-01T00:00:01Z\n"
                "GPU[0] : GPU use (%): 87\n"
                "GPU[0] : VRAM Total Used Memory (B): 123456789\n"
                "GPU[1] : GPU use (%): 0\n"
                "GPU[1] : VRAM Total Used Memory (B): 0\n"
                "sample=2 run_id=run-1 collected_at_utc=2030-01-01T00:00:11Z\n"
                "GPU[0] : GPU use (%): 0\n"
                "GPU[0] : VRAM Total Used Memory (B): 0\n"
                "GPU[1] : GPU use (%): 91\n"
                "GPU[1] : VRAM Total Used Memory (B): 223456789\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "share an active GPU index"):
                runtime_gpu_summary(
                    server,
                    monitor,
                    "test",
                    required_windows={
                        "agent_quality": (
                            datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC),
                            datetime(2030, 1, 1, 0, 0, 2, tzinfo=UTC),
                        ),
                        "agent_benchmark": (
                            datetime(2030, 1, 1, 0, 0, 10, tzinfo=UTC),
                            datetime(2030, 1, 1, 0, 0, 12, tzinfo=UTC),
                        ),
                    },
                )

    def test_binds_active_windows_to_one_physical_gpu_unique_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            server.write_text(
                "ggml_cuda_init: found 1 ROCm device gfx1100\n"
                "load_tensors: offloaded 41/41 layers to GPU\n",
                encoding="utf-8",
            )
            monitor.write_text(
                "device_identity_begin\n"
                "================ Unique ID ================\n"
                "GPU[0] : Unique ID: 0xabc123\n"
                "device_identity_end\n"
                "sample=1 run_id=run-1 collected_at_utc=2030-01-01T00:00:01Z\n"
                "GPU[0] : GPU use (%): 87\n"
                "GPU[0] : VRAM Total Used Memory (B): 123456789\n"
                "sample=2 run_id=run-1 collected_at_utc=2030-01-01T00:00:11Z\n"
                "GPU[0] : GPU use (%): 91\n"
                "GPU[0] : VRAM Total Used Memory (B): 223456789\n",
                encoding="utf-8",
            )

            summary = runtime_gpu_summary(
                server,
                monitor,
                "test",
                required_windows={
                    "agent_quality": (
                        datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC),
                        datetime(2030, 1, 1, 0, 0, 2, tzinfo=UTC),
                    ),
                    "agent_benchmark": (
                        datetime(2030, 1, 1, 0, 0, 10, tzinfo=UTC),
                        datetime(2030, 1, 1, 0, 0, 12, tzinfo=UTC),
                    ),
                },
                require_device_identity=True,
            )

            self.assertEqual(summary["common_active_gpu_indices"], [0])
            self.assertEqual(summary["common_active_gpu_unique_ids"], ["0xabc123"])

    def test_rejects_one_boundary_sample_reused_for_two_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            server.write_text(
                "ggml_cuda_init: found 1 ROCm device gfx1100\n"
                "load_tensors: offloaded 41/41 layers to GPU\n",
                encoding="utf-8",
            )
            monitor.write_text(
                "sample=1 run_id=run-1 collected_at_utc=2030-01-01T00:00:05Z\n"
                "GPU[0] : GPU use (%): 87\n"
                "GPU[0] : VRAM Total Used Memory (B): 123456789\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "distinct active telemetry samples"):
                runtime_gpu_summary(
                    server,
                    monitor,
                    "test",
                    required_windows={
                        "agent_quality": (
                            datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC),
                            datetime(2030, 1, 1, 0, 0, 5, tzinfo=UTC),
                        ),
                        "agent_benchmark": (
                            datetime(2030, 1, 1, 0, 0, 5, tzinfo=UTC),
                            datetime(2030, 1, 1, 0, 0, 10, tzinfo=UTC),
                        ),
                    },
                )

    def test_requires_distinct_window_samples_on_the_shared_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            server.write_text(
                "ggml_cuda_init: found 3 ROCm devices\n"
                "load_tensors: offloaded 41/41 layers to GPU\n",
                encoding="utf-8",
            )
            monitor.write_text(
                "sample=1 run_id=run-1 collected_at_utc=2030-01-01T00:00:01Z\n"
                "GPU[1] : GPU use (%): 87\n"
                "GPU[1] : VRAM Total Used Memory (B): 123456789\n"
                "sample=2 run_id=run-1 collected_at_utc=2030-01-01T00:00:05Z\n"
                "GPU[0] : GPU use (%): 88\n"
                "GPU[0] : VRAM Total Used Memory (B): 223456789\n"
                "sample=3 run_id=run-1 collected_at_utc=2030-01-01T00:00:09Z\n"
                "GPU[2] : GPU use (%): 89\n"
                "GPU[2] : VRAM Total Used Memory (B): 323456789\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "distinct active telemetry"):
                runtime_gpu_summary(
                    server,
                    monitor,
                    "test",
                    required_windows={
                        "agent_quality": (
                            datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC),
                            datetime(2030, 1, 1, 0, 0, 5, tzinfo=UTC),
                        ),
                        "agent_benchmark": (
                            datetime(2030, 1, 1, 0, 0, 5, tzinfo=UTC),
                            datetime(2030, 1, 1, 0, 0, 10, tzinfo=UTC),
                        ),
                    },
                )

    def test_rejects_invalid_rocm_unique_id_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            server.write_text(
                "ggml_cuda_init: found 1 ROCm device gfx1100\n"
                "load_tensors: offloaded 41/41 layers to GPU\n",
                encoding="utf-8",
            )
            for invalid_row in (
                "GPU[0] : Unable to get Unique ID",
                "GPU[0] : Unique ID: unavailable",
                "GPU[0] : Unique ID: 0x0",
            ):
                with self.subTest(invalid_row=invalid_row):
                    monitor.write_text(
                        "device_identity_begin\n"
                        f"{invalid_row}\n"
                        "device_identity_end\n"
                        "sample=1 run_id=run-1 collected_at_utc=2030-01-01T00:00:01Z\n"
                        "GPU[0] : GPU use (%): 87\n"
                        "GPU[0] : VRAM Total Used Memory (B): 123456789\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        ValueError,
                        "invalid Radeon GPU unique ID",
                    ):
                        runtime_gpu_summary(
                            server,
                            monitor,
                            "test",
                            required_windows={
                                "agent_quality": (
                                    datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC),
                                    datetime(2030, 1, 1, 0, 0, 2, tzinfo=UTC),
                                )
                            },
                            require_device_identity=True,
                        )

    def test_ignores_invalid_unique_id_for_an_inactive_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            server.write_text(
                "ggml_cuda_init: found 2 ROCm devices\n"
                "load_tensors: offloaded 41/41 layers to GPU\n",
                encoding="utf-8",
            )
            monitor.write_text(
                "device_identity_begin\n"
                "GPU[0] : Unique ID: 0xabc123\n"
                "GPU[1] : Unique ID: N/A\n"
                "device_identity_end\n"
                "sample=1 run_id=run-1 collected_at_utc=2030-01-01T00:00:01Z\n"
                "GPU[0] : GPU use (%): 87\n"
                "GPU[0] : VRAM Total Used Memory (B): 123456789\n"
                "sample=2 run_id=run-1 collected_at_utc=2030-01-01T00:00:11Z\n"
                "GPU[0] : GPU use (%): 91\n"
                "GPU[0] : VRAM Total Used Memory (B): 223456789\n",
                encoding="utf-8",
            )

            summary = runtime_gpu_summary(
                server,
                monitor,
                "test",
                required_windows={
                    "agent_quality": (
                        datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC),
                        datetime(2030, 1, 1, 0, 0, 2, tzinfo=UTC),
                    ),
                    "agent_benchmark": (
                        datetime(2030, 1, 1, 0, 0, 10, tzinfo=UTC),
                        datetime(2030, 1, 1, 0, 0, 12, tzinfo=UTC),
                    ),
                },
                require_device_identity=True,
            )

            self.assertEqual(
                summary["common_active_gpu_unique_ids"],
                ["0xabc123"],
            )
            self.assertEqual(summary["invalid_device_identity_indices"], [1])

    def test_requires_unique_id_for_official_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.log"
            monitor = root / "monitor.log"
            server.write_text(
                "ggml_cuda_init: found 1 ROCm device gfx1100\n"
                "load_tensors: offloaded 41/41 layers to GPU\n",
                encoding="utf-8",
            )
            monitor.write_text(
                "GPU[0] : GPU use (%): 87\n"
                "GPU[0] : VRAM Total Used Memory (B): 123456789\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unique-ID evidence"):
                runtime_gpu_summary(
                    server,
                    monitor,
                    "test",
                    require_device_identity=True,
                )


class AgentEvaluatorOrderTests(unittest.TestCase):
    def test_rejects_reversed_successful_tool_execution(self) -> None:
        score = _case_score(
            {
                "expected": {
                    "decision": "execute_read",
                    "ordered_tools": [
                        "hotel.check_availability",
                        "hotel.quote_stay",
                    ],
                }
            },
            responses=[
                {
                    "answer": "",
                    "citations": [],
                    "pending_actions": [],
                    "receipts": [{"status": "ok"}],
                }
            ],
            plans=[
                {
                    "steps": [
                        {
                            "step_id": "availability",
                            "tool": "hotel.check_availability",
                            "arguments": {},
                            "depends_on": [],
                        },
                        {
                            "step_id": "quote",
                            "tool": "hotel.quote_stay",
                            "arguments": {},
                            "depends_on": [],
                        },
                    ]
                }
            ],
            tool_calls=[
                {
                    "source": "agent",
                    "tool": "hotel.check_availability",
                    "arguments": {},
                    "status": "error",
                },
                {
                    "source": "agent",
                    "tool": "hotel.check_availability",
                    "arguments": {},
                    "status": "pending_confirmation",
                },
                {
                    "source": "agent",
                    "tool": "hotel.quote_stay",
                    "arguments": {},
                    "status": "ok",
                },
                {
                    "source": "agent",
                    "tool": "hotel.check_availability",
                    "arguments": {},
                    "status": "ok",
                },
            ],
            errors=[],
            confirmations=[],
            snapshot_before={},
            snapshot_final={},
            unconfirmed_mutation=False,
            policy_evidence=set(),
        )

        self.assertFalse(score["checks"]["actual_order"])
        self.assertFalse(score["criteria"]["order_and_confirmation"])
        self.assertIn("tool_order_violation", score["hard_failures"])
        self.assertEqual(score["score"], 0)


if __name__ == "__main__":
    unittest.main()
