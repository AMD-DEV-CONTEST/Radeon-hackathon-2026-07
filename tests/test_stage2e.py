from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from buildguard.config import (
    CameraConfig,
    CameraPolicyConfig,
    GpuSchedulerConfig,
    RealtimeConfig,
    TemporalRuleConfig,
)
from buildguard.exceptions import ConfigurationError
from buildguard.monitoring.base import (
    BaseHardwareMonitor,
    CompositeMonitor,
    GPUStats,
    HardwareSnapshot,
)
from buildguard.monitoring.dashboard import PerformanceDashboard
from buildguard.realtime.camera_manager import CameraManager
from buildguard.realtime.clip_writer import ClipWriter
from buildguard.realtime.event_engine import EventEngine, InMemoryRealtimeStore
from buildguard.realtime.frame_buffer import BoundedFrameQueue
from buildguard.realtime.sampler import AdaptiveMotionSampler
from buildguard.realtime.schemas import CameraState, SamplingMode, VideoFrame
from buildguard.realtime.source import VideoSource
from buildguard.scheduling.gpu_scheduler import GpuScheduler
from buildguard.scheduling.runtime_gate import (
    GpuAdmissionError,
    GpuInferenceGate,
    MonitoredGpuResourceProvider,
)
from buildguard.scheduling.schemas import GpuResourceState, GpuTask


def _frame(sequence: int, *, key_frame: bool = False) -> VideoFrame:
    return VideoFrame(
        camera_id="camera",
        sequence=sequence,
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_time_seconds=float(sequence),
        image=np.full((8, 8, 3), sequence, dtype=np.uint8),
        key_frame=key_frame,
    )


def test_adaptive_sampling_motion_formula_hysteresis_and_risk_override() -> None:
    sampler = AdaptiveMotionSampler(
        CameraPolicyConfig(
            static_fps=1,
            low_motion_fps=3,
            active_fps=5,
            suspected_fps=9,
            static_motion_threshold=2,
            active_motion_threshold=10,
            hysteresis_frames=2,
        )
    )
    assert sampler.observe(np.zeros((8, 8, 3), dtype=np.uint8)) == 0
    assert sampler.mode == SamplingMode.STATIC

    assert sampler.observe(np.full((8, 8, 3), 5, dtype=np.uint8)) == 5
    assert sampler.mode == SamplingMode.STATIC
    assert sampler.observe(np.full((8, 8, 3), 10, dtype=np.uint8)) == 5
    assert sampler.mode == SamplingMode.LOW_MOTION
    assert sampler.fps == 3

    assert sampler.observe(np.full((8, 8, 3), 30, dtype=np.uint8)) == 20
    assert sampler.mode == SamplingMode.LOW_MOTION
    assert sampler.observe(np.full((8, 8, 3), 50, dtype=np.uint8)) == 20
    assert sampler.mode == SamplingMode.ACTIVE
    assert sampler.fps == 5

    sampler.set_suspected_risk(True)
    assert sampler.mode == SamplingMode.SUSPECTED
    assert sampler.fps == 9
    sampler.set_suspected_risk(False)
    assert sampler.mode == SamplingMode.ACTIVE


def test_bounded_queue_drops_old_normal_but_preserves_key_frames() -> None:
    frame_queue = BoundedFrameQueue(max_size=2)
    assert frame_queue.put(_frame(1))
    assert frame_queue.put(_frame(2, key_frame=True))
    assert frame_queue.put(_frame(3))
    assert frame_queue.get(timeout=0.01).sequence == 2
    assert frame_queue.get(timeout=0.01).sequence == 3
    assert frame_queue.metrics() == {
        "length": 0,
        "max_size": 2,
        "peak_size": 2,
        "dropped_normal_frames": 1,
        "critical_waits": 0,
    }

    assert frame_queue.put(_frame(4, key_frame=True))
    assert frame_queue.put(_frame(5, key_frame=True))
    assert not frame_queue.put(_frame(6))
    with pytest.raises(TimeoutError, match="Critical frame queue remained full"):
        frame_queue.put(_frame(7, key_frame=True), timeout=0.001)
    assert [frame_queue.get().sequence, frame_queue.get().sequence] == [4, 5]


