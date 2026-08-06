#!/usr/bin/env python3
"""Strict BiGym + AMD 3DGS evaluator for a versioned inference HTTP adapter."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import types
from typing import Any
import uuid

import cv2
import numpy as np
import requests

from episode_recorder import EpisodeRecorder, inspect_episode, json_safe


CAMERA_KEYS = (
    ("head", "rgb_head"),
    ("left_wrist", "rgb_left_wrist"),
    ("right_wrist", "rgb_right_wrist"),
)


class PolicyRequestFailure(RuntimeError):
    """Policy request failure with timing evidence retained for the recorder."""

    def __init__(self, reason: str, detail: str, request_record: dict[str, Any]):
        super().__init__(detail)
        self.reason = reason
        self.request_record = request_record


class RecordingFailure(RuntimeError):
    """A recorder failure that must remain resumable, never a task failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def git_revision(path: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def latency_summary(values: list[float]) -> dict[str, float | None]:
    latencies = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(latencies.mean()) if latencies.size else None,
        "p50": float(np.percentile(latencies, 50)) if latencies.size else None,
        "p95": float(np.percentile(latencies, 95)) if latencies.size else None,
        "maximum": float(latencies.max()) if latencies.size else None,
    }


def policy_health(base_url: str) -> dict[str, Any]:
    """Freeze a provider-neutral inference-service identity into the run."""

    response = requests.get(base_url.rstrip("/") + "/health", timeout=30)
    response.raise_for_status()
    payload = response.json()
    identity = payload.get("policy_identity") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "ok"
        or payload.get("protocol_version") != 2
        or not isinstance(identity, dict)
        or not identity.get("provider")
        or not identity.get("model_id")
        or not identity.get("model_revision")
        or not identity.get("adapter_source_sha256")
    ):
        raise RuntimeError(f"policy health response is not ready: {payload!r}")
    return json_safe(payload)


