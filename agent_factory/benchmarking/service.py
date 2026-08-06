from __future__ import annotations

import asyncio
import json
import math
from statistics import fmean, pstdev
import time
from typing import Any
from uuid import uuid4

import httpx

from agent_factory.benchmarking.schema import (
    BenchmarkExperimentGroup,
    BenchmarkExperimentGroupSpec,
    BenchmarkExperimentRunRef,
    BenchmarkConcurrencyResult,
    BenchmarkImplementation,
    BenchmarkImplementationId,
    BenchmarkMetricStats,
    BenchmarkOperatorAnalysisResult,
    BenchmarkPromptCacheSummary,
    BenchmarkRun,
    BenchmarkRunKind,
    BenchmarkRunSpec,
    BenchmarkSample,
    BenchmarkSpeculativeDecodingSummary,
    BenchmarkSummary,
    BenchmarkTelemetryPoint,
    utc_now_text,
)
from agent_factory.benchmarking.store import BenchmarkStore
from agent_factory.local_inference.config import (
    LocalInferenceEndpoint,
    load_inference_telemetry_endpoint,
    load_local_inference_endpoint,
)
from agent_factory.local_inference.http_client import create_private_async_http_client
from agent_factory.local_inference.node_control import (
    InferenceNodeClient,
    InferenceNodeProfileConfiguration,
    InferenceOperatorAnalysisOptions,
    InferenceOperatorAnalysisRequest,
)
from agent_factory.local_inference.runtime_manager import LocalInferenceRuntimeManager
from agent_factory.model_pool.store import ModelPoolStore