class _LoopSource(VideoSource):
    def __init__(self, camera_id: str, *, fail_reads: bool = False) -> None:
        super().__init__(camera_id, "usb")
        self.fail_reads = fail_reads
        self.sequence = 0

    def open(self) -> bool:
        self._set_state(CameraState.RUNNING, reset_failures=True)
        return True

    def read(self) -> VideoFrame | None:
        time.sleep(0.005)
        if self.fail_reads:
            raise RuntimeError("isolated synthetic camera error")
        self.sequence += 1
        frame = _frame(self.sequence).model_copy(
            update={
                "camera_id": self.camera_id,
                "captured_at": datetime(2026, 1, 1, tzinfo=UTC)
                + timedelta(seconds=self.sequence),
            }
        )
        self._record_frame(frame)
        return frame

    def reconnect(self) -> bool:
        return self.open()

    def close(self) -> None:
        self._set_state(CameraState.STOPPED)


def _camera_manager(
    tmp_path: Path,
    *,
    max_concurrent: int,
    performance_sink: Any = None,
) -> tuple[CameraManager, dict[str, _LoopSource]]:
    cameras = [
        CameraConfig(camera_id="healthy", source_type="usb", usb_index=0),
        CameraConfig(camera_id="broken", source_type="usb", usb_index=1),
    ]
    config = RealtimeConfig(
        cameras=cameras,
        max_concurrent_cameras=max_concurrent,
        reconnect_initial_seconds=0.01,
        buffer_memory_mb=2,
        inference_queue_size=2,
        event_queue_size=2,
        temporal_rules={
            "helmet_missing": TemporalRuleConfig(m=1, n=2, alpha=0.5)
        },
        camera_policies={
            "healthy": CameraPolicyConfig(
                static_fps=1,
                low_motion_fps=2,
                active_fps=4,
                suspected_fps=8,
                hysteresis_frames=2,
            )
        },
    )
    store = InMemoryRealtimeStore()
    engine = EventEngine(
        store=store,
        writer=ClipWriter(tmp_path / "images", tmp_path / "clips", codec="mp4v", fps=5),
        severity_by_type={},
        cooldown_seconds=5,
        resolve_seconds=2,
        region_iou_threshold=0.4,
        before_seconds=1,
        after_seconds=1,
        save_clips=False,
    )
    sources = {
        "healthy": _LoopSource("healthy"),
        "broken": _LoopSource("broken", fail_reads=True),
    }
    manager = CameraManager(
        config,
        store=store,
        event_engine=engine,
        inference=lambda _: [],
        source_factory=lambda camera: sources[camera.camera_id],
        performance_sink=performance_sink,
    )
    return manager, sources


def test_multi_camera_isolation_registration_policy_and_concurrency(
    tmp_path: Path,
) -> None:
    sink_calls = 0

    def failing_sink(
        _operation: str,
        _duration_ms: float,
        _metrics: dict[str, object],
    ) -> None:
        nonlocal sink_calls
        sink_calls += 1
        raise RuntimeError("isolated performance sink failure")

    manager, _ = _camera_manager(
        tmp_path,
        max_concurrent=2,
        performance_sink=failing_sink,
    )
    try:
        manager.start("broken")
        manager.start("healthy")
        deadline = time.monotonic() + 1
        while sink_calls < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert manager.is_online("healthy")
        assert manager.status("healthy").frames_read > 0
        assert manager.status("healthy").target_fps == 1
        assert manager.status("healthy").current_fps == pytest.approx(1)
        assert sink_calls > 1
        assert manager.camera_policy("healthy").active_fps == 4
        metrics = {item["camera_id"]: item for item in manager.runtime_metrics()}
        assert metrics["healthy"]["worker_threads_alive"] == 3
        assert metrics["healthy"]["inference_queue"]["max_size"] == 2  # type: ignore[index]
        with pytest.raises(ValueError, match="already registered"):
            manager.register(
                CameraConfig(camera_id="healthy", source_type="usb", usb_index=2)
            )
    finally:
        manager.stop_all()

    limited, _ = _camera_manager(tmp_path / "limited", max_concurrent=1)
    try:
        limited.start("healthy")
        with pytest.raises(RuntimeError, match="Maximum concurrent camera"):
            limited.start("broken")
    finally:
        limited.stop_all()


def _task(
    task_id: str,
    task_type: str,
    *,
    memory_mb: float = 100,
    batch_size: int = 1,
) -> GpuTask:
    return GpuTask(
        task_id=task_id,
        task_type=cast(Any, task_type),
        model_name=f"model-{task_id}",
        estimated_latency_ms=10,
        estimated_memory_mb=memory_mb,
        batch_size=batch_size,
    )


