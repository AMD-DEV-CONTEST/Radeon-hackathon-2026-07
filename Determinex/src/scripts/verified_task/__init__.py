"""Universal verified task harness.

Adapters translate benchmarks into TaskSpec. The runner executes validators,
records verdict-rich traces, and keeps large working state on the configured
T: staging root by default.
"""

from .bench_to_corpus_eligibility import (
    TRAINING_ELIGIBLE_STATUS,
    complete_benchmark_payload,
    missing_training_fields,
    signed_training_eligible,
)
from .benchmark_trace_contract import (
    BenchmarkTrace,
    BenchmarkTraceAdapter,
    GenericBenchmarkTraceAdapter,
)
from .command_runner import CommandResult, CommandRunner
from .corpus_writer import CorpusWriter
from .retry_loop import AttemptRecord, RetryLoop, RetryLoopResult
from .storage import StorageEntry
from .task_spec import ResourceLimits, TaskSpec
from .workspace_manager import WorkspaceLease, WorkspaceManager

__all__ = [
    "AttemptRecord",
    "BenchmarkTrace",
    "BenchmarkTraceAdapter",
    "CommandResult",
    "CommandRunner",
    "CorpusWriter",
    "GenericBenchmarkTraceAdapter",
    "ResourceLimits",
    "RetryLoop",
    "RetryLoopResult",
    "StorageEntry",
    "TaskSpec",
    "TRAINING_ELIGIBLE_STATUS",
    "WorkspaceLease",
    "WorkspaceManager",
    "complete_benchmark_payload",
    "missing_training_fields",
    "signed_training_eligible",
]