def simulator_time(mojo: Any) -> float | None:
    try:
        value = float(mojo.data.time)
    except (AttributeError, TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def append_recording_step(
    recorder: EpisodeRecorder,
    record: dict[str, Any],
    camera_frames: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return recorder.append_step(record, camera_frames)
    except Exception as error:
        raise RecordingFailure(f"{type(error).__name__}: {error}") from error


def install_prebuilt_gsplat_backend() -> dict[str, str] | None:
    """Load an existing prebuilt extension without triggering backend JIT rebuild."""

    build_dir_value = os.environ.get("GSPLAT_PREBUILT_DIR")
    if not build_dir_value:
        return None
    build_dir = Path(build_dir_value).resolve()
    shared_object = build_dir / "gsplat_cuda.so"
    if not shared_object.is_file():
        raise RuntimeError(f"prebuilt gsplat extension is missing: {shared_object}")

    from torch.utils.cpp_extension import _import_module_from_library

    native = _import_module_from_library("gsplat_cuda", str(build_dir), True)
    if not hasattr(native, "CameraModelType"):
        raise RuntimeError("prebuilt gsplat extension lacks CameraModelType")
    backend = types.ModuleType("gsplat.cuda._backend")
    backend._C = native  # type: ignore[attr-defined]
    backend.__all__ = ["_C"]
    sys.modules[backend.__name__] = backend
    digest = hashlib.sha256(shared_object.read_bytes()).hexdigest()
    receipt = {"path": str(shared_object), "sha256": digest}
    print(f"GSPLAT_PREBUILT_LOADED {json.dumps(receipt, sort_keys=True)}")
    return receipt


def chw_rgb(observation: dict[str, Any], key: str) -> np.ndarray:
    image = np.asarray(observation[key], dtype=np.uint8)
    if image.ndim != 3 or image.shape[0] != 3:
        raise RuntimeError(f"invalid CHW RGB observation {key}: {image.shape}")
    return np.moveaxis(image, 0, -1)


def encode_png(chw: np.ndarray) -> bytes:
    rgb = np.asarray(chw, dtype=np.uint8).transpose(1, 2, 0)
    ok, buffer = cv2.imencode(".png", rgb[:, :, ::-1])
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return buffer.tobytes()


def save_observation_images(
    observation: dict[str, Any], evidence_dir: Path, episode: int, label: str
) -> list[str]:
    paths: list[str] = []
    for camera_name, key in CAMERA_KEYS:
        path = evidence_dir / f"ep{episode:02d}_{label}_{camera_name}.png"
        rgb = chw_rgb(observation, key)
        if not cv2.imwrite(str(path), rgb[:, :, ::-1]):
            raise RuntimeError(f"failed to write {path}")
        paths.append(str(path))
    return paths


def success_from(env: Any, reward: Any, info: dict[str, Any]) -> bool:
    if reward is not None and float(reward) > 0.5:
        return True
    if info.get("task_success"):
        return True
    success = getattr(env, "success", None)
    if callable(success):
        try:
            return bool(success())
        except Exception:
            return False
    return bool(success)


def classify_exception(error: Exception, stage: str) -> str:
    if isinstance(error, PolicyRequestFailure):
        return error.reason
    message = f"{type(error).__name__}: {error}"
    lowered = message.lower()
    if "visual-shell" in lowered or "gaussian" in lowered or "gsplat" in lowered:
        return "visual_shell_runtime_error"
    if stage == "policy_request":
        if isinstance(error, requests.Timeout):
            return "policy_timeout"
        if isinstance(error, requests.RequestException):
            return "policy_http_error"
        return "policy_payload_error"
    if stage == "env_step":
        return "environment_step_error"
    return "environment_reset_error"


def request_chunk(
    base_url: str,
    prompt: str,
    state16: np.ndarray,
    observation: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    request_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "request_id": request_id,
        "started_at_utc": utc_now(),
        "image_encode_ms": None,
        "http_round_trip_ms": None,
        "server_timing_ms": None,
    }
    encode_started = time.perf_counter()
    try:
        images = [encode_png(observation[key]) for _name, key in CAMERA_KEYS]
    except Exception as error:
        record["image_encode_ms"] = (time.perf_counter() - encode_started) * 1000.0
        raise PolicyRequestFailure(
            "policy_payload_error", f"{type(error).__name__}: {error}", record
        ) from error
    record["image_encode_ms"] = (time.perf_counter() - encode_started) * 1000.0

    request_started = time.perf_counter()
    try:
        response = requests.post(
            base_url.rstrip("/") + "/process_frame",
            data={
                "text": prompt,
                "states": json.dumps(state16.tolist()),
                "request_id": request_id,
            },
            files=[
                ("image", (f"camera-{index}.png", payload, "image/png"))
                for index, payload in enumerate(images)
            ],
            timeout=180,
        )
        record["http_round_trip_ms"] = (
            time.perf_counter() - request_started
        ) * 1000.0
        response.raise_for_status()
    except requests.Timeout as error:
        record["http_round_trip_ms"] = (
            time.perf_counter() - request_started
        ) * 1000.0
        raise PolicyRequestFailure(
            "policy_timeout", f"{type(error).__name__}: {error}", record
        ) from error
    except requests.RequestException as error:
        record["http_round_trip_ms"] = (
            time.perf_counter() - request_started
        ) * 1000.0
        raise PolicyRequestFailure(
            "policy_http_error", f"{type(error).__name__}: {error}", record
        ) from error

    try:
        payload = response.json()
        response_request_id = payload.get("request_id")
        if response_request_id != request_id:
            raise RuntimeError(
                f"policy request id mismatch: sent={request_id} received={response_request_id}"
            )
        server_timing = payload.get("timing_ms")
        required_server_timings = (
            "image_decode",
            "policy_infer",
            "total_before_serialize",
            "serialization_first_pass",
            "server_total_before_final_serialize",
        )
        if not isinstance(server_timing, dict) or any(
            not isinstance(server_timing.get(key), (int, float))
            for key in required_server_timings
        ):
            raise RuntimeError(
                f"policy response lacks required timing contract: {server_timing!r}"
            )
        record["server_timing_ms"] = server_timing
        if "response" not in payload:
            raise RuntimeError(f"policy response missing action chunk: {payload}")
        chunk = np.asarray(payload["response"], dtype=np.float32)
        if chunk.shape != (10, 16):
            raise RuntimeError(f"policy action chunk must be 10x16, got {chunk.shape}")
        if not np.isfinite(chunk).all():
            raise RuntimeError("policy action chunk contains non-finite values")
    except Exception as error:
        raise PolicyRequestFailure(
            "policy_payload_error", f"{type(error).__name__}: {error}", record
        ) from error
    return chunk, record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bigym-root", type=Path, required=True)
    parser.add_argument("--task", default="DishwasherUnloadCutleryLong")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--visual-shell-profile", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--n-episodes", type=int, required=True)
    parser.add_argument("--seed0", type=int, default=0)
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--tag", default="amd-external-inference")
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--restart-interrupted",
        action="store_true",
        help="archive an incomplete episode attempt and replay it from its reset seed",
    )
    args = parser.parse_args()

    if args.n_episodes <= 0:
        parser.error("--n-episodes must be a positive integer")
    if args.max_steps is not None and args.max_steps <= 0:
        parser.error("--max-steps must be a positive integer")
    if args.restart_interrupted and not args.resume:
        parser.error("--restart-interrupted requires --resume")

    gsplat_backend = install_prebuilt_gsplat_backend()
    bigym_root = args.bigym_root.resolve()
    replay_dir = bigym_root / "d" / "replay_generation"
    eval_dir = bigym_root / "d" / "eval"
    sys.path.insert(0, str(replay_dir))
    sys.path.insert(0, str(eval_dir))

    from dim_utils import drop_z, pad_to_16  # type: ignore
    from env_utils import build_env, get_state  # type: ignore
    from tasks import FREQ, TASKS, get_maxstep, resolve_task, task_to_snake  # type: ignore

    task = resolve_task(args.task)
    if task != "DishwasherUnloadCutleryLong":
        raise SystemExit(
            "this evaluation profile currently supports only DishwasherUnloadCutleryLong"
        )
    prompt = TASKS[task]["prompt"]
    max_steps = args.max_steps if args.max_steps is not None else get_maxstep(task)
    task_dir = args.output_dir.resolve() / task_to_snake(task)
    task_dir.mkdir(parents=True, exist_ok=True)
    results_path = task_dir / "results.json"

    previous_results: dict[str, Any] | None = None
    if results_path.exists():
        if not args.resume:
            raise SystemExit(
                f"results already exist; use --resume or a new output directory: {results_path}"
            )
        previous_results = json.loads(results_path.read_text(encoding="utf-8"))
        if previous_results.get("schema_version") != 2:
            raise SystemExit(
                "legacy summary-only results cannot be resumed as a full recording; "
                "use a new output directory"
            )

    run_id = (
        args.run_id
        or (str(previous_results["run_id"]) if previous_results and previous_results.get("run_id") else None)
        or f"{args.tag}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    evaluation_root = Path(__file__).resolve().parents[3]
    code_revisions = {
        "evaluation_repository": git_revision(evaluation_root),
        "bigym": git_revision(bigym_root),
    }
    active_policy_health = policy_health(args.base_url)
    configuration = {
        "run_id": run_id,
        "task": task,
        "prompt": prompt,
        "n_episodes": args.n_episodes,
        "seed0": args.seed0,
        "max_steps": max_steps,
        "fps": float(FREQ),
        "base_url": args.base_url,
        "visual_shell_profile": str(args.visual_shell_profile.resolve()),
        "visual_shell_profile_sha256": hashlib.sha256(
            args.visual_shell_profile.resolve().read_bytes()
        ).hexdigest(),
        "code_revisions": code_revisions,
        "policy_health": active_policy_health,
        "record_mode": "full",
        "camera_videos": [name for name, _key in CAMERA_KEYS],
    }
    configuration_sha256 = hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode("utf-8")
    ).hexdigest()
    episode_provenance = {
        "run_id": run_id,
        "configuration_sha256": configuration_sha256,
        "task": task,
        "policy_health": active_policy_health,
        "code_revisions": code_revisions,
    }

    if previous_results is not None:
        if previous_results.get("configuration_sha256") != configuration_sha256:
            raise SystemExit("resume configuration does not match the existing run")

    episodes_by_index: dict[int, dict[str, Any]] = {
        int(episode["episode_index"]): episode
        for episode in (previous_results or {}).get("episodes", [])
    }
    run_started_at = (previous_results or {}).get("started_at", utc_now())

    def current_shell_status(environment: Any) -> dict[str, Any]:
        shell = getattr(environment, "_visual_shell", None)
        if shell is None:
            return {"enabled": False}
        try:
            return json_safe(shell.status())
        except Exception as error:  # noqa: BLE001
            return {"enabled": True, "status_error": f"{type(error).__name__}: {error}"}

    def build_results(status: str, shell_status: dict[str, Any]) -> dict[str, Any]:
        episodes = [episodes_by_index[index] for index in sorted(episodes_by_index)]
        successful_latencies = [
            float(value)
            for episode in episodes
            if episode.get("recording_status") in {"complete", "failed"}
            for value in episode.get("request_latency_ms", [])
            if value is not None
        ]
        attempt_latencies = [
            float(value)
            for episode in episodes
            if episode.get("recording_status") in {"complete", "failed"}
            for value in episode.get("request_attempt_latency_ms", [])
            if value is not None
        ]
        successes = sum(1 for episode in episodes if episode.get("success"))
        terminal = sum(
            1
            for episode in episodes
            if episode.get("recording_status") in {"complete", "failed"}
        )
        interrupted = sum(
            1 for episode in episodes if episode.get("recording_status") == "interrupted"
        )
        strict_shell_passed = bool(
            shell_status.get("enabled")
            and shell_status.get("rendered_frames", 0) > 0
            and shell_status.get("last_error") is None
            and shell_status.get("status_error") is None
        )
        return {
            "schema_version": 2,
            "status": status,
            "run_id": run_id,
            "started_at": run_started_at,
            "finished_at": utc_now() if status != "benchmark_running" else None,
            "task": task,
            "prompt": prompt,
            "base_url": args.base_url,
            "n_episodes": args.n_episodes,
            "episodes_completed": terminal,
            "seed0": args.seed0,
            "max_steps": max_steps,
            "successes": successes,
            "success_rate": successes / len(episodes) if episodes else 0.0,
            "policy_requests": len(successful_latencies),
            "policy_request_attempts": sum(
                int(episode.get("request_attempts", 0)) for episode in episodes
            ),
            "policy_attempts_with_http_latency": len(attempt_latencies),
            "policy_latency_ms": latency_summary(successful_latencies),
            "policy_attempt_latency_ms": latency_summary(attempt_latencies),
            "recording": {
                "mode": "full",
                "format": "per-episode JSONL plus synchronized three-camera MP4",
                "episodes_terminal": terminal,
                "episodes_interrupted": interrupted,
                "step_records": sum(int(ep.get("step_records", 0)) for ep in episodes),
                "camera_frame_steps": sum(
                    int(ep.get("camera_frame_steps", 0)) for ep in episodes
                ),
                "failed_task_episodes_retained": True,
                "resume_boundary": "completed episodes; incomplete attempts are archived and replayed from reset",
            },
            "configuration": configuration,
            "configuration_sha256": configuration_sha256,
            "code_revisions": code_revisions,
            "policy_health": active_policy_health,
            "visual_shell": {
                "profile": str(args.visual_shell_profile.resolve()),
                "strict": True,
                "runtime_passed": strict_shell_passed,
                "status": shell_status,
                "human_visual_review": "pending",
            },
            "observation_contract": {
                "state_dim": 16,
                "action_chunk_shape": [10, 16],
                "cameras": {
                    "head": [3, 480, 848],
                    "left_wrist": [3, 480, 640],
                    "right_wrist": [3, 480, 640],
                },
            },
            "gsplat_backend": gsplat_backend,
            "episodes": episodes,
        }

    def checkpoint(status: str, environment: Any) -> dict[str, Any]:
        payload = build_results(status, current_shell_status(environment))
        atomic_write_json(results_path, payload)
        return payload

    def archive_incomplete_episode(episode_index: int) -> Path:
        report = inspect_episode(task_dir, episode_index)
        source = Path(report["episode_dir"])
        archive_root = task_dir / "incomplete-attempts"
        archive_root.mkdir(parents=True, exist_ok=True)
        destination = archive_root / (
            f"episode-{episode_index:06d}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        )
        shutil.move(str(source), str(destination))
        return destination

    def recover_terminal_entry(inspection: dict[str, Any]) -> dict[str, Any]:
        """Rebuild the top-level entry from the terminal manifest authority."""

        manifest = inspection.get("manifest", {})
        recovered = manifest.get("result")
        if not isinstance(recovered, dict):
            raise SystemExit(
                f"episode {inspection.get('episode_index')} has no recoverable manifest result"
            )
        if recovered.get("provenance") != episode_provenance:
            raise SystemExit(
                f"episode {inspection.get('episode_index')} provenance does not match this run"
            )
        rebuilt = dict(recovered)
        episode_dir = Path(inspection["episode_dir"])
        rebuilt.update(
            {
                "recording_status": manifest["status"],
                "recording_manifest": str(
                    episode_dir.joinpath("manifest.json").relative_to(task_dir)
                ),
                "step_records": int(manifest["steps"]["count"]),
                "camera_frame_steps": int(
                    manifest["steps"]["camera_frame_steps"]
                ),
                "videos": {
                    camera: manifest["videos"][camera]["final"]
                    for camera, _key in CAMERA_KEYS
                },
            }
        )
        return rebuilt

    env = build_env(
        task,
        render_mode="rgb_array",
        visual_shell_profile=str(args.visual_shell_profile.resolve()),
        visual_shell_strict=True,
    )
    mojo = env.action_mode._mojo
    episodes_executed_this_process = 0

    try:
        for episode_index in range(args.n_episodes):
            seed = args.seed0 + episode_index
            inspection = inspect_episode(task_dir, episode_index, seed=seed)
            if inspection["state"] in {"complete", "failed"}:
                if not args.resume:
                    raise SystemExit(
                        f"episode {episode_index} already exists; use --resume or a new output directory"
                    )
                episodes_by_index[episode_index] = recover_terminal_entry(inspection)
                print(f"episode={episode_index} seed={seed} resume=skip-terminal")
                continue
            if inspection["state"] != "new":
                if not (args.resume and args.restart_interrupted):
                    raise SystemExit(
                        f"episode {episode_index} has an incomplete attempt ({inspection['state']}); "
                        "use --resume --restart-interrupted or a new output directory"
                    )
                archived = archive_incomplete_episode(episode_index)
                episodes_by_index.pop(episode_index, None)
                print(f"episode={episode_index} archived_incomplete={archived}")

            episode_started = time.perf_counter()
            episodes_executed_this_process += 1
            recorder = EpisodeRecorder(
                task_dir,
                episode_index,
                seed,
                float(FREQ),
                fsync=True,
            )
            action_queue: list[np.ndarray] = []
            current_request: dict[str, Any] | None = None
            action_index_in_chunk = 0
            request_latencies: list[float] = []
            request_attempt_latencies: list[float] = []
            request_records: list[dict[str, Any]] = []
            request_count = 0
            request_attempts = 0
            clipped_values = 0
            success = False
            failure_reason: str | None = None
            failure_detail: str | None = None
            final_reward: float | None = None
            final_info: dict[str, Any] = {}
            steps_executed = 0
            initial_images: list[str] = []
            final_images: list[str] = []
            observation: dict[str, Any] | None = None
            observation_record_step_index: int | None = None
            episode_evidence_dir = recorder.episode_dir / "evidence"
            episode_evidence_dir.mkdir(parents=True, exist_ok=True)

            try:
                observation, reset_info = env.reset(seed=seed)
                reset_state = pad_to_16(get_state(env.robot, observation, mojo), task)
                if reset_state.shape != (16,) or not np.isfinite(reset_state).all():
                    raise RuntimeError(
                        f"invalid reset state shape={reset_state.shape} "
                        f"finite={np.isfinite(reset_state).all()}"
                    )
            except Exception as error:
                failure_reason = classify_exception(error, "env_reset")
                failure_detail = f"{type(error).__name__}: {error}"
                entry = {
                    "episode_index": episode_index,
                    "seed": seed,
                    "success": False,
                    "steps_executed": 0,
                    "max_steps": max_steps,
                    "failure_reason": failure_reason,
                    "failure_detail": failure_detail,
                    "request_count": 0,
                    "request_attempts": 0,
                    "request_latency_ms": [],
                    "request_attempt_latency_ms": [],
                    "request_records": [],
                    "initial_images": initial_images,
                    "final_images": [],
                    "wall_time_seconds": time.perf_counter() - episode_started,
                    "provenance": episode_provenance,
                }
                try:
                    recorder.finalize(
                        success=False,
                        result=entry,
                        failure_reason=failure_reason,
                        failure_detail=failure_detail,
                    )
                except Exception as recording_error:
                    raise RecordingFailure(
                        f"reset failure could not be finalized: {recording_error}"
                    ) from recording_error
                episodes_by_index[episode_index] = recover_terminal_entry(
                    inspect_episode(task_dir, episode_index, seed=seed)
                )
                checkpoint("benchmark_running", env)
                continue

            try:
                initial_images = save_observation_images(
                    observation, episode_evidence_dir, episode_index, "step000"
                )
                append_recording_step(
                    recorder,
                    {
                        "record_type": "reset",
                        "env_step_index": -1,
                        "control_time_s": 0.0,
                        "sim_time_s": simulator_time(mojo),
                        "state16": reset_state,
                        "camera_frames_phase": "observation_after_reset",
                        "action16_model": None,
                        "action_env": None,
                        "action_clipped": None,
                        "clip_mask": None,
                        "reward": None,
                        "success": False,
                        "terminated": False,
                        "truncated": False,
                        "info": reset_info,
                        "request": None,
                    },
                    {name: observation[key] for name, key in CAMERA_KEYS},
                )
                observation_record_step_index = recorder.next_step_index - 1
            except RecordingFailure:
                raise
            except Exception as error:
                raise RecordingFailure(
                    f"reset evidence recording failed: {type(error).__name__}: {error}"
                ) from error

            for step in range(max_steps):
                try:
                    state16 = pad_to_16(get_state(env.robot, observation, mojo), task)
                except Exception as error:
                    failure_reason = "invalid_environment_state"
                    failure_detail = f"{type(error).__name__}: {error}"
                    append_recording_step(
                        recorder,
                        {
                            "record_type": "state_error",
                            "env_step_index": step,
                            "control_time_s": step / float(FREQ),
                            "failure_reason": failure_reason,
                            "failure_detail": failure_detail,
                        }
                    )
                    break
                if state16.shape != (16,) or not np.isfinite(state16).all():
                    failure_reason = "invalid_environment_state"
                    failure_detail = (
                        f"state shape={state16.shape} finite={np.isfinite(state16).all()}"
                    )
                    append_recording_step(
                        recorder,
                        {
                            "record_type": "state_error",
                            "env_step_index": step,
                            "control_time_s": step / float(FREQ),
                            "state16": state16,
                            "failure_reason": failure_reason,
                            "failure_detail": failure_detail,
                        }
                    )
                    break

                if not action_queue:
                    request_attempts += 1
                    try:
                        chunk, current_request = request_chunk(
                            args.base_url, prompt, state16, observation
                        )
                    except Exception as error:
                        failure_reason = classify_exception(error, "policy_request")
                        failure_detail = f"{type(error).__name__}: {error}"
                        request_record = getattr(error, "request_record", None)
                        if isinstance(request_record, dict):
                            request_records.append(request_record)
                            attempt_latency = request_record.get("http_round_trip_ms")
                            if attempt_latency is not None:
                                request_attempt_latencies.append(float(attempt_latency))
                        append_recording_step(
                            recorder,
                            {
                                "record_type": "policy_request_error",
                                "env_step_index": step,
                                "control_time_s": step / float(FREQ),
                                "state16": state16,
                                "request": request_record,
                                "failure_reason": failure_reason,
                                "failure_detail": failure_detail,
                            }
                        )
                        break
                    request_count += 1
                    request_records.append(current_request)
                    latency_ms = float(current_request["http_round_trip_ms"])
                    request_latencies.append(latency_ms)
                    request_attempt_latencies.append(latency_ms)
                    action_queue = [row.copy() for row in chunk]
                    action_index_in_chunk = 0

                action16 = np.asarray(action_queue.pop(0), dtype=np.float32)
                action = drop_z(action16, task)
                clipped = np.clip(action, env.action_space.low, env.action_space.high)
                clip_mask = clipped != action
                clipped_values += int(np.count_nonzero(clip_mask))
                sim_time_before = simulator_time(mojo)
                try:
                    next_observation, reward, terminated, truncated, info = env.step(clipped)
                except Exception as error:
                    failure_reason = classify_exception(error, "env_step")
                    failure_detail = f"{type(error).__name__}: {error}"
                    append_recording_step(
                        recorder,
                        {
                            "record_type": "environment_step_error",
                            "env_step_index": step,
                            "control_time_s": step / float(FREQ),
                            "state16": state16,
                            "action16_model": action16,
                            "action_env": action,
                            "action_clipped": clipped,
                            "clip_mask": clip_mask,
                            "request": current_request,
                            "action_index_in_chunk": action_index_in_chunk,
                            "failure_reason": failure_reason,
                            "failure_detail": failure_detail,
                        }
                    )
                    break

                steps_executed = step + 1
                final_reward = None if reward is None else float(reward)
                final_info = dict(info)
                success = success_from(env, reward, info)
                next_state16: np.ndarray | None = None
                state_after_error: str | None = None
                try:
                    candidate_next_state = pad_to_16(
                        get_state(env.robot, next_observation, mojo), task
                    )
                    if candidate_next_state.shape != (16,) or not np.isfinite(
                        candidate_next_state
                    ).all():
                        raise RuntimeError(
                            f"state shape={candidate_next_state.shape} "
                            f"finite={np.isfinite(candidate_next_state).all()}"
                        )
                    next_state16 = candidate_next_state
                except Exception as error:
                    state_after_error = f"{type(error).__name__}: {error}"
                    success = False
                    failure_reason = "invalid_environment_state"
                    failure_detail = state_after_error
                transition_record_step_index = recorder.next_step_index
                append_recording_step(
                    recorder,
                    {
                        "record_type": "transition",
                        "env_step_index": step,
                        "control_time_s": steps_executed / float(FREQ),
                        "state16": state16,
                        "state16_before": state16,
                        "state16_after": next_state16,
                        "state_after_error": state_after_error,
                        "sim_time_s_before": sim_time_before,
                        "sim_time_s_after": simulator_time(mojo),
                        "camera_frames_phase": "observation_after_action",
                        "observation_before_record_step_index": observation_record_step_index,
                        "observation_after_record_step_index": transition_record_step_index,
                        "action16_model": action16,
                        "action_env": action,
                        "action_clipped": clipped,
                        "clip_mask": clip_mask,
                        "reward": final_reward,
                        "success": success,
                        "terminated": bool(terminated),
                        "truncated": bool(truncated),
                        "info": info,
                        "request": current_request,
                        "action_index_in_chunk": action_index_in_chunk,
                    },
                    {name: next_observation[key] for name, key in CAMERA_KEYS},
                )
                observation = next_observation
                observation_record_step_index = transition_record_step_index
                action_index_in_chunk += 1
                if state_after_error is not None:
                    break
                if success:
                    break
                if terminated or truncated:
                    failure_reason = "environment_terminated_without_success"
                    break
            else:
                failure_reason = "max_steps_without_success"

            if not success and failure_reason is None:
                failure_reason = "max_steps_without_success"
            if observation is not None:
                final_images = save_observation_images(
                    observation,
                    episode_evidence_dir,
                    episode_index,
                    f"step{steps_executed:04d}-final",
                )

            entry = {
                "episode_index": episode_index,
                "seed": seed,
                "success": success,
                "steps_executed": steps_executed,
                "max_steps": max_steps,
                "failure_reason": None if success else failure_reason,
                "failure_detail": None if success else failure_detail,
                "request_count": request_count,
                "request_attempts": request_attempts,
                "request_latency_ms": request_latencies,
                "request_attempt_latency_ms": request_attempt_latencies,
                "request_records": request_records,
                "action_values_clipped": clipped_values,
                "final_reward": final_reward,
                "final_task_success": bool(final_info.get("task_success", False)),
                "wall_time_seconds": time.perf_counter() - episode_started,
                "initial_images": initial_images,
                "final_images": final_images,
                "provenance": episode_provenance,
            }
            try:
                recorder.finalize(
                    success=success,
                    result=entry,
                    failure_reason=None if success else failure_reason,
                    failure_detail=None if success else failure_detail,
                )
            except Exception as error:
                raise RecordingFailure(
                    f"recording finalize failed: {type(error).__name__}: {error}"
                ) from error

            episodes_by_index[episode_index] = recover_terminal_entry(
                inspect_episode(task_dir, episode_index, seed=seed)
            )
            checkpoint("benchmark_running", env)
            print(
                f"episode={episode_index} seed={seed} success={success} "
                f"steps={steps_executed} requests={request_count} failure={failure_reason}"
            )
    except BaseException as error:
        active_recorder = locals().get("recorder")
        if isinstance(active_recorder, EpisodeRecorder):
            try:
                active_recorder.interrupt(error)
            except Exception:
                pass
        checkpoint("benchmark_incomplete", env)
        raise
    finally:
        process_shell_status = current_shell_status(env)
        if episodes_executed_this_process == 0 and previous_results is not None:
            shell_status = json_safe(
                previous_results.get("visual_shell", {}).get(
                    "status", process_shell_status
                )
            )
        else:
            shell_status = process_shell_status
        env.close()

    strict_shell_passed = bool(
        shell_status.get("enabled")
        and shell_status.get("rendered_frames", 0) > 0
        and shell_status.get("last_error") is None
        and shell_status.get("status_error") is None
    )
    terminal = sum(
        1
        for episode in episodes_by_index.values()
        if episode.get("recording_status") in {"complete", "failed"}
    )
    interrupted = sum(
        1
        for episode in episodes_by_index.values()
        if episode.get("recording_status") == "interrupted"
    )
    final_status = (
        "benchmark_complete"
        if terminal == args.n_episodes and interrupted == 0
        else "benchmark_incomplete"
    )
    results = build_results(final_status, shell_status)
    atomic_write_json(results_path, results)
    print(json.dumps({key: results[key] for key in ("status", "success_rate", "policy_requests", "policy_latency_ms")}, indent=2))
    print(f"saved {results_path}")

    if results["status"] != "benchmark_complete":
        raise SystemExit(2)
    if not strict_shell_passed:
        raise SystemExit("strict visual-shell runtime gate failed")


if __name__ == "__main__":
    main()
