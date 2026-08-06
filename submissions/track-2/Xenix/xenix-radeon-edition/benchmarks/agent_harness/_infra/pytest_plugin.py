"""Small pytest control surface for explicit real-provider benchmark cells.

Pytest owns collection, selection and item lifecycle.  This module only turns
the selected item's command-line configuration into one case-agnostic runner
invocation; outcome verdicts remain measurements rather than test failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .contracts import BenchmarkCase, BenchmarkExecutionMode, BenchmarkRunStatus
from .runner import DEFAULT_OUTPUT_DIRECTORY, BenchmarkRun, run_benchmark

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.fixtures import FixtureRequest


_LIVE_MARKER = "agent_harness_live: explicit real-provider Agent Harness benchmark case"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("agent-harness benchmark")
    group.addoption(
        "--run-agent-harness",
        action="store_true",
        default=False,
        dest="agent_harness_live",
        help="Allow selected Agent Harness benchmark cases to call configured providers.",
    )
    group.addoption(
        "--headed",
        action="store_true",
        default=False,
        dest="agent_harness_headed",
        help="Drive each selected real-provider case through the visible desktop UI.",
    )
    group.addoption(
        "--llm-settings",
        type=Path,
        dest="agent_harness_llm_settings",
        help=(
            "External subject LLM settings JSON; otherwise "
            "XENIX_AGENT_BENCHMARK_LLM_SETTINGS_PATH."
        ),
    )
    group.addoption(
        "--judge-llm-settings",
        type=Path,
        dest="agent_harness_judge_llm_settings",
        help=(
            "External judge LLM settings JSON; otherwise "
            "XENIX_AGENT_BENCHMARK_JUDGE_LLM_SETTINGS_PATH."
        ),
    )
    group.addoption(
        "--embedding-settings",
        type=Path,
        dest="agent_harness_embedding_settings",
        help=(
            "External subject Embedding settings JSON; otherwise "
            "XENIX_AGENT_BENCHMARK_EMBEDDING_SETTINGS_PATH."
        ),
    )
    group.addoption(
        "--judge-model",
        dest="agent_harness_judge_model",
        help="Optional judge provider/model key from the explicit judge settings.",
    )
    group.addoption(
        "--model",
        action="append",
        default=[],
        dest="agent_harness_models",
        help="Repeat to limit the configured subject provider/model matrix.",
    )
    group.addoption(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        dest="agent_harness_output_directory",
        help="Directory for one privacy-bounded JSON result per completed cell.",
    )
    group.addoption(
        "--source",
        type=Path,
        dest="agent_harness_source",
        help="External source for a case that explicitly requires one.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", _LIVE_MARKER)


@dataclass(frozen=True)
class AgentHarnessBenchmarkController:
    """The deliberately small interface exposed to every benchmark case."""

    config: Config

    def require_source(self) -> Path:
        source = self.config.getoption("agent_harness_source")
        if source is None:
            pytest.skip("this benchmark case requires --source PATH")
        return Path(source)

    def run(self, case: BenchmarkCase) -> tuple[BenchmarkRun, ...]:
        """Run the case matrix and fail only for execution/persistence faults."""

        runs = run_benchmark(
            settings_path=_path_option(self.config, "agent_harness_llm_settings"),
            embedding_settings_path=_path_option(
                self.config,
                "agent_harness_embedding_settings",
            ),
            case=case,
            execution_mode=(
                BenchmarkExecutionMode.HEADED
                if self.config.getoption("agent_harness_headed")
                else BenchmarkExecutionMode.HEADLESS
            ),
            output_directory=Path(
                self.config.getoption("agent_harness_output_directory")
            ),
            requested_models=tuple(self.config.getoption("agent_harness_models")),
            judge_settings_path=_path_option(
                self.config,
                "agent_harness_judge_llm_settings",
            ),
            judge_model_key=self.config.getoption("agent_harness_judge_model"),
        )
        for run in runs:
            self._report(run)

        failure = _infrastructure_failure(runs)
        if failure is not None:
            pytest.fail(failure)
        return runs

    def _report(self, run: BenchmarkRun) -> None:
        result = run.result
        usage = result.subject_metrics.token_usage
        token_total = usage.total_tokens if usage is not None else None
        seconds = result.subject_metrics.turn_seconds
        summary = " ".join(
            (
                "agent-harness-benchmark:",
                f"case={result.case_id}",
                f"model={result.provider_model}",
                f"mode={result.execution_mode.value}",
                f"run={result.run_status.value}",
                f"semantic={result.semantic_verdict.value}",
                f"integrity={result.integrity_passed}",
                f"judge={result.judge.status.value}",
                f"tokens={token_total if token_total is not None else 'unreported'}",
                f"seconds={seconds:.3f}" if seconds is not None else "seconds=unreported",
                f"persisted={run.persisted}",
            )
        )
        terminal_reporter = self.config.pluginmanager.getplugin("terminalreporter")
        if terminal_reporter is not None:
            terminal_reporter.write_line(summary)


@pytest.fixture
def agent_harness_benchmark(request: FixtureRequest) -> AgentHarnessBenchmarkController:
    """Gate paid execution until a caller gives the explicit live switch."""

    config = request.config
    if not config.getoption("agent_harness_live"):
        pytest.skip("pass --run-agent-harness to execute real-provider benchmark cells")
    return AgentHarnessBenchmarkController(config=config)


def _path_option(config: Config, option_name: str) -> Path | None:
    value = config.getoption(option_name)
    return Path(value) if value is not None else None


def _infrastructure_failure(runs: tuple[BenchmarkRun, ...]) -> str | None:
    if not runs:
        return "Agent Harness benchmark produced no measurement cells"
    if any(not run.persisted for run in runs):
        return "Agent Harness benchmark could not persist every measurement"
    failed = [run for run in runs if run.result.run_status is not BenchmarkRunStatus.COMPLETED]
    if failed:
        statuses = ", ".join(
            f"{run.result.provider_model}:{run.result.run_status.value}"
            for run in failed
        )
        return f"Agent Harness benchmark execution failed ({statuses})"
    return None