class BenchmarkService:
    def __init__(
        self,
        runtime_manager: LocalInferenceRuntimeManager,
        *,
        store: BenchmarkStore | None = None,
    ) -> None:
        self._runtime_manager = runtime_manager
        self._store = store or BenchmarkStore()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._active_run_id = ""
        self._active_group_id = ""
        self._store.interrupt_incomplete()

    def list_runs(self, *, limit: int = 100) -> list[BenchmarkRun]:
        return self._store.list(limit=limit)

    def require_run(self, run_id: str) -> BenchmarkRun:
        return self._store.require(run_id)

    def list_groups(self, *, limit: int = 100) -> list[BenchmarkExperimentGroup]:
        return self._store.list_groups(limit=limit)

    def require_group(self, group_id: str) -> BenchmarkExperimentGroup:
        return self._store.require_group(group_id)

    def group_runs(self, group_id: str) -> list[BenchmarkRun]:
        group = self._store.require_group(group_id)
        return [self._store.require(item.run_id) for item in group.runs]

    async def start_run(self, spec: BenchmarkRunSpec) -> BenchmarkRun:
        if self._active_group_id:
            active_group = self._store.get_group(self._active_group_id)
            if active_group is not None and active_group.status in {"queued", "running"}:
                raise ValueError(
                    f"benchmark experiment group is already active: {active_group.group_id}"
                )
            self._active_group_id = ""
        if self._active_run_id:
            active = self._store.get(self._active_run_id)
            if active is not None and active.status in {"queued", "running"}:
                raise ValueError(f"benchmark run is already active: {active.run_id}")
            self._active_run_id = ""
        profile = ModelPoolStore().require_profile(spec.profile_id)
        if profile.kind != "chat" or not profile.enabled:
            raise ValueError("benchmark requires an enabled chat profile")
        if not self._runtime_manager.is_ready(profile.profile_id):
            raise ValueError("benchmark requires the selected model to be loaded and ready")
        spec = spec.model_copy(
            update={"implementation": await _active_benchmark_implementation()},
            deep=True,
        )
        total = (
            1
            if spec.kind == "operator_analysis"
            else (
                spec.concurrency.concurrent_requests
                * (
                    spec.concurrency.warmup_requests_per_worker
                    + spec.concurrency.requests_per_worker
                )
                if spec.kind == "concurrency" and spec.concurrency is not None
                else spec.warmup_iterations + spec.measured_iterations
            )
        )
        run = self._store.save(
            BenchmarkRun(
                run_id=uuid4().hex,
                spec=spec,
                progress_total=total,
            )
        )
        self._active_run_id = run.run_id
        self._tasks[run.run_id] = asyncio.create_task(self._execute(run.run_id))
        return run

    async def start_group(
        self,
        spec: BenchmarkExperimentGroupSpec,
    ) -> BenchmarkExperimentGroup:
        self._require_idle()
        profile = ModelPoolStore().require_profile(spec.profile_id)
        if profile.kind != "chat" or not profile.enabled:
            raise ValueError("benchmark requires an enabled chat profile")
        if not self._runtime_manager.is_ready(profile.profile_id):
            raise ValueError("benchmark requires the selected model to be loaded and ready")
        implementation_status = await InferenceNodeClient().llama_implementation()
        available = {build.implementation for build in implementation_status.builds}
        missing = {"official", "amd"} - available
        if missing:
            raise ValueError(
                "benchmark experiment group requires both llama.cpp implementations; "
                f"missing: {', '.join(sorted(missing))}"
            )
        if implementation_status.active not in {"official", "amd"}:
            raise ValueError("the inference node did not report an active llama.cpp implementation")
        group = self._store.save_group(
            BenchmarkExperimentGroup(
                group_id=uuid4().hex,
                spec=spec,
                progress_total=spec.repetitions * 6,
                initial_implementation=implementation_status.active,
                active_implementation=implementation_status.active,
            )
        )
        self._active_group_id = group.group_id
        self._tasks[group.group_id] = asyncio.create_task(
            self._execute_group(group.group_id)
        )
        return group

    def delete_group(self, group_id: str) -> bool:
        group = self._store.require_group(group_id)
        if group.status in {"queued", "running"}:
            raise ValueError("a running benchmark experiment group cannot be deleted")
        return self._store.delete_group(group_id)

    async def cancel_run(self, run_id: str) -> BenchmarkRun:
        run = self._store.require(run_id)
        if run.spec.kind == "operator_analysis" and run.status in {"queued", "running"}:
            raise ValueError(
                "operator analysis cannot be cancelled while profiler cleanup and runtime restore are pending"
            )
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return self._store.require(run_id)

    def delete_run(self, run_id: str) -> bool:
        run = self._store.require(run_id)
        if run.status in {"queued", "running"}:
            raise ValueError("a running benchmark must be cancelled before deletion")
        return self._store.delete(run_id)

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _require_idle(self) -> None:
        if self._active_group_id:
            group = self._store.get_group(self._active_group_id)
            if group is not None and group.status in {"queued", "running"}:
                raise ValueError(f"benchmark experiment group is already active: {group.group_id}")
            self._active_group_id = ""
        if self._active_run_id:
            run = self._store.get(self._active_run_id)
            if run is not None and run.status in {"queued", "running"}:
                raise ValueError(f"benchmark run is already active: {run.run_id}")
            self._active_run_id = ""

    async def _execute_group(self, group_id: str) -> None:
        group = self._store.require_group(group_id)
        restored_error: Exception | None = None
        execution_succeeded = False
        try:
            group = self._store.save_group(
                group.model_copy(
                    update={"status": "running", "started_at": utc_now_text()},
                    deep=True,
                )
            )
            for repetition_index in range(group.spec.repetitions):
                implementations = (
                    ("official", "amd")
                    if repetition_index % 2 == 0
                    else ("amd", "official")
                )
                for implementation in implementations:
                    await self._activate_group_implementation(
                        group_id,
                        implementation,
                    )
                    for kind in ("performance", "concurrency", "operator_analysis"):
                        await self._execute_group_run(
                            group_id,
                            repetition_index=repetition_index,
                            implementation=implementation,
                            kind=kind,
                        )
            execution_succeeded = True
        except asyncio.CancelledError:
            current = self._store.require_group(group_id)
            self._store.save_group(
                current.model_copy(
                    update={
                        "status": "interrupted",
                        "error": "benchmark process stopped before the experiment group completed",
                        "completed_at": utc_now_text(),
                    },
                    deep=True,
                )
            )
            raise
        except Exception as exc:
            current = self._store.require_group(group_id)
            self._store.save_group(
                current.model_copy(
                    update={
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "completed_at": utc_now_text(),
                    },
                    deep=True,
                )
            )
        finally:
            current = self._store.require_group(group_id)
            if (
                current.initial_implementation is not None
                and current.active_implementation != current.initial_implementation
            ):
                try:
                    await self._activate_group_implementation(
                        group_id,
                        current.initial_implementation,
                    )
                except Exception as exc:
                    restored_error = exc
            if restored_error is not None:
                current = self._store.require_group(group_id)
                restoration_message = (
                    "failed to restore the initial llama.cpp implementation: "
                    f"{type(restored_error).__name__}: {restored_error}"
                )
                self._store.save_group(
                    current.model_copy(
                        update={
                            "status": "failed",
                            "error": "; ".join(
                                part for part in (current.error, restoration_message) if part
                            ),
                            "completed_at": current.completed_at or utc_now_text(),
                        },
                        deep=True,
                    )
                )
            elif execution_succeeded:
                current = self._store.require_group(group_id)
                self._store.save_group(
                    current.model_copy(
                        update={"status": "completed", "completed_at": utc_now_text()},
                        deep=True,
                    )
                )
            self._tasks.pop(group_id, None)
            if self._active_group_id == group_id:
                self._active_group_id = ""

    async def _activate_group_implementation(
        self,
        group_id: str,
        implementation: BenchmarkImplementationId,
    ) -> None:
        group = self._store.require_group(group_id)
        if group.active_implementation == implementation:
            return
        await InferenceNodeClient().activate_llama_implementation(implementation)
        current = self._store.require_group(group_id)
        self._store.save_group(
            current.model_copy(
                update={"active_implementation": implementation},
                deep=True,
            )
        )

    async def _execute_group_run(
        self,
        group_id: str,
        *,
        repetition_index: int,
        implementation: BenchmarkImplementationId,
        kind: BenchmarkRunKind,
    ) -> None:
        group = self._store.require_group(group_id)
        run_spec = await self._group_run_spec(
            group.spec,
            repetition_index=repetition_index,
            implementation=implementation,
            kind=kind,
        )
        run = self._store.save(
            BenchmarkRun(
                run_id=uuid4().hex,
                spec=run_spec,
                progress_total=(
                    1
                    if kind == "operator_analysis"
                    else (
                        run_spec.concurrency.concurrent_requests
                        * (
                            run_spec.concurrency.warmup_requests_per_worker
                            + run_spec.concurrency.requests_per_worker
                        )
                        if kind == "concurrency" and run_spec.concurrency is not None
                        else run_spec.warmup_iterations + run_spec.measured_iterations
                    )
                ),
            )
        )
        ref = BenchmarkExperimentRunRef(
            run_id=run.run_id,
            repetition_index=repetition_index,
            implementation=implementation,
            kind=kind,
        )
        self._store.save_group(
            group.model_copy(update={"runs": [*group.runs, ref]}, deep=True)
        )
        await self._execute(run.run_id)
        completed = self._store.require(run.run_id)
        if completed.status != "completed":
            raise RuntimeError(
                f"{implementation} {kind} run failed: {completed.error or completed.status}"
            )
        current = self._store.require_group(group_id)
        self._store.save_group(
            current.model_copy(
                update={"progress_completed": current.progress_completed + 1},
                deep=True,
            )
        )

    async def _group_run_spec(
        self,
        spec: BenchmarkExperimentGroupSpec,
        *,
        repetition_index: int,
        implementation: BenchmarkImplementationId,
        kind: BenchmarkRunKind,
    ) -> BenchmarkRunSpec:
        active = await _active_benchmark_implementation()
        active_id = str(active.parameters.get("implementation") or "")
        if active_id != implementation:
            raise ValueError(
                f"active implementation mismatch: expected {implementation}, got {active_id or 'unknown'}"
            )
        return BenchmarkRunSpec(
            kind=kind,
            name=f"{spec.name} · {repetition_index + 1} · {implementation}",
            profile_id=spec.profile_id,
            prompt=spec.prompt if kind in {"performance", "concurrency"} else "",
            max_output_tokens=spec.max_output_tokens,
            temperature=spec.temperature,
            seed=spec.seed,
            warmup_iterations=spec.warmup_iterations,
            measured_iterations=spec.measured_iterations,
            telemetry_interval_ms=spec.telemetry_interval_ms,
            prompt_cache_mode=spec.prompt_cache_mode,
            implementation=active,
            concurrency=(spec.concurrency if kind == "concurrency" else None),
            operator_analysis=(spec.operator_analysis if kind == "operator_analysis" else None),
        )

    async def _execute(self, run_id: str) -> None:
        run = self._store.require(run_id)
        try:
            run = self._store.save(
                run.model_copy(
                    update={
                        "status": "running",
                        "started_at": utc_now_text(),
                        "environment": await self._environment(run.spec.profile_id),
                    },
                    deep=True,
                )
            )
            if run.spec.kind == "operator_analysis":
                await self._execute_operator_analysis(run)
                return
            if run.spec.kind == "concurrency":
                await self._execute_concurrency(run)
                return
            profile = ModelPoolStore().require_profile(run.spec.profile_id)
            endpoint = load_local_inference_endpoint(
                timeout_seconds=profile.limits.timeout_seconds or 600.0
            )
            async with create_private_async_http_client(endpoint) as client:
                for sample_index in range(run.progress_total):
                    current = self._store.require(run_id)
                    sample = await self._run_sample(
                        current.spec,
                        client=client,
                        endpoint=endpoint,
                        served_model_name=profile.served_model_name,
                        sample_index=sample_index,
                        warmup=sample_index < current.spec.warmup_iterations,
                    )
                    run = self._store.save(
                        current.model_copy(
                            update={
                                "samples": [*current.samples, sample],
                                "progress_completed": sample_index + 1,
                            },
                            deep=True,
                        )
                    )
                    if sample.status == "failed":
                        raise RuntimeError(sample.error or "benchmark sample failed")
            summary = _summarize(run.samples)
            self._store.save(
                run.model_copy(
                    update={
                        "status": "completed",
                        "summary": summary,
                        "completed_at": utc_now_text(),
                    },
                    deep=True,
                )
            )
        except asyncio.CancelledError:
            current = self._store.require(run_id)
            self._store.save(
                current.model_copy(
                    update={
                        "status": "cancelled",
                        "error": "benchmark was cancelled",
                        "completed_at": utc_now_text(),
                    },
                    deep=True,
                )
            )
            raise
        except Exception as exc:
            current = self._store.require(run_id)
            self._store.save(
                current.model_copy(
                    update={
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "completed_at": utc_now_text(),
                    },
                    deep=True,
                )
            )
        finally:
            self._tasks.pop(run_id, None)
            if self._active_run_id == run_id:
                self._active_run_id = ""

    async def _execute_concurrency(self, run: BenchmarkRun) -> None:
        settings = run.spec.concurrency
        if settings is None:
            raise ValueError("concurrency benchmark settings are missing")
        profile = ModelPoolStore().require_profile(run.spec.profile_id)
        endpoint = load_local_inference_endpoint(
            timeout_seconds=profile.limits.timeout_seconds or 600.0
        )
        samples: list[BenchmarkSample] = []
        progress_lock = asyncio.Lock()
        next_sample_index = 0

        async with create_private_async_http_client(endpoint) as client:
            async def execute_phase(*, requests_per_worker: int, warmup: bool) -> float:
                nonlocal next_sample_index
                start_gate = asyncio.Event()

                async def worker() -> None:
                    nonlocal next_sample_index
                    await start_gate.wait()
                    for _ in range(requests_per_worker):
                        async with progress_lock:
                            sample_index = next_sample_index
                            next_sample_index += 1
                        sample = await self._run_sample(
                            run.spec,
                            client=client,
                            endpoint=endpoint,
                            served_model_name=profile.served_model_name,
                            sample_index=sample_index,
                            warmup=warmup,
                            telemetry_enabled=False,
                        )
                        async with progress_lock:
                            samples.append(sample)
                            current = self._store.require(run.run_id)
                            self._store.save(
                                current.model_copy(
                                    update={
                                        "samples": list(samples),
                                        "progress_completed": len(samples),
                                    },
                                    deep=True,
                                )
                            )

                workers = [
                    asyncio.create_task(worker())
                    for _ in range(settings.concurrent_requests)
                ]
                started_ns = time.perf_counter_ns()
                start_gate.set()
                await asyncio.gather(*workers)
                return (time.perf_counter_ns() - started_ns) / 1_000_000_000

            if settings.warmup_requests_per_worker:
                await execute_phase(
                    requests_per_worker=settings.warmup_requests_per_worker,
                    warmup=True,
                )
            elapsed_seconds = await execute_phase(
                requests_per_worker=settings.requests_per_worker,
                warmup=False,
            )

        measured = [sample for sample in samples if not sample.warmup]
        successful = [sample for sample in measured if sample.status == "completed"]
        if not successful:
            errors = "; ".join(sample.error for sample in measured if sample.error)
            raise RuntimeError(errors or "all concurrency benchmark requests failed")
        input_tokens = sum(sample.prompt_tokens or 0 for sample in successful)
        output_tokens = sum(sample.completion_tokens or 0 for sample in successful)
        concurrency_result = BenchmarkConcurrencyResult(
            concurrent_requests=settings.concurrent_requests,
            request_count=len(measured),
            successful_requests=len(successful),
            error_rate_percent=(len(measured) - len(successful)) / len(measured) * 100,
            elapsed_seconds=elapsed_seconds,
            requests_per_second=len(successful) / elapsed_seconds,
            input_tokens_per_second=input_tokens / elapsed_seconds,
            output_tokens_per_second=output_tokens / elapsed_seconds,
            request_latency_ms=_stats(successful, "end_to_end_ms"),
            ttft_ms=_stats(successful, "ttft_ms"),
        )
        current = self._store.require(run.run_id)
        self._store.save(
            current.model_copy(
                update={
                    "status": "completed",
                    "samples": samples,
                    "summary": _summarize(samples),
                    "concurrency": concurrency_result,
                    "completed_at": utc_now_text(),
                },
                deep=True,
            )
        )

    async def _execute_operator_analysis(self, run: BenchmarkRun) -> None:
        settings = run.spec.operator_analysis
        if settings is None:
            raise ValueError("operator analysis settings are missing")
        profile = ModelPoolStore().require_profile(run.spec.profile_id)
        result_payload = await InferenceNodeClient().operator_analysis(
            InferenceOperatorAnalysisRequest(
                model_id=profile.served_model_name,
                profile=InferenceNodeProfileConfiguration.from_profile(profile),
                analysis_id=run.run_id,
                options=InferenceOperatorAnalysisOptions.model_validate(
                    settings.model_dump(mode="json")
                ),
            )
        )
        result = BenchmarkOperatorAnalysisResult.model_validate(result_payload)
        current = self._store.require(run.run_id)
        self._store.save(
            current.model_copy(
                update={
                    "status": "completed",
                    "progress_completed": 1,
                    "operator_analysis": result,
                    "completed_at": utc_now_text(),
                },
                deep=True,
            )
        )

    async def _run_sample(
        self,
        spec: BenchmarkRunSpec,
        *,
        client: httpx.AsyncClient,
        endpoint: LocalInferenceEndpoint,
        served_model_name: str,
        sample_index: int,
        warmup: bool,
        telemetry_enabled: bool = True,
    ) -> BenchmarkSample:
        started_at = utc_now_text()
        started_ns = time.perf_counter_ns()
        stop_telemetry = asyncio.Event()
        telemetry: list[BenchmarkTelemetryPoint] = []
        telemetry_task = (
            asyncio.create_task(
                self._sample_telemetry(
                    telemetry,
                    stop_telemetry,
                    started_ns=started_ns,
                    interval_seconds=spec.telemetry_interval_ms / 1000,
                )
            )
            if telemetry_enabled
            else None
        )
        first_token_ns: int | None = None
        response_headers_ns: int | None = None
        first_event_ns: int | None = None
        first_token_timings: dict[str, Any] = {}
        output_parts: list[str] = []
        timings: dict[str, Any] = {}
        usage: dict[str, Any] = {}
        finish_reason = ""
        try:
            payload = {
                "model": served_model_name,
                "messages": [{"role": "user", "content": spec.prompt}],
                "stream": True,
                "temperature": spec.temperature,
                "max_tokens": spec.max_output_tokens,
                "seed": spec.seed,
                "cache_prompt": spec.prompt_cache_mode != "cold",
                "timings_per_token": True,
            }
            async with client.stream(
                "POST",
                endpoint.endpoint("/chat/completions"),
                json=payload,
            ) as response:
                response_headers_ns = time.perf_counter_ns()
                response.raise_for_status()
                async for line in response.aiter_lines():
                    data = _sse_payload(line)
                    if data is None:
                        continue
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if first_event_ns is None:
                        first_event_ns = time.perf_counter_ns()
                    if isinstance(chunk.get("timings"), dict):
                        timings = dict(chunk["timings"])
                    if isinstance(chunk.get("usage"), dict):
                        usage = dict(chunk["usage"])
                    choice = _first_choice(chunk)
                    if choice is None:
                        continue
                    finish_reason = str(choice.get("finish_reason") or finish_reason)
                    delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                    visible = _visible_delta(delta)
                    if visible and first_token_ns is None:
                        first_token_ns = time.perf_counter_ns()
                        first_token_timings = dict(timings)
                    for key in ("reasoning_content", "content"):
                        text = delta.get(key)
                        if isinstance(text, str):
                            output_parts.append(text)
            completed_ns = time.perf_counter_ns()
            return _completed_sample(
                sample_index=sample_index,
                warmup=warmup,
                started_at=started_at,
                started_ns=started_ns,
                response_headers_ns=response_headers_ns,
                first_event_ns=first_event_ns,
                first_token_ns=first_token_ns,
                completed_ns=completed_ns,
                timings=timings,
                first_token_timings=first_token_timings,
                usage=usage,
                output_text="".join(output_parts),
                finish_reason=finish_reason,
                telemetry=telemetry,
            )
        except Exception as exc:
            return BenchmarkSample(
                sample_index=sample_index,
                warmup=warmup,
                started_at=started_at,
                status="failed",
                end_to_end_ms=_elapsed_ms(started_ns, time.perf_counter_ns()),
                telemetry=telemetry,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            stop_telemetry.set()
            if telemetry_task is not None:
                await telemetry_task

    async def _sample_telemetry(
        self,
        target: list[BenchmarkTelemetryPoint],
        stop: asyncio.Event,
        *,
        started_ns: int,
        interval_seconds: float,
    ) -> None:
        while True:
            payload = await _remote_json("/runtime/rocm")
            devices = payload.get("devices") if isinstance(payload, dict) else None
            device = devices[0] if isinstance(devices, list) and devices else None
            if isinstance(device, dict):
                target.append(
                    BenchmarkTelemetryPoint(
                        elapsed_ms=_elapsed_ms(started_ns, time.perf_counter_ns()),
                        used_memory_bytes=_optional_int(device.get("used_memory_bytes")),
                        gpu_utilization_percent=_optional_float(
                            device.get("gpu_utilization_percent")
                        ),
                        memory_activity_percent=_optional_float(
                            device.get("memory_activity_percent")
                        ),
                        power_watts=_optional_float(device.get("power_watts")),
                        temperature_celsius=_optional_float(
                            device.get("temperature_hotspot_celsius")
                        ),
                    )
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
                return
            except TimeoutError:
                continue

    async def _environment(self, profile_id: str) -> dict[str, Any]:
        profile = ModelPoolStore().require_profile(profile_id)
        models_payload, rocm_payload, software_payload = await asyncio.gather(
            _remote_json("/models"),
            _remote_json("/runtime/rocm"),
            _remote_json("/runtime/software"),
        )
        models = models_payload.get("models") if isinstance(models_payload, dict) else []
        selected_model = next(
            (
                item
                for item in models
                if isinstance(item, dict)
                and str(item.get("model_id") or "") == profile.served_model_name
            ),
            {},
        )
        return {
            "profile": profile.model_dump(mode="json"),
            "remote_model": selected_model,
            "rocm": rocm_payload,
            "software": software_payload,
        }


async def _remote_json(path: str) -> dict[str, Any]:
    endpoint = load_inference_telemetry_endpoint(timeout_seconds=5.0)
    try:
        async with create_private_async_http_client(endpoint) as client:
            response = await client.get(endpoint.endpoint(path))
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except (httpx.HTTPError, ValueError):
        return {}


async def _active_benchmark_implementation() -> BenchmarkImplementation:
    status = await InferenceNodeClient().llama_implementation()
    active_build = status.active_build
    if not status.available or active_build is None:
        raise ValueError(status.error or "the inference node did not report an active llama.cpp implementation")
    label = str(active_build.display_name or active_build.implementation).strip()
    revision = active_build.source_revision.strip()
    if not label or not revision:
        raise ValueError("the active llama.cpp implementation metadata is incomplete")
    return BenchmarkImplementation(
        label=label,
        revision=revision,
        parameters={
            "implementation": active_build.implementation,
            "source_sha256": active_build.source_sha256,
            "binary_sha256": active_build.binary_sha256,
            "benchmark_binary_sha256": active_build.benchmark_binary_sha256,
            "kernel_catalog_sha256": active_build.kernel_catalog_sha256,
            "custom_kernels": active_build.custom_kernels,
            "optimization_status": active_build.optimization_status,
            "build_options": active_build.build_options,
            "built_at": active_build.built_at,
        },
    )


def _sse_payload(line: str) -> str | None:
    text = line.strip()
    if not text or text.startswith(":") or not text.startswith("data:"):
        return None
    return text[5:].strip()


def _first_choice(chunk: dict[str, Any]) -> dict[str, Any] | None:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    return choices[0]


def _visible_delta(delta: dict[str, Any]) -> bool:
    for key in ("content", "reasoning_content"):
        value = delta.get(key)
        if isinstance(value, str) and value:
            return True
    tool_calls = delta.get("tool_calls")
    return isinstance(tool_calls, list) and bool(tool_calls)


def _completed_sample(
    *,
    sample_index: int,
    warmup: bool,
    started_at: str,
    started_ns: int,
    response_headers_ns: int | None,
    first_event_ns: int | None,
    first_token_ns: int | None,
    completed_ns: int,
    timings: dict[str, Any],
    first_token_timings: dict[str, Any],
    usage: dict[str, Any],
    output_text: str,
    finish_reason: str,
    telemetry: list[BenchmarkTelemetryPoint],
) -> BenchmarkSample:
    prompt_tokens, cache_tokens = _prompt_token_counts(timings, usage)
    ttft_ms = _elapsed_ms(started_ns, first_token_ns) if first_token_ns else None
    first_prompt_ms = _optional_float(first_token_timings.get("prompt_ms"))
    first_decode_ms = _optional_float(first_token_timings.get("predicted_ms"))
    model_compute_ttft_ms = (
        first_prompt_ms + first_decode_ms
        if first_prompt_ms is not None and first_decode_ms is not None
        else None
    )
    gpu_usage = _values(telemetry, "gpu_utilization_percent")
    power = _values(telemetry, "power_watts")
    temperatures = _values(telemetry, "temperature_celsius")
    vram = [point.used_memory_bytes for point in telemetry if point.used_memory_bytes is not None]
    draft_tokens = _optional_int(timings.get("draft_n"))
    accepted_draft_tokens = _optional_int(timings.get("draft_n_accepted"))
    return BenchmarkSample(
        sample_index=sample_index,
        warmup=warmup,
        started_at=started_at,
        ttft_ms=ttft_ms,
        request_to_headers_ms=(
            _elapsed_ms(started_ns, response_headers_ns) if response_headers_ns else None
        ),
        first_event_ms=_elapsed_ms(started_ns, first_event_ns) if first_event_ns else None,
        model_compute_ttft_ms=model_compute_ttft_ms,
        first_token_decode_ms=first_decode_ms,
        outside_model_compute_ms=(
            max(0.0, ttft_ms - model_compute_ttft_ms)
            if ttft_ms is not None and model_compute_ttft_ms is not None
            else None
        ),
        end_to_end_ms=_elapsed_ms(started_ns, completed_ns),
        prompt_tokens=prompt_tokens,
        completion_tokens=_optional_int(
            _first_defined(timings.get("predicted_n"), usage.get("completion_tokens"))
        ),
        cache_tokens=cache_tokens,
        prompt_ms=_optional_float(timings.get("prompt_ms")),
        decode_ms=_optional_float(timings.get("predicted_ms")),
        prompt_tokens_per_second=_optional_float(timings.get("prompt_per_second")),
        decode_tokens_per_second=_optional_float(timings.get("predicted_per_second")),
        draft_tokens=draft_tokens,
        accepted_draft_tokens=accepted_draft_tokens,
        draft_acceptance_rate_percent=(
            accepted_draft_tokens / draft_tokens * 100
            if draft_tokens and accepted_draft_tokens is not None
            else None
        ),
        peak_vram_bytes=max(vram) if vram else None,
        average_gpu_utilization_percent=fmean(gpu_usage) if gpu_usage else None,
        peak_gpu_utilization_percent=max(gpu_usage) if gpu_usage else None,
        average_power_watts=fmean(power) if power else None,
        peak_power_watts=max(power) if power else None,
        peak_temperature_celsius=max(temperatures) if temperatures else None,
        output_text=output_text,
        finish_reason=finish_reason,
        telemetry=telemetry,
    )


def _summarize(samples: list[BenchmarkSample]) -> BenchmarkSummary:
    measured = [sample for sample in samples if not sample.warmup]
    successful = [sample for sample in measured if sample.status == "completed"]
    return BenchmarkSummary(
        measured_samples=len(measured),
        successful_samples=len(successful),
        ttft_ms=_stats(successful, "ttft_ms"),
        request_to_headers_ms=_stats(successful, "request_to_headers_ms"),
        first_event_ms=_stats(successful, "first_event_ms"),
        model_compute_ttft_ms=_stats(successful, "model_compute_ttft_ms"),
        first_token_decode_ms=_stats(successful, "first_token_decode_ms"),
        outside_model_compute_ms=_stats(successful, "outside_model_compute_ms"),
        end_to_end_ms=_stats(successful, "end_to_end_ms"),
        prompt_ms=_stats(successful, "prompt_ms"),
        decode_ms=_stats(successful, "decode_ms"),
        prompt_tokens_per_second=_stats(successful, "prompt_tokens_per_second"),
        decode_tokens_per_second=_stats(successful, "decode_tokens_per_second"),
        peak_vram_bytes=_stats(successful, "peak_vram_bytes"),
        average_gpu_utilization_percent=_stats(
            successful, "average_gpu_utilization_percent"
        ),
        peak_gpu_utilization_percent=_stats(successful, "peak_gpu_utilization_percent"),
        average_power_watts=_stats(successful, "average_power_watts"),
        peak_power_watts=_stats(successful, "peak_power_watts"),
        prompt_cache=_prompt_cache_summary(successful),
        speculative_decoding=_speculative_decoding_summary(successful),
    )


def _speculative_decoding_summary(
    samples: list[BenchmarkSample],
) -> BenchmarkSpeculativeDecodingSummary | None:
    reported = [sample for sample in samples if sample.draft_tokens is not None]
    if not reported:
        return None
    draft_tokens = sum(sample.draft_tokens or 0 for sample in reported)
    accepted_draft_tokens = sum(sample.accepted_draft_tokens or 0 for sample in reported)
    return BenchmarkSpeculativeDecodingSummary(
        draft_tokens=draft_tokens,
        accepted_draft_tokens=accepted_draft_tokens,
        acceptance_rate_percent=(
            accepted_draft_tokens / draft_tokens * 100 if draft_tokens else 0
        ),
    )


def _prompt_cache_summary(
    samples: list[BenchmarkSample],
) -> BenchmarkPromptCacheSummary | None:
    reported = [
        sample
        for sample in samples
        if sample.prompt_tokens is not None and sample.cache_tokens is not None
    ]
    if not reported:
        return None
    prompt_tokens = sum(sample.prompt_tokens or 0 for sample in reported)
    cached_tokens = sum(sample.cache_tokens or 0 for sample in reported)
    return BenchmarkPromptCacheSummary(
        metric_version="prompt_prefix_reuse.v1",
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        processed_tokens=prompt_tokens - cached_tokens,
        hit_rate_percent=(cached_tokens / prompt_tokens * 100) if prompt_tokens else 0,
    )


def _stats(samples: list[BenchmarkSample], field_name: str) -> BenchmarkMetricStats | None:
    values = [
        float(value)
        for sample in samples
        if (value := getattr(sample, field_name)) is not None and math.isfinite(float(value))
    ]
    if not values:
        return None
    ordered = sorted(values)
    return BenchmarkMetricStats(
        count=len(ordered),
        mean=fmean(ordered),
        minimum=ordered[0],
        maximum=ordered[-1],
        p50=_percentile(ordered, 0.50),
        p95=_percentile(ordered, 0.95),
        standard_deviation=pstdev(ordered),
    )


def _percentile(values: list[float], ratio: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _values(points: list[BenchmarkTelemetryPoint], field_name: str) -> list[float]:
    return [
        float(value)
        for point in points
        if (value := getattr(point, field_name)) is not None and math.isfinite(float(value))
    ]


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _usage_cached_tokens(usage: dict[str, Any]) -> Any:
    details = usage.get("prompt_tokens_details")
    return details.get("cached_tokens") if isinstance(details, dict) else None


def _prompt_token_counts(
    timings: dict[str, Any],
    usage: dict[str, Any],
) -> tuple[int | None, int | None]:
    processed_tokens = _optional_int(timings.get("prompt_n"))
    cache_tokens = _optional_int(
        _first_defined(timings.get("cache_n"), _usage_cached_tokens(usage))
    )
    prompt_tokens = _optional_int(usage.get("prompt_tokens"))
    if prompt_tokens is None and processed_tokens is not None:
        prompt_tokens = processed_tokens + (cache_tokens or 0)
    if prompt_tokens is not None and cache_tokens is not None and cache_tokens > prompt_tokens:
        raise ValueError(
            "llama.cpp reported cached prompt tokens greater than total prompt tokens"
        )
    return prompt_tokens, cache_tokens


def _first_defined(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _elapsed_ms(started_ns: int, completed_ns: int | None) -> float:
    if completed_ns is None:
        return 0.0
    return max(0.0, (completed_ns - started_ns) / 1_000_000)