def test_gpu_scheduler_priority_defer_unload_and_oom_degradation() -> None:
    scheduler = GpuScheduler(
        GpuSchedulerConfig(
            reserved_vram_mb=100,
            max_gpu_utilization_percent=90,
        )
    )
    scheduler.submit(_task("background", "background_indexing"))
    scheduler.submit(_task("emergency", "emergency_vision"))
    resource = GpuResourceState(
        utilization_percent=10,
        memory_used_mb=100,
        memory_total_mb=1000,
    )
    first = scheduler.next(resource)
    assert first is not None
    assert (first.task_id, first.action) == ("emergency", "execute_gpu")

    busy = GpuResourceState(
        utilization_percent=95,
        memory_used_mb=100,
        memory_total_mb=1000,
    )
    deferred = scheduler.next(busy)
    assert deferred is not None
    assert deferred.action == "defer"
    assert scheduler.queued_task_ids() == ["background"]

    unload_scheduler = GpuScheduler(GpuSchedulerConfig(reserved_vram_mb=100))
    unload_scheduler.submit(_task("vision", "normal_monitoring", memory_mb=300))
    unload = unload_scheduler.next(
        GpuResourceState(
            utilization_percent=20,
            memory_used_mb=900,
            memory_total_mb=1000,
            resident_models={"idle-llm": 500},
        )
    )
    assert unload is not None
    assert unload.action == "execute_gpu"
    assert unload.unload_models == ["idle-llm"]
    assert unload.load_model

    cpu_scheduler = GpuScheduler(GpuSchedulerConfig(reserved_vram_mb=100))
    large = _task("large", "report_generation", memory_mb=800, batch_size=4)
    cpu_scheduler.submit(large)
    fallback = cpu_scheduler.next(
        GpuResourceState(
            utilization_percent=20,
            memory_used_mb=950,
            memory_total_mb=1000,
            resident_models={"small": 50},
        )
    )
    assert fallback is not None
    assert (fallback.action, fallback.effective_batch_size) == ("execute_cpu", 2)
    assert cpu_scheduler.degrade_after_oom(large).effective_batch_size == 2
    minimum = large.model_copy(update={"batch_size": 1})
    assert cpu_scheduler.degrade_after_oom(minimum).action == "execute_cpu"


def test_gpu_runtime_gate_admits_releases_and_cancels_timed_out_work() -> None:
    available = GpuResourceState(
        utilization_percent=20,
        memory_used_mb=100,
        memory_total_mb=1000,
    )
    scheduler = GpuScheduler(GpuSchedulerConfig(reserved_vram_mb=0))
    gate = GpuInferenceGate(
        scheduler,
        lambda: available,
        wait_timeout_seconds=0.1,
        poll_seconds=0.005,
    )
    task = _task("admitted", "normal_monitoring")

    with gate.admit(task) as decision:
        assert decision is not None
        assert decision.action == "execute_gpu"
        assert gate.active_inference == 1

    assert gate.active_inference == 0
    busy_scheduler = GpuScheduler(
        GpuSchedulerConfig(
            reserved_vram_mb=0,
            max_gpu_utilization_percent=50,
        )
    )
    busy_gate = GpuInferenceGate(
        busy_scheduler,
        lambda: available.model_copy(update={"utilization_percent": 100}),
        wait_timeout_seconds=0.02,
        poll_seconds=0.002,
    )
    timed_out = _task("timed-out", "normal_monitoring")
    with pytest.raises(GpuAdmissionError, match="timed out"), busy_gate.admit(timed_out):
        pass
    assert busy_scheduler.queued_task_ids() == []


class _FixedMonitor(BaseHardwareMonitor):
    def snapshot(self) -> HardwareSnapshot:
        return HardwareSnapshot(
            source="amd-smi",
            cpu_percent=12,
            process_memory_mb=128,
            gpus=[
                GPUStats(
                    name="AMD Radeon Test",
                    utilization_percent=70,
                    memory_used_mb=4096,
                    memory_total_mb=8192,
                    temperature_celsius=60,
                    power_watts=120,
                )
            ],
        )


def test_monitored_gpu_resource_provider_caches_command_sampling() -> None:
    class CountingMonitor(_FixedMonitor):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def snapshot(self) -> HardwareSnapshot:
            self.calls += 1
            return super().snapshot()

    monitor = CountingMonitor()
    provider = MonitoredGpuResourceProvider(monitor, cache_seconds=10)

    first = provider()
    second = provider()

    assert first is not None and second is not None
    assert first.memory_total_mb == 8192
    assert monitor.calls == 1


class _DashboardCameras:
    def runtime_metrics(self) -> list[dict[str, object]]:
        return [
            {
                "camera_id": "camera-1",
                "current_fps": 5.0,
                "inference_queue": {"length": 2},
                "event_queue_length": 1,
            }
        ]


