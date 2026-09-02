"""
Cross-language repair factory interface.

Every language backend implements this protocol. The pipeline contract is:

    find project
    → understand project (detect_project)
    → prove project works (baseline)
    → break it in a controlled way (inject_failure)
    → repair it (repair)
    → verify the repair (verify)
    → sign the trace (write_corpus)
    → train/compress/reroute from the trace

Language expansion is factory work, not invention.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectProfile:
    language: str
    root: Path
    build_system: str  # "cargo", "maven", "go_modules", "cmake", etc.
    license_spdx: str
    license_bucket: str  # "green" | "yellow" | "red" | "unknown"
    has_build_script: bool  # build.rs, build.py, CMakeLists.txt, etc.
    has_unsafe_patterns: bool  # injection / supply chain flags
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ingest_allowed(self) -> bool:
        return self.license_bucket == "green" and not self.has_unsafe_patterns


@dataclass
class BaselineResult:
    passed: bool
    command: str
    output: str
    duration_ms: int = 0


@dataclass
class RepairTask:
    task_id: str
    language: str
    build_system: str
    mutation_type: str
    failure_type: str
    failure_output: str
    source_file: str = ""
    original_snippet: str = ""
    mutated_snippet: str = ""

    def to_corpus_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class MutationResult:
    succeeded: bool  # True if mutation caused a verifiable failure
    failure_output: str
    mutation_type: str
    mutated_file: str = ""


@dataclass
class RepairResult:
    patch: str
    repair_command: str
    repaired_content: str = ""


@dataclass
class OracleVerdict:
    passed: bool
    command: str
    output: str


@dataclass
class CorpusRecord:
    task_id: str
    language: str
    signed: bool
    record: dict[str, Any]


class LanguageRepairBackend(ABC):
    """
    Abstract base for all language repair pipelines.

    Implementors:
      - RustRepairPipeline (cargo)
      - JavaRepairPipeline (maven/gradle) — predates this interface
      - PythonRepairPipeline (pytest)
      - GoRepairPipeline (go test)
      - CRepairPipeline (make/cmake)
      - TypeScriptRepairPipeline (npm/tsc)
    """

    language: str

    @abstractmethod
    def detect_project(self, path: Path) -> ProjectProfile | None:
        """
        Identify whether path contains a project in this language.
        Returns None if the path is not a recognizable project.
        """

    @abstractmethod
    def baseline(self, project: ProjectProfile) -> BaselineResult:
        """
        Run the project's test suite without any mutation.
        The pipeline must refuse to proceed if baseline fails.
        """

    @abstractmethod
    def extract_tasks(self, project: ProjectProfile) -> list[RepairTask]:
        """
        Produce repair tasks from the project by applying mutations,
        confirming each mutation causes a test failure, and recording the trace.
        Only called after baseline passes.
        """

    @abstractmethod
    def inject_failure(self, task: RepairTask) -> MutationResult:
        """
        Apply the mutation recorded in the task and confirm the failure
        is reproducible. Used to re-verify tasks in isolation.
        """

    @abstractmethod
    def repair(self, task: RepairTask, failure: MutationResult) -> RepairResult:
        """
        Produce a repair patch for the given task and failure.
        May invoke a model, a deterministic fixer, or a lookup.
        """

    @abstractmethod
    def verify(self, repair: RepairResult, project: ProjectProfile) -> OracleVerdict:
        """
        Apply the repair and run the oracle. Returns OracleVerdict.
        The oracle is always the language's native compiler/test runner.
        """

    @abstractmethod
    def write_corpus(self, task: RepairTask, verdict: OracleVerdict) -> CorpusRecord:
        """
        Sign and write a corpus record for this (task, verdict) pair.
        Must use HMAC-signed records. Must not write unsigned rows.
        """
