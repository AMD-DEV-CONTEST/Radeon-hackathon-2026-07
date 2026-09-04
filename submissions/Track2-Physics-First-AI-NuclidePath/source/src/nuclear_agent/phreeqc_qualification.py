"""Dependency-light, bounded process qualification for a PHREEQC executable.

This module qualifies artifact identity and replayability, not scientific truth.
It deliberately delegates process execution to :mod:`external_adapters`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import secrets
import stat
from types import MappingProxyType
from typing import Mapping

from .external_adapters import ExternalSolverManifest, SolverRunResult, run_replayable
from .replay import ReplayBundle, verify_bundle


class QualificationError(ValueError):
    """A fail-closed qualification contract violation."""


EXAMPLE2_SELECTED_SHA256 = "d83b5148c6350aaac58c18ba5cffa4b8837b0254f7d8cac4a8d45c7681d6cfec"


@dataclass(frozen=True)
class FileSnapshot:
    name: str
    size: int
    sha256: str
    device: int
    inode: int
    link_count: int
    file_type: str = "regular"


@dataclass(frozen=True)
class StableFileRead:
    """An immutable snapshot and the bytes read from its verified descriptor."""

    snapshot: FileSnapshot
    data: bytes


def stable_file_read(path: Path, *, logical_name: str | None = None,
                     max_bytes: int | None = None) -> StableFileRead:
    """Read and hash a stable regular file through one descriptor."""
    path = Path(path)
    try:
        preliminary = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise QualificationError(f"stable file unavailable: {path.name}") from exc
    if not stat.S_ISREG(preliminary.st_mode) or preliminary.st_nlink != 1:
        raise QualificationError(f"stable file must be a single-link regular file: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QualificationError(f"stable file unavailable: {path.name}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise QualificationError(f"stable file must be a single-link regular file: {path.name}")
        if max_bytes is not None and before.st_size > max_bytes:
            raise QualificationError(f"file exceeds size limit: {path.name}")
        digest = hashlib.sha256()
        data = bytearray()
        observed = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            observed += len(chunk)
            if max_bytes is not None and observed > max_bytes:
                raise QualificationError(f"file exceeds size limit: {path.name}")
            digest.update(chunk)
            data.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                              value.st_ctime_ns, value.st_nlink)
    if identity(before) != identity(after) or observed != after.st_size:
        raise QualificationError(f"file changed while hashing: {path.name}")
    try:
        current = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise QualificationError(f"file changed after hashing: {path.name}") from exc
    if not stat.S_ISREG(current.st_mode) or identity(current) != identity(after):
        raise QualificationError(f"file path changed after hashing: {path.name}")
    snapshot = FileSnapshot(logical_name or path.name, observed, digest.hexdigest(), after.st_dev,
                            after.st_ino, after.st_nlink)
    return StableFileRead(snapshot, bytes(data))


def stable_file_snapshot(path: Path, *, logical_name: str | None = None,
                         max_bytes: int | None = None) -> FileSnapshot:
    """Hash a stable regular file without following a final POSIX symlink."""
    return stable_file_read(path, logical_name=logical_name, max_bytes=max_bytes).snapshot


def sha256_file(path: Path) -> str:
    return stable_file_snapshot(path).sha256


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise QualificationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _source_file(value: Path | str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise QualificationError(f"{label} path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise QualificationError(f"{label} must be a regular non-symlink file")
    return path


@dataclass(frozen=True)
class BannerMatcher:
    """An anchored regular expression for one explicit self-reported banner."""

    fullmatch_pattern: str

    def __post_init__(self) -> None:
        if not self.fullmatch_pattern:
            raise QualificationError("banner matcher is required")
        try:
            re.compile(self.fullmatch_pattern)
        except re.error as exc:
            raise QualificationError("invalid banner matcher") from exc

    def verify(self, banner: str) -> str:
        if not banner or re.fullmatch(self.fullmatch_pattern, banner) is None:
            raise QualificationError("self-reported banner does not match")
        return banner


@dataclass(frozen=True)
class QualificationConfig:
    executable: Path
    database: Path
    input_path: Path
    working_directory: Path
    expected_executable_sha256: str
    expected_database_sha256: str
    expected_input_sha256: str
    banner_matcher: BannerMatcher
    timeout_seconds: float = 30.0
    max_stdout_bytes: int = 1024 * 1024
    max_stderr_bytes: int = 1024 * 1024
    allowed_outputs: tuple[str, ...] = ("ex2.sel", "phreeqc.out", "phreeqc.log")
    required_outputs: tuple[str, ...] = ("ex2.sel", "phreeqc.out", "phreeqc.log")
    max_output_files: int = 3
    max_output_file_bytes: int = 16 * 1024 * 1024
    max_output_total_bytes: int = 32 * 1024 * 1024
    expected_selected_output_sha256: str = EXAMPLE2_SELECTED_SHA256

    def __post_init__(self) -> None:
        object.__setattr__(self, "executable", _source_file(self.executable, "executable"))
        object.__setattr__(self, "database", _source_file(self.database, "database"))
        object.__setattr__(self, "input_path", _source_file(self.input_path, "input"))
        root = Path(self.working_directory)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise QualificationError("working directory must be an absolute non-symlink directory")
        object.__setattr__(self, "working_directory", root)
        for field in ("expected_executable_sha256", "expected_database_sha256", "expected_input_sha256"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        timeout = self.timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise QualificationError("timeout must be positive and finite")
        for field in ("max_stdout_bytes", "max_stderr_bytes", "max_output_files",
                      "max_output_file_bytes", "max_output_total_bytes"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise QualificationError(f"{field} must be a positive integer")
        object.__setattr__(self, "allowed_outputs", tuple(self.allowed_outputs))
        object.__setattr__(self, "required_outputs", tuple(self.required_outputs))
        if (len(set(self.allowed_outputs)) != len(self.allowed_outputs)
                or not set(self.required_outputs) <= set(self.allowed_outputs)
                or len(self.allowed_outputs) > self.max_output_files):
            raise QualificationError("invalid produced-output policy")
        object.__setattr__(self, "expected_selected_output_sha256",
                           _digest(self.expected_selected_output_sha256, "expected_selected_output_sha256"))

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "QualificationConfig":
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if set(value) != expected:
            raise QualificationError("configuration fields do not match the strict schema")
        data = dict(value)
        matcher = data["banner_matcher"]
        if isinstance(matcher, str):
            data["banner_matcher"] = BannerMatcher(matcher)
        return cls(**data)

    def normalized(self) -> dict[str, object]:
        return {
            "executable": str(self.executable), "database": str(self.database),
            "input_path": str(self.input_path), "working_directory": str(self.working_directory),
            "expected_executable_sha256": self.expected_executable_sha256,
            "expected_database_sha256": self.expected_database_sha256,
            "expected_input_sha256": self.expected_input_sha256,
            "banner_pattern": self.banner_matcher.fullmatch_pattern,
            "timeout_seconds": self.timeout_seconds,
            "max_stdout_bytes": self.max_stdout_bytes, "max_stderr_bytes": self.max_stderr_bytes,
            "allowed_outputs": list(self.allowed_outputs), "required_outputs": list(self.required_outputs),
            "max_output_files": self.max_output_files,
            "max_output_file_bytes": self.max_output_file_bytes,
            "max_output_total_bytes": self.max_output_total_bytes,
            "expected_selected_output_sha256": self.expected_selected_output_sha256,
        }


@dataclass(frozen=True)
class StagedQualification:
    config: QualificationConfig
    run_directory: Path
    manifest: ExternalSolverManifest
    source_hashes: Mapping[str, str]
    staged_hashes: Mapping[str, str]
    baseline_files: tuple[str, ...]
    run_identity_sha256: str


def _run_identity(manifest: ExternalSolverManifest, source_hashes: Mapping[str, str],
                  staged_hashes: Mapping[str, str], run_identifier: str) -> str:
    payload = {
        "manifest": {
            "executable": str(manifest.executable), "executable_sha256": manifest.executable_sha256,
            "database": str(manifest.database), "database_sha256": manifest.database_sha256,
            "inputs": [[str(path), digest] for path, digest in manifest.input_files],
            "version": manifest.version, "command": list(manifest.command),
            "working_directory": str(manifest.working_directory),
        },
        "source_hashes": dict(sorted(source_hashes.items())),
        "staged_hashes": dict(sorted(staged_hashes.items())),
        "run_identifier": run_identifier,
    }
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def stage_qualification(config: QualificationConfig) -> StagedQualification:
    expected = {
        "executable": config.expected_executable_sha256,
        "database": config.expected_database_sha256,
        "input": config.expected_input_sha256,
    }
    sources = {"executable": config.executable, "database": config.database, "input": config.input_path}
    actual = {name: sha256_file(path) for name, path in sources.items()}
    for name in expected:
        if actual[name] != expected[name]:
            raise QualificationError(f"source {name} SHA-256 mismatch")
    run_directory = config.working_directory / "phreeqc-qualification-run"
    if run_directory.exists() or run_directory.is_symlink():
        raise QualificationError("dedicated run directory already exists")
    run_directory.mkdir(mode=0o700)
    staged = {
        "executable": run_directory / "phreeqc",
        "database": run_directory / "database.dat",
        "input": run_directory / "input.pqi",
    }
    for name, destination in staged.items():
        shutil.copyfile(sources[name], destination, follow_symlinks=False)
    staged["executable"].chmod(config.executable.stat().st_mode & 0o777)
    staged_hashes = {name: sha256_file(path) for name, path in staged.items()}
    if staged_hashes != expected:
        raise QualificationError("staged artifact SHA-256 mismatch")
    command = (str(staged["executable"]), str(staged["input"]), "phreeqc.out", str(staged["database"]), "phreeqc.log")
    manifest = ExternalSolverManifest(
        executable=staged["executable"], executable_sha256=expected["executable"],
        database=staged["database"], database_sha256=expected["database"],
        input_files=((staged["input"], expected["input"]),), version=config.banner_matcher.fullmatch_pattern,
        command=command, working_directory=run_directory,
    )
    baseline = tuple(sorted(path.name for path in run_directory.iterdir()))
    identity = _run_identity(manifest, actual, staged_hashes, secrets.token_hex(16))
    return StagedQualification(config, run_directory, manifest, MappingProxyType(actual),
                               MappingProxyType(staged_hashes), baseline, identity)


@dataclass(frozen=True)
class ProcessQualificationResult:
    process: SolverRunResult
    working_directory: Path
    output_files: Mapping[str, FileSnapshot]
    banner: str
    run_identity_sha256: str
    parsed_selected_output: ParsedSelectedOutput

    @property
    def output_hashes(self) -> Mapping[str, str]:
        return MappingProxyType({name: snapshot.sha256 for name, snapshot in self.output_files.items()})

    def deterministic_payload(self) -> dict[str, object]:
        return {
            "exit_status": self.process.exit_status, "timed_out": self.process.timed_out,
            "stdout": self.process.stdout, "stderr": self.process.stderr,
            "stdout_sha256": self.process.stdout_sha256, "stderr_sha256": self.process.stderr_sha256,
            "stdout_bytes_observed": self.process.stdout_bytes_observed,
            "stderr_bytes_observed": self.process.stderr_bytes_observed,
            "stdout_bytes_retained": self.process.stdout_bytes_retained,
            "stderr_bytes_retained": self.process.stderr_bytes_retained,
            "output_limits_exceeded": list(self.process.output_limits_exceeded),
            "streams_complete": self.process.streams_complete,
            "stream_drain_timed_out": self.process.stream_drain_timed_out,
            "stream_errors": list(self.process.stream_errors),
            "output_files": {name: {"name": snapshot.name, "size": snapshot.size,
                                      "sha256": snapshot.sha256, "file_type": snapshot.file_type}
                             for name, snapshot in sorted(self.output_files.items())},
            "banner": self.banner,
        }


def verify_staged_artifacts(staged: StagedQualification) -> None:
    artifacts = {
        "executable": staged.manifest.executable,
        "database": staged.manifest.database,
        "input": staged.manifest.input_files[0][0],
    }
    expected = dict(staged.staged_hashes)
    if set(artifacts) != set(expected):
        raise QualificationError("staged artifact schema mismatch")
    root = staged.run_directory.resolve()
    for name, path in artifacts.items():
        if path is None or not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise QualificationError(f"staged {name} is unavailable or unsafe")
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise QualificationError(f"staged {name} escapes the run directory") from exc
        if stable_file_snapshot(path, logical_name=name).sha256 != expected[name]:
            raise QualificationError(f"staged {name} SHA-256 changed")


def snapshot_output_files(staged: StagedQualification) -> Mapping[str, FileSnapshot]:
    baseline = set(staged.baseline_files)
    entries = {path.name: path for path in staged.run_directory.iterdir() if path.name not in baseline}
    if set(entries) != set(staged.config.required_outputs) or not set(entries) <= set(staged.config.allowed_outputs):
        raise QualificationError("produced output set does not match the closed policy")
    if len(entries) > staged.config.max_output_files:
        raise QualificationError("too many produced output files")
    snapshots = {}
    total = 0
    for name, path in sorted(entries.items()):
        snapshot = stable_file_snapshot(path, logical_name=name,
                                        max_bytes=staged.config.max_output_file_bytes)
        total += snapshot.size
        if total > staged.config.max_output_total_bytes:
            raise QualificationError("produced outputs exceed total size limit")
        snapshots[name] = snapshot
    return MappingProxyType(snapshots)


def verify_output_files(staged: StagedQualification, result: ProcessQualificationResult) -> None:
    current = snapshot_output_files(staged)
    if dict(current) != dict(result.output_files):
        raise QualificationError("produced output inventory changed")


def _canonical_output_record(staged: StagedQualification, snapshot: FileSnapshot) -> dict[str, object]:
    path = staged.run_directory / snapshot.name
    stable = stable_file_read(path, logical_name=snapshot.name,
                              max_bytes=staged.config.max_output_file_bytes)
    data = stable.data
    if stable.snapshot != snapshot:
        raise QualificationError(f"produced output changed during canonicalization: {snapshot.name}")
    if snapshot.name in {"phreeqc.out", "phreeqc.log"}:
        text = data.decode("utf-8", errors="strict")
        text = text.replace(str(staged.manifest.input_files[0][0]), "input.pqi")
        text = text.replace(str(staged.manifest.database), "database.dat")
        text = re.sub(r"^-+\nEnd of Run after [0-9.]+ Seconds\.\n-+$",
                      "---\nEnd of Run after <duration> Seconds.\n---", text, flags=re.MULTILINE)
        text = re.sub(r"End of Run after [0-9.]+ Seconds\.",
                      "End of Run after <duration> Seconds.", text)
        data = text.encode("utf-8")
    return {"name": snapshot.name, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "file_type": "regular"}


def run_qualification(staged: StagedQualification) -> ProcessQualificationResult:
    result = run_replayable(staged.manifest, timeout=staged.config.timeout_seconds,
                            max_stdout_bytes=staged.config.max_stdout_bytes,
                            max_stderr_bytes=staged.config.max_stderr_bytes)
    if result.timed_out:
        raise QualificationError("PHREEQC process timed out")
    if result.stream_drain_timed_out:
        raise QualificationError("PHREEQC stream drain did not complete before deadline")
    if not result.streams_complete or result.stream_errors:
        raise QualificationError("PHREEQC stream capture failed")
    if result.output_limits_exceeded:
        raise QualificationError(f"PHREEQC {', '.join(result.output_limits_exceeded)} exceeded byte limits")
    if result.launch_error is not None or result.exit_status is None:
        raise QualificationError("PHREEQC process state is incoherent or launch failed")
    if result.exit_status != 0:
        raise QualificationError(f"PHREEQC process exited with status {result.exit_status}")
    verify_staged_artifacts(staged)
    first_line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    banner_candidate = first_line
    log = staged.run_directory / "phreeqc.log"
    if log.is_file() and not log.is_symlink():
        log_text = log.read_text(encoding="utf-8", errors="replace")
        version = re.search(r"PHREEQC_([0-9]+(?:\.[0-9]+)+)", log_text)
        date = re.search(r"([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})", log_text)
        if version and date:
            banner_candidate = f"PHREEQC {version.group(1)}, {date.group(1)}"
    banner = staged.config.banner_matcher.verify(banner_candidate)
    outputs = snapshot_output_files(staged)
    selected_read = stable_file_read(staged.run_directory / "ex2.sel", logical_name="ex2.sel",
                                     max_bytes=staged.config.max_output_file_bytes)
    if (selected_read.snapshot != outputs["ex2.sel"]
            or selected_read.snapshot.sha256 != staged.config.expected_selected_output_sha256):
        raise QualificationError("verified selected output is unavailable or changed")
    try:
        parsed = parse_selected_output(selected_read.data.decode("utf-8", errors="strict"))
    except UnicodeDecodeError as exc:
        raise QualificationError("selected output is not UTF-8") from exc
    validate_example2_structure(parsed)
    return ProcessQualificationResult(result, staged.run_directory, outputs, banner,
                                      staged.run_identity_sha256, parsed)


SELECTED_OUTPUT_HEADER = (
    "sim", "state", "soln", "dist_x", "time", "step", "pH", "pe", "temp",
    "si_anhydrite", "si_gypsum",
)
SELECTED_OUTPUT_HEADER_LINE = "         sim\t       state\t        soln\t      dist_x\t        time\t        step\t          pH\t          pe\t        temp\tsi_anhydrite\t   si_gypsum\t"
SELECTED_OUTPUT_UNITS = MappingProxyType({
    "simulation": "1", "state": "category", "solution": "1", "distance": "m", "time": "s",
    "step": "1", "pH": "1", "pe": "1", "temperature": "degC",
    "si_anhydrite": "1", "si_gypsum": "1",
})


@dataclass(frozen=True)
class SelectedOutputRow:
    simulation: int; state: str; solution: int; distance: float; time: float; step: int
    pH: float; pe: float; temperature: float; si_anhydrite: float; si_gypsum: float


@dataclass(frozen=True)
class ParsedSelectedOutput:
    header: tuple[str, ...]
    units: Mapping[str, str]
    rows: tuple[SelectedOutputRow, ...]


def parse_selected_output(text: str) -> ParsedSelectedOutput:
    """Parse the fixed selected-output wire structure without judging its science."""
    lines = text.splitlines()
    if not lines or lines[0] != SELECTED_OUTPUT_HEADER_LINE:
        raise QualificationError("selected-output header mismatch")
    rows = []
    for number, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != len(SELECTED_OUTPUT_HEADER) + 1 or fields[-1] != "":
            raise QualificationError(f"selected-output field count mismatch on line {number}")
        fields = [field.strip() for field in fields[:-1]]
        try:
            integers = [float(fields[i]) for i in (0, 2, 5)]
            if any(not value.is_integer() for value in integers):
                raise ValueError
            numeric = [float(fields[i]) for i in (3, 4, 6, 7, 8, 9, 10)]
            if any(not math.isfinite(value) for value in integers + numeric):
                raise ValueError
        except ValueError as exc:
            raise QualificationError(f"invalid selected-output number on line {number}") from exc
        if fields[1] not in {"i_soln", "react"}:
            raise QualificationError(f"invalid state on line {number}")
        rows.append(SelectedOutputRow(int(integers[0]), fields[1], int(integers[1]), numeric[0], numeric[1], int(integers[2]), *numeric[2:]))
    if len(rows) != 52 or sum(row.state == "i_soln" for row in rows) != 1 or sum(row.state == "react" for row in rows) != 51:
        raise QualificationError("selected-output requires one initial and 51 reaction rows")
    return ParsedSelectedOutput(SELECTED_OUTPUT_HEADER, SELECTED_OUTPUT_UNITS, tuple(rows))


def validate_example2_structure(parsed: ParsedSelectedOutput) -> None:
    """Validate upstream Example 2 ordering and control-field invariants only."""
    rows = parsed.rows
    if len(rows) != 52 or rows[0].state != "i_soln" or any(row.state != "react" for row in rows[1:]):
        raise QualificationError("Example 2 state ordering mismatch")
    if any(row.simulation != 1 or row.solution != 1 for row in rows):
        raise QualificationError("Example 2 simulation or solution mismatch")
    if rows[0].step != -99 or [row.step for row in rows[1:]] != list(range(1, 52)):
        raise QualificationError("Example 2 step sequence mismatch")
    if rows[0].temperature != 25.0 or [row.temperature for row in rows[1:]] != [float(v) for v in range(25, 76)]:
        raise QualificationError("Example 2 temperature sequence mismatch")
    if rows[0].distance != -99.0 or rows[0].time != -99.0:
        raise QualificationError("Example 2 initial distance/time mismatch")
    if any(row.distance != -99.0 or row.time != 0.0 for row in rows[1:]):
        raise QualificationError("Example 2 reaction distance/time mismatch")


def normalize_selected_output(parsed: ParsedSelectedOutput) -> tuple[dict[str, object], ...]:
    return tuple({**asdict(row), "row_kind": "initial" if row.state.lower() in {"initial", "i_soln"} else "reaction"} for row in parsed.rows)


@dataclass(frozen=True, init=False)
class QualificationClassification:
    process_qualified: bool
    scientific_input_qualified: bool
    scientific_result_qualified: bool
    scientific_result_reason: str

    def __init__(self, *args, **kwargs) -> None:
        raise QualificationError("qualification classification must be derived from verified execution")

    @classmethod
    def _from_verified_execution(cls, scientific_result_reason: str) -> "QualificationClassification":
        if not isinstance(scientific_result_reason, str) or not scientific_result_reason.strip():
            raise QualificationError("scientific-result reason is required")
        value = object.__new__(cls)
        object.__setattr__(value, "process_qualified", True)
        object.__setattr__(value, "scientific_input_qualified", True)
        object.__setattr__(value, "scientific_result_qualified", False)
        object.__setattr__(value, "scientific_result_reason", scientific_result_reason)
        return value


def derive_qualification_classification(staged: StagedQualification, result: ProcessQualificationResult,
                                        scientific_result_reason: str) -> QualificationClassification:
    if result.run_identity_sha256 != staged.run_identity_sha256:
        raise QualificationError("staging and process result identities do not match")
    if (result.process.timed_out or result.process.stream_drain_timed_out
            or not result.process.streams_complete or result.process.stream_errors
            or result.process.launch_error is not None or result.process.exit_status != 0):
        raise QualificationError("process result is not a successful verified execution")
    verify_staged_artifacts(staged)
    verify_output_files(staged, result)
    expected_sources = {
        "executable": staged.config.expected_executable_sha256,
        "database": staged.config.expected_database_sha256,
        "input": staged.config.expected_input_sha256,
    }
    if dict(staged.source_hashes) != expected_sources or dict(staged.staged_hashes) != expected_sources:
        raise QualificationError("qualification artifact evidence is inconsistent")
    selected = result.working_directory / "ex2.sel"
    selected_read = stable_file_read(selected, logical_name="ex2.sel",
                                     max_bytes=staged.config.max_output_file_bytes)
    selected_snapshot = selected_read.snapshot
    if (result.output_files.get("ex2.sel") != selected_snapshot
            or selected_snapshot.sha256 != staged.config.expected_selected_output_sha256):
        raise QualificationError("verified selected output is unavailable or changed")
    try:
        parsed = parse_selected_output(selected_read.data.decode("utf-8", errors="strict"))
    except UnicodeDecodeError as exc:
        raise QualificationError("selected output is not UTF-8") from exc
    if parsed != result.parsed_selected_output:
        raise QualificationError("parsed selected output does not match the verified artifact")
    validate_example2_structure(parsed)
    return QualificationClassification._from_verified_execution(scientific_result_reason)


def write_qualification_replay(path: Path, staged: StagedQualification, result: ProcessQualificationResult,
                               scientific_result_reason: str) -> ReplayBundle:
    if result.run_identity_sha256 != staged.run_identity_sha256:
        raise QualificationError("staging and process result identities do not match")
    verify_staged_artifacts(staged)
    verify_output_files(staged, result)
    classification = derive_qualification_classification(staged, result, scientific_result_reason)
    parsed = result.parsed_selected_output
    manifest = staged.manifest
    canonical = {
        "schema": "phreeqc-qualification-1",
        "configuration": {
            "artifact_hashes": dict(staged.staged_hashes),
            "expected_selected_output_sha256": staged.config.expected_selected_output_sha256,
            "banner_pattern": staged.config.banner_matcher.fullmatch_pattern,
            "timeout_seconds": staged.config.timeout_seconds,
            "max_stdout_bytes": staged.config.max_stdout_bytes,
            "max_stderr_bytes": staged.config.max_stderr_bytes,
            "allowed_outputs": list(staged.config.allowed_outputs),
            "required_outputs": list(staged.config.required_outputs),
            "max_output_files": staged.config.max_output_files,
            "max_output_file_bytes": staged.config.max_output_file_bytes,
            "max_output_total_bytes": staged.config.max_output_total_bytes,
        },
        "manifest": {"executable": "phreeqc", "database": "database.dat",
                     "inputs": [["input.pqi", staged.config.expected_input_sha256]],
                     "command": ["phreeqc", "input.pqi", "phreeqc.out", "database.dat", "phreeqc.log"],
                     "version_matcher": manifest.version},
        "source_hashes": dict(staged.source_hashes), "staged_hashes": dict(staged.staged_hashes),
        "process": {**result.deterministic_payload(),
                    "output_files": {name: _canonical_output_record(staged, snapshot)
                                     for name, snapshot in sorted(result.output_files.items())}},
        "selected_output": list(normalize_selected_output(parsed)),
        "selected_output_units": dict(parsed.units), "classification": asdict(classification),
    }
    encoded = json.dumps(canonical, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    results = {"qualification_content": canonical,
               "qualification_content_sha256": hashlib.sha256(encoded).hexdigest()}
    normalized_input = {"schema": "phreeqc-qualification-1", "artifact_hashes": dict(staged.source_hashes)}
    metadata = {"duration_seconds": result.process.duration_seconds, "contract": "process-qualified-only",
                "run_identity_sha256": result.run_identity_sha256,
                "paths": staged.config.normalized(),
                "raw_output_files": {name: asdict(snapshot)
                                     for name, snapshot in sorted(result.output_files.items())}}
    bundle = ReplayBundle.write(path, normalized_input, {"artifact_hashes": dict(staged.source_hashes)},
                                results, tool_trace=[{"tool": "phreeqc", "command": canonical["manifest"]["command"]}],
                                metadata=metadata)
    verify_bundle(path)
    return bundle