def test_dashboard_matches_sources_persists_and_exports(tmp_path: Path) -> None:
    scheduler = GpuScheduler(GpuSchedulerConfig(reserved_vram_mb=0))
    scheduler.next(
        GpuResourceState(
            utilization_percent=70,
            memory_used_mb=4096,
            memory_total_mb=8192,
            resident_models={"vision-model": 2048},
        )
    )
    dashboard = PerformanceDashboard(
        _FixedMonitor(),
        cast(Any, _DashboardCameras()),
        scheduler,
        log_path=tmp_path / "metrics" / "dashboard.jsonl",
        export_dir=tmp_path / "exports",
        workspace_root=tmp_path,
        history_size=10,
        rocm_version="6.2",
    )
    operations = [
        {
            "operation": "vision_inference",
            "duration_ms": 18.5,
            "metrics": {"rgc_before_calls": 4, "rgc_after_calls": 2},
        },
        {
            "operation": "rag_retrieval",
            "duration_ms": 9.0,
            "metrics": {"quantization": "int8", "latency_before_ms": 14},
        },
    ]
    payload = dashboard.payload(
        llm_metrics=[{"ttft_seconds": 0.2, "tokens_per_second": 30.0}],
        operations=operations,
        limit=10,
    )
    sample = payload["samples"][-1]
    gpu = sample["hardware"]["gpus"][0]
    assert gpu["name"] == "AMD Radeon Test"
    assert gpu["utilization_percent"] == 70
    assert gpu["memory_used_mb"] == 4096
    assert sample["video_fps"] == {"camera-1": 5.0}
    assert sample["queue_lengths"] == {
        "camera-1:inference": 2,
        "camera-1:event": 1,
    }
    assert sample["vision_latency_ms"] == 18.5
    assert sample["rag_latency_ms"] == 9.0
    assert payload["rgc_comparison"] == [operations[0]]
    assert payload["quantization_comparison"] == [operations[1]]

    logged = [
        json.loads(line)
        for line in (tmp_path / "metrics" / "dashboard.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert logged[-1]["hardware"]["gpus"][0]["utilization_percent"] == 70

    for export_format in ("json", "csv", "chart"):
        content, media_type, filename = dashboard.export(
            payload,
            cast(Any, export_format),
        )
        assert content
        assert media_type in {"application/json", "text/csv"}
        assert (tmp_path / "exports" / filename).read_bytes() == content

    restored = PerformanceDashboard(
        _FixedMonitor(),
        cast(Any, _DashboardCameras()),
        scheduler,
        log_path=tmp_path / "metrics" / "dashboard.jsonl",
        export_dir=tmp_path / "exports",
        workspace_root=tmp_path,
        history_size=10,
    )
    assert len(restored.history) == 1


def test_camera_policy_rejects_invalid_fps_order() -> None:
    with pytest.raises(ValueError, match="static <= low_motion"):
        CameraPolicyConfig(
            static_fps=4,
            low_motion_fps=3,
            active_fps=5,
            suspected_fps=8,
        )


class _FailingMonitor(BaseHardwareMonitor):
    def snapshot(self) -> HardwareSnapshot:
        raise RuntimeError("synthetic monitor failure")


class _FailingCameras:
    def runtime_metrics(self) -> list[dict[str, object]]:
        raise RuntimeError("synthetic camera metric failure")


def test_dashboard_paths_and_metric_failures_are_contained(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    scheduler = GpuScheduler(GpuSchedulerConfig())
    with pytest.raises(ConfigurationError, match="must remain inside workspace"):
        PerformanceDashboard(
            _FixedMonitor(),
            cast(Any, _DashboardCameras()),
            scheduler,
            log_path=tmp_path / "outside.jsonl",
            export_dir=workspace / "exports",
            workspace_root=workspace,
            history_size=10,
        )

    dashboard = PerformanceDashboard(
        _FailingMonitor(),
        cast(Any, _FailingCameras()),
        scheduler,
        log_path=workspace / "logs" / "dashboard.jsonl",
        export_dir=workspace / "exports",
        workspace_root=workspace,
        history_size=10,
    )
    payload = dashboard.payload(llm_metrics=[], operations=[], limit=10)
    assert payload["samples"][-1]["hardware"]["available"] is False
    assert payload["cameras"] == []

    composite = CompositeMonitor([_FailingMonitor(), _FixedMonitor()])
    snapshot = composite.snapshot()
    assert snapshot.available
    assert snapshot.gpus[0].name == "AMD Radeon Test"
