from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
import csv
import json
import os
from pathlib import Path
import re
import shutil
import signal
import time
from typing import Any

from agent_factory.local_inference.implementation import LlamaImplementationBuild
from agent_factory.local_inference.kernel_catalog import KernelCatalog, load_kernel_catalog
from agent_factory.local_inference.node_control import InferenceOperatorAnalysisOptions
from agent_factory.model_pool.schema import LlamaCppInferenceConfig, LocalModelArtifact, ModelPoolProfile
from agent_factory.paths import factory_artifact_path


_GRAPH_NODE_PATTERN = re.compile(
    r"node\s+#\d+\s+\((?P<operation>[^)]+)\).*?\[(?P<backend>[^\]]+)\]",
    re.IGNORECASE,
)
_GRAPH_SPLIT_PATTERN = re.compile(
    r"##\s+SPLIT\s+#\d+\s*:\s*(?P<backend>\S+)",
    re.IGNORECASE,
)


async def run_llama_operator_analysis(
    *,
    profile: ModelPoolProfile,
    artifact: LocalModelArtifact,
    build: LlamaImplementationBuild,
    analysis_id: str,
    options: InferenceOperatorAnalysisOptions,
) -> dict[str, Any]:
    profiler = shutil.which("rocprofv3")
    if profiler is None:
        raise RuntimeError("rocprofv3 is unavailable on the inference node")
    benchmark_binary = Path(build.benchmark_binary_path).expanduser().resolve()
    if not benchmark_binary.is_file() or not os.access(benchmark_binary, os.X_OK):
        raise RuntimeError(
            f"active llama.cpp build does not provide an executable llama-bench: {benchmark_binary}"
        )
    model_path = artifact.resolved_path()
    if not model_path.is_file():
        raise RuntimeError(f"llama.cpp model file is unavailable: {model_path}")
    inference = profile.inference
    if not isinstance(inference, LlamaCppInferenceConfig):
        raise ValueError("operator analysis requires llama.cpp inference settings")
    catalog = load_kernel_catalog(
        path=build.kernel_catalog_path,
        expected_sha256=build.kernel_catalog_sha256,
        implementation=build.implementation,
    )

    analysis_root = factory_artifact_path(
        "benchmark",
        "operator-analysis",
        _safe_analysis_id(analysis_id),
    )
    analysis_root.mkdir(parents=True, exist_ok=False)
    phases = [
        await _run_phase(
            phase="prefill",
            profiler=profiler,
            benchmark_binary=benchmark_binary,
            model_path=model_path,
            inference=inference,
            prompt_tokens=options.prefill_tokens,
            generation_tokens=0,
            repetitions=options.repetitions,
            top_kernels=options.top_kernels,
            output_root=analysis_root,
            catalog=catalog,
        ),
        await _run_phase(
            phase="decode",
            profiler=profiler,
            benchmark_binary=benchmark_binary,
            model_path=model_path,
            inference=inference,
            prompt_tokens=0,
            generation_tokens=options.decode_tokens,
            repetitions=options.repetitions,
            top_kernels=options.top_kernels,
            output_root=analysis_root,
            catalog=catalog,
        ),
    ]
    return {
        "profiler": "rocprofv3",
        "gpu_graphs_disabled_for_attribution": True,
        "phases": phases,
        "warnings": [
            warning
            for phase in phases
            for warning in phase.get("warnings", [])
        ],
    }


async def _run_phase(
    *,
    phase: str,
    profiler: str,
    benchmark_binary: Path,
    model_path: Path,
    inference: LlamaCppInferenceConfig,
    prompt_tokens: int,
    generation_tokens: int,
    repetitions: int,
    top_kernels: int,
    output_root: Path,
    catalog: KernelCatalog,
) -> dict[str, Any]:
    phase_root = output_root / phase
    profiler_root = phase_root / "rocprof"
    profiler_root.mkdir(parents=True)
    benchmark_command = [
        str(benchmark_binary),
        "-m",
        str(model_path),
        "-p",
        str(prompt_tokens),
        "-n",
        str(generation_tokens),
        "-r",
        str(repetitions),
        "-ngl",
        str(inference.gpu_layers),
        "-ctk",
        inference.cache_type_k,
        "-ctv",
        inference.cache_type_v,
        "-fa",
        "on" if inference.flash_attention else "off",
        "-o",
        "json",
        "-v",
        "--no-warmup",
    ]
    command = [
        profiler,
        "--kernel-trace",
        "--stats",
        "--output-format",
        "csv",
        "--output-directory",
        str(profiler_root),
        "--",
        *benchmark_command,
    ]
    environment = dict(os.environ)
    environment["GGML_SCHED_DEBUG"] = "2"
    environment["GGML_CUDA_DISABLE_GRAPHS"] = "1"
    custom_kernel_summary_path = phase_root / "custom-kernel-summary.json"
    environment["AGENTFACTORY_KERNEL_TRACE_OUTPUT"] = str(custom_kernel_summary_path)
    started = time.perf_counter()
    process = await asyncio.create_subprocess_exec(
        *command,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=3600,
        )
    except BaseException:
        await _terminate_process_group(process)
        raise
    elapsed_seconds = time.perf_counter() - started
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    (phase_root / "stdout.jsonl").write_text(stdout, encoding="utf-8")
    (phase_root / "stderr.log").write_text(stderr, encoding="utf-8")
    (phase_root / "command.json").write_text(
        json.dumps(benchmark_command, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if process.returncode != 0:
        detail = _last_nonempty_line(stderr) or _last_nonempty_line(stdout)
        raise RuntimeError(
            f"{phase} operator analysis exited with code {process.returncode}: {detail}"
        )

    top_kernel_rows, profiler_warnings = _read_kernel_stats(
        profiler_root,
        top_kernels,
        catalog,
    )
    custom_kernels, dispatches = _read_operator_trace(custom_kernel_summary_path, catalog)
    trace_events = _read_kernel_trace_events(profiler_root)
    dispatch_variants, dispatch_warnings = _aggregate_dispatch_variants(
        dispatches,
        trace_events,
    )
    return {
        "phase": phase,
        "elapsed_seconds": elapsed_seconds,
        "benchmark_rows": _read_json_rows(stdout),
        "top_kernels": top_kernel_rows,
        "graph_operators": _read_graph_operators(stderr),
        "custom_kernels": custom_kernels,
        "dispatch_variants": dispatch_variants,
        "artifact_directory": str(phase_root),
        "warnings": [*profiler_warnings, *dispatch_warnings],
    }


def _read_operator_trace(
    path: Path,
    catalog: KernelCatalog,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not path.is_file():
        return [], []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("custom kernel summary schema_version must be 1")
    kernel_rows = payload.get("kernels")
    if not isinstance(kernel_rows, list):
        raise ValueError("custom kernel summary must contain a kernels list")
    kernels: list[dict[str, Any]] = []
    for row in kernel_rows:
        if not isinstance(row, dict):
            raise ValueError("custom kernel summary entries must be objects")
        kernel_id = str(row.get("kernel_id") or "").strip().lower()
        descriptor = catalog.get(kernel_id)
        if descriptor is None:
            raise ValueError(f"custom kernel summary references an unknown kernel_id: {kernel_id}")
        fallback_reasons = row.get("fallback_reasons") or {}
        if not isinstance(fallback_reasons, dict):
            raise ValueError("custom kernel fallback_reasons must be an object")
        kernels.append(
            {
                "kernel_id": kernel_id,
                "display_name": descriptor.display_name,
                "family": descriptor.family,
                "descriptions": descriptor.descriptions,
                "selected_count": _non_negative_count(row.get("selected_count")),
                "dispatch_count": _non_negative_count(row.get("dispatch_count")),
                "fallback_count": _non_negative_count(row.get("fallback_count")),
                "fallback_reasons": {
                    str(reason): _non_negative_count(count)
                    for reason, count in fallback_reasons.items()
                },
            }
        )
    dispatch_rows = payload.get("dispatches") or []
    if not isinstance(dispatch_rows, list):
        raise ValueError("operator trace dispatches must be a list")
    dispatches = [
        _validated_dispatch(row, expected_sequence=index)
        for index, row in enumerate(dispatch_rows)
    ]
    return kernels, dispatches


def _validated_dispatch(row: Any, *, expected_sequence: int) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("operator trace dispatch entries must be objects")
    if row.get("sequence") != expected_sequence:
        raise ValueError("operator trace dispatch sequence must be contiguous and ordered")
    operation = str(row.get("operation") or "").strip().lower()
    if operation not in {"mmvq", "mmq"}:
        raise ValueError(f"unsupported operator trace operation: {operation}")
    weight_type = str(row.get("weight_type") or "").strip().upper()
    if not weight_type:
        raise ValueError("operator trace weight_type is required")
    configuration = row.get("configuration")
    if not isinstance(configuration, dict):
        raise ValueError("operator trace configuration must be an object")
    if any(not isinstance(key, str) for key in configuration):
        raise ValueError("operator trace configuration keys must be strings")
    return {
        "operation": operation,
        "weight_type": weight_type,
        "m": _positive_integer(row.get("m"), "m"),
        "n": _positive_integer(row.get("n"), "n"),
        "k": _positive_integer(row.get("k"), "k"),
        "has_ids": _boolean_value(row.get("has_ids"), "has_ids"),
        "has_fusion": _boolean_value(row.get("has_fusion"), "has_fusion"),
        "experts": _non_negative_count(row.get("experts")),
        "active_experts": _non_negative_count(row.get("active_experts")),
        "configuration": configuration,
    }


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=20.0)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        await process.wait()


def _read_json_rows(output: str) -> list[dict[str, Any]]:
    text = output.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return [payload] if isinstance(payload, dict) else []


def _read_graph_operators(stderr: str) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    split_backend = ""
    for line in stderr.splitlines():
        split_match = _GRAPH_SPLIT_PATTERN.search(line)
        if split_match:
            split_backend = split_match.group("backend").strip()
        node_match = _GRAPH_NODE_PATTERN.search(line)
        if not node_match:
            continue
        operation = node_match.group("operation").strip()
        backend_field = node_match.group("backend").strip()
        backend = (backend_field.split(maxsplit=1)[0] if backend_field else split_backend) or "unknown"
        counts[(operation, backend)] += 1
    return [
        {"operation": operation, "backend": backend, "count": count}
        for (operation, backend), count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def _read_kernel_trace_events(root: Path) -> list[tuple[str, float, float]]:
    candidates: list[tuple[Path, list[tuple[str, float, float]], int]] = []
    for path in sorted(root.rglob("*.csv")):
        rows: list[tuple[str, float, float]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            normalized_headers = {
                _normalize_header(header)
                for header in (reader.fieldnames or [])
                if header
            }
            explicit_kernel_column = bool(
                normalized_headers.intersection({"kernelname", "kernel", "function"})
            )
            for row in reader:
                normalized = {_normalize_header(key): value for key, value in row.items() if key}
                name = _first_text(normalized, "kernelname", "kernel", "function", "name")
                start = _first_number(normalized, "starttimestamp", "start", "begints")
                end = _first_number(normalized, "endtimestamp", "end", "endts")
                if name and start is not None and end is not None and end >= start:
                    rows.append((name, start, end - start))
        if not rows:
            continue
        file_name = path.name.lower()
        non_kernel_domain = any(
            marker in file_name
            for marker in ("api", "counter", "dispatch", "domain", "marker")
        )
        score = (
            -1
            if non_kernel_domain
            else 4
            if "kernel" in file_name and "trace" in file_name
            else 3
            if explicit_kernel_column
            else 1
        )
        candidates.append((path, rows, score))
    eligible = [candidate for candidate in candidates if candidate[2] >= 0]
    if not eligible:
        return []
    best_score = max(score for _, _, score in eligible)
    events = [
        event
        for _, rows, score in eligible
        if score == best_score
        for event in rows
    ]
    return sorted(events, key=lambda event: event[1])


def _aggregate_dispatch_variants(
    dispatches: list[dict[str, Any]],
    trace_events: list[tuple[str, float, float]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not dispatches:
        return [], [
            "llama.cpp did not emit host dispatch metadata; redeploy both instrumented implementations "
            "before running operator analysis again"
        ]
    if not trace_events:
        return [], [
            "rocprofv3 did not emit a recognizable kernel timeline; quantization and Shape timing "
            "cannot be paired safely"
        ]

    events_by_operation: dict[str, list[tuple[str, float, float]]] = {
        "mmvq": [],
        "mmq": [],
    }
    for event in trace_events:
        operation = _dispatch_operation_for_kernel(event[0])
        if operation is not None:
            events_by_operation[operation].append(event)

    warnings: list[str] = []
    paired: list[tuple[dict[str, Any], float]] = []
    for operation in ("mmvq", "mmq"):
        operation_dispatches = [row for row in dispatches if row["operation"] == operation]
        operation_events = events_by_operation[operation]
        if len(operation_dispatches) != len(operation_events):
            warnings.append(
                f"{operation.upper()} host dispatch count ({len(operation_dispatches)}) does not match "
                f"rocprof kernel event count ({len(operation_events)}); variant timing was omitted"
            )
            continue
        paired.extend(
            (dispatch, event[2])
            for dispatch, event in zip(operation_dispatches, operation_events, strict=True)
        )

    totals: defaultdict[tuple[Any, ...], dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "duration_ns": 0.0, "dispatch": None}
    )
    for dispatch, duration_ns in paired:
        configuration_key = json.dumps(
            dispatch["configuration"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        key = (
            dispatch["operation"],
            dispatch["weight_type"],
            dispatch["m"],
            dispatch["n"],
            dispatch["k"],
            dispatch["has_ids"],
            dispatch["has_fusion"],
            dispatch["experts"],
            dispatch["active_experts"],
            configuration_key,
        )
        totals[key]["calls"] += 1
        totals[key]["duration_ns"] += duration_ns
        totals[key]["dispatch"] = dispatch

    profiled_duration = sum(duration for _, _, duration in trace_events)
    result: list[dict[str, Any]] = []
    for values in sorted(
        totals.values(),
        key=lambda item: float(item["duration_ns"]),
        reverse=True,
    ):
        dispatch = values["dispatch"]
        calls = int(values["calls"])
        duration_ns = float(values["duration_ns"])
        result.append(
            {
                **dispatch,
                "calls": calls,
                "total_duration_ns": duration_ns,
                "average_duration_ns": duration_ns / calls,
                "duration_percent": min(
                    100.0,
                    duration_ns / profiled_duration * 100 if profiled_duration else 0.0,
                ),
            }
        )
    return result, warnings


def _dispatch_operation_for_kernel(raw_name: str) -> str | None:
    symbol = _base_symbol(raw_name)
    if symbol in {"mul_mat_vec_q", "mul_mat_vec_q_moe"}:
        return "mmvq"
    if symbol == "mul_mat_q":
        return "mmq"
    return None


def _read_kernel_stats(
    root: Path,
    limit: int,
    catalog: KernelCatalog,
) -> tuple[list[dict[str, Any]], list[str]]:
    csv_paths = sorted(root.rglob("*.csv"))
    aggregate_candidates: list[tuple[Path, list[tuple[str, int, float]], int]] = []
    trace_candidates: list[tuple[Path, list[tuple[str, int, float]], int]] = []
    for path in csv_paths:
        aggregate_rows: list[tuple[str, int, float]] = []
        trace_rows: list[tuple[str, int, float]] = []
        explicit_kernel_column = False
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            normalized_headers = {
                _normalize_header(header)
                for header in (reader.fieldnames or [])
                if header
            }
            explicit_kernel_column = bool(
                normalized_headers.intersection({"kernelname", "kernel", "function"})
            )
            for row in reader:
                normalized = {_normalize_header(key): value for key, value in row.items() if key}
                name = _first_text(
                    normalized,
                    "kernelname",
                    "kernel",
                    "function",
                    "name",
                )
                if not name:
                    continue
                calls = _first_number(normalized, "calls", "callcount", "count")
                total_ns = _duration_ns(normalized)
                if total_ns is not None and calls is not None:
                    aggregate_rows.append((name, max(0, int(calls)), max(0.0, total_ns)))
                    continue
                start = _first_number(normalized, "starttimestamp", "start", "begints")
                end = _first_number(normalized, "endtimestamp", "end", "endts")
                if start is not None and end is not None and end >= start:
                    trace_rows.append((name, 1, end - start))
        file_name = path.name.lower()
        kernel_stats_file = "kernel" in file_name and any(
            marker in file_name for marker in ("stat", "summary")
        )
        kernel_trace_file = "kernel" in file_name and "trace" in file_name
        non_kernel_domain = any(
            marker in file_name
            for marker in ("api", "counter", "dispatch", "domain", "marker")
        )
        aggregate_score = (
            -1
            if non_kernel_domain
            else 4
            if kernel_stats_file
            else 3
            if explicit_kernel_column
            else 1
        )
        trace_score = (
            -1
            if non_kernel_domain
            else 4
            if kernel_trace_file
            else 3
            if explicit_kernel_column
            else 1
        )
        if aggregate_rows:
            aggregate_candidates.append((path, aggregate_rows, aggregate_score))
        if trace_rows:
            trace_candidates.append((path, trace_rows, trace_score))

    aggregate_rows = _select_kernel_csv_rows(aggregate_candidates)
    trace_rows = _select_kernel_csv_rows(trace_candidates)
    source_rows = aggregate_rows if aggregate_rows else trace_rows
    if not source_rows:
        return [], [
            "rocprofv3 completed but no recognizable kernel timing rows were found; "
            f"inspect CSV artifacts under {root}"
        ]
    totals: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "duration_ns": 0.0,
            "variants": set(),
            "display_name": "",
            "family": "",
            "descriptions": {},
        }
    )
    for name, calls, duration_ns in source_rows:
        kernel_id, display_name, family, descriptions = _kernel_identity(name, catalog)
        totals[kernel_id]["calls"] += calls
        totals[kernel_id]["duration_ns"] += duration_ns
        totals[kernel_id]["variants"].add(name)
        totals[kernel_id]["display_name"] = display_name
        totals[kernel_id]["family"] = family
        totals[kernel_id]["descriptions"] = descriptions
    all_duration = sum(float(values["duration_ns"]) for values in totals.values())
    ranked = sorted(
        totals.items(),
        key=lambda item: float(item[1]["duration_ns"]),
        reverse=True,
    )[:limit]
    return [
        {
            "name": kernel_id,
            "display_name": str(values["display_name"]),
            "family": str(values["family"]),
            "descriptions": dict(values["descriptions"]),
            "variants": sorted(values["variants"])[:8],
            "variant_count": len(values["variants"]),
            "calls": int(values["calls"]),
            "total_duration_ns": float(values["duration_ns"]),
            "average_duration_ns": (
                float(values["duration_ns"]) / int(values["calls"])
                if int(values["calls"])
                else 0.0
            ),
            "duration_percent": (
                float(values["duration_ns"]) / all_duration * 100
                if all_duration
                else 0.0
            ),
        }
        for kernel_id, values in ranked
    ], []


def _select_kernel_csv_rows(
    candidates: list[tuple[Path, list[tuple[str, int, float]], int]],
) -> list[tuple[str, int, float]]:
    eligible = [candidate for candidate in candidates if candidate[2] >= 0]
    if not eligible:
        return []
    best_score = max(score for _, _, score in eligible)
    selected = [rows for _, rows, score in eligible if score == best_score]
    return [row for rows in selected for row in rows]


def _kernel_identity(
    raw_name: str,
    catalog: KernelCatalog,
) -> tuple[str, str, str, dict[str, str]]:
    raw_symbol = raw_name.strip()
    base_symbol = _base_symbol(raw_symbol)
    descriptor = catalog.resolve(raw_symbol=raw_symbol, base_symbol=base_symbol)
    if descriptor is not None:
        return (
            descriptor.kernel_id,
            descriptor.display_name,
            descriptor.family,
            descriptor.descriptions,
        )
    normalized_symbol = re.sub(r"[^a-z0-9_.-]+", "_", base_symbol.lower()).strip("_.-")
    return (
        f"unregistered.{normalized_symbol or 'unknown'}",
        _humanize_symbol(base_symbol),
        "unregistered",
        {
            "zh-CN": "当前活动实现未在 Kernel Catalog 中登记该 Kernel；请展开查看原始符号。",
            "en-US": (
                "This kernel is not registered in the active implementation catalog; "
                "expand it to inspect the raw symbol."
            ),
        },
    )


def _base_symbol(raw_name: str) -> str:
    normalized_name = re.sub(
        r"\(anonymous namespace\)::",
        "",
        raw_name.strip(),
    )
    match = re.match(
        r"^(?:(?:void|int|float|double|bool)\s+)?(?P<symbol>[A-Za-z_][A-Za-z0-9_:]*)",
        normalized_name,
    )
    symbol = match.group("symbol") if match else normalized_name
    return symbol.split("::")[-1]


def _humanize_symbol(value: str) -> str:
    words = re.sub(r"[_\-]+", " ", value).strip()
    return words.title() if words else "Unknown Kernel"


def _non_negative_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("custom kernel counters must be non-negative integers")
    return value


def _positive_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"operator trace {field_name} must be a positive integer")
    return value


def _boolean_value(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"operator trace {field_name} must be a boolean")
    return value


def _duration_ns(row: dict[str, str]) -> float | None:
    for key, scale in (
        ("totaldurationns", 1.0),
        ("totalduration", 1.0),
        ("durationns", 1.0),
        ("duration", 1.0),
        ("totaldurationus", 1_000.0),
        ("totaldurationms", 1_000_000.0),
    ):
        value = _first_number(row, key)
        if value is not None:
            return value * scale
    return None


def _first_text(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _first_number(row: dict[str, str], *keys: str) -> float | None:
    for key in keys:
        value = str(row.get(key) or "").strip().replace(",", "")
        if not value:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def _safe_analysis_id(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", normalized):
        raise ValueError("analysis_id must be a 32-character lowercase hexadecimal identifier")
    return normalized


def _last_nonempty_line(value: str) -> str:
    return next((line.strip() for line in reversed(value.splitlines()) if line.strip()), "")
