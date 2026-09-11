"""Local persistent PI0.5 service for multi-episode Radeon evaluation."""

from __future__ import annotations

import atexit
from dataclasses import asdict
import json
from multiprocessing.connection import Client, Connection, Listener
import os
from pathlib import Path
import secrets
import traceback
from typing import Any, Callable, Mapping
import uuid

from .mobile_harness import MobileHarnessConfig
from .mobile_vla_controller import MobileVLAHarnessController


SERVICE_PROTOCOL = "mobile-pi05-persistent-policy-service-v1"


def _reply_ok(result: Any = None) -> dict[str, Any]:
    return {"protocol": SERVICE_PROTOCOL, "ok": True, "result": result}


def _reply_error(exc: Exception) -> dict[str, Any]:
    return {
        "protocol": SERVICE_PROTOCOL,
        "ok": False,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": traceback.format_exc(limit=20),
    }


def dispatch_policy_service_request(
    controller: Any,
    request: Mapping[str, Any],
    *,
    session_id: str,
    episode_index: int,
    description: Mapping[str, Any],
) -> tuple[dict[str, Any], bool, int]:
    """Dispatch one local request and return reply, close flag, episode index."""

    if request.get("protocol") != SERVICE_PROTOCOL:
        raise ValueError("policy service protocol mismatch")
    command = str(request.get("command") or "")
    if command == "describe":
        return _reply_ok(dict(description)), False, episode_index
    if command == "begin_episode":
        controller.reset_runtime_state()
        episode_index += 1
        return (
            _reply_ok(
                {
                    "policy_runtime_session_id": session_id,
                    "policy_runtime_episode_index": episode_index,
                }
            ),
            False,
            episode_index,
        )
    if command == "select":
        action, telemetry = controller.select(**dict(request.get("kwargs") or {}))
        telemetry = dict(telemetry)
        telemetry["policy_runtime_session_id"] = session_id
        telemetry["policy_runtime_episode_index"] = episode_index
        telemetry["persistent_policy_service"] = True
        return _reply_ok({"action": action, "telemetry": telemetry}), False, episode_index
    if command == "set_harness_config":
        payload = dict(request.get("config") or {})
        controller.set_harness_config(MobileHarnessConfig(**payload))
        return _reply_ok(), False, episode_index
    if command == "observe_contact_forces":
        controller.observe_contact_forces(
            float(request["left_force_n"]), float(request["right_force_n"])
        )
        return _reply_ok(), False, episode_index
    if command == "clear_action_chunk":
        controller.clear_action_chunk()
        return _reply_ok(), False, episode_index
    if command == "end_episode":
        controller.reset_runtime_state()
        return _reply_ok(), True, episode_index
    if command == "shutdown":
        return _reply_ok(), True, -1
    raise ValueError(f"unsupported policy service command: {command!r}")


def _serve_connection(
    connection: Connection,
    controller: Any,
    *,
    session_id: str,
    episode_index: int,
    description: Mapping[str, Any],
) -> tuple[bool, int]:
    shutdown = False
    try:
        while True:
            try:
                request = connection.recv()
            except EOFError:
                break
            try:
                reply, close, updated_index = dispatch_policy_service_request(
                    controller,
                    request,
                    session_id=session_id,
                    episode_index=episode_index,
                    description=description,
                )
                episode_index = updated_index
                shutdown = updated_index < 0
            except Exception as exc:
                reply = _reply_error(exc)
                close = False
            connection.send(reply)
            if close:
                break
    finally:
        connection.close()
    return shutdown, episode_index


def serve_mobile_vla(
    checkpoint: Path,
    socket_path: Path,
    ready_path: Path,
    *,
    chunk_execution_protocol: str,
    chunk_execution_steps: int,
    stage_chunk_execution_steps: Mapping[str, int] | None = None,
    controller_factory: Callable[..., Any] = MobileVLAHarnessController,
) -> None:
    if socket_path.exists() or ready_path.exists():
        raise FileExistsError("policy service socket and ready file must be new")
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    ready_path.parent.mkdir(parents=True, exist_ok=True)
    authkey = secrets.token_bytes(32)
    session_id = str(uuid.uuid4())
    controller = controller_factory(
        checkpoint,
        chunk_execution_protocol=chunk_execution_protocol,
        chunk_execution_steps=chunk_execution_steps,
        stage_chunk_execution_steps=stage_chunk_execution_steps,
    )
    description = {
        "protocol": SERVICE_PROTOCOL,
        "checkpoint": str(checkpoint.resolve()),
        "policy_type": str(controller.policy_type),
        "uses_residual_contract": bool(controller.uses_residual_contract),
        "uses_absolute_contract": bool(controller.uses_absolute_contract),
        "training_contract_sha256": controller.training_contract_sha256,
        "chunk_execution_protocol": chunk_execution_protocol,
        "chunk_execution_steps": int(chunk_execution_steps),
        "stage_chunk_execution_steps": (
            dict(stage_chunk_execution_steps)
            if stage_chunk_execution_steps is not None
            else None
        ),
        "policy_runtime_session_id": session_id,
        "server_pid": os.getpid(),
    }
    listener = Listener(str(socket_path), family="AF_UNIX", authkey=authkey)
    ready_payload = {
        **description,
        "socket_path": str(socket_path.resolve()),
        "authkey_hex": authkey.hex(),
    }
    temporary = ready_path.with_name(f".{ready_path.name}.tmp")
    temporary.write_text(
        json.dumps(ready_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(ready_path)
    episode_index = -1
    try:
        while True:
            connection = listener.accept()
            shutdown, episode_index = _serve_connection(
                connection,
                controller,
                session_id=session_id,
                episode_index=episode_index,
                description=description,
            )
            if shutdown:
                break
    finally:
        listener.close()
        for path in (socket_path, ready_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


class MobileVLAServiceClient:
    """Controller-compatible proxy for one episode of a persistent policy."""

    def __init__(self, ready_path: Path, *, expected_checkpoint: Path) -> None:
        ready = json.loads(ready_path.read_text(encoding="utf-8"))
        if ready.get("protocol") != SERVICE_PROTOCOL:
            raise RuntimeError("persistent policy ready-file protocol mismatch")
        if Path(str(ready.get("checkpoint", ""))).resolve() != expected_checkpoint.resolve():
            raise RuntimeError("persistent policy checkpoint does not match evaluation")
        self._connection = Client(
            str(ready["socket_path"]),
            family="AF_UNIX",
            authkey=bytes.fromhex(str(ready["authkey_hex"])),
        )
        self._closed = False
        description = self._request("describe")
        self.policy_type = str(description["policy_type"])
        self.uses_residual_contract = bool(description["uses_residual_contract"])
        self.uses_absolute_contract = bool(description["uses_absolute_contract"])
        self.training_contract_sha256 = description.get("training_contract_sha256")
        self.chunk_execution_protocol = str(description["chunk_execution_protocol"])
        self.chunk_execution_steps = int(description["chunk_execution_steps"])
        self.stage_chunk_execution_steps = description.get("stage_chunk_execution_steps")
        episode = self._request("begin_episode")
        self.policy_runtime_session_id = str(episode["policy_runtime_session_id"])
        self.policy_runtime_episode_index = int(episode["policy_runtime_episode_index"])
        self._queued_steps_remaining = 0
        self._queued_stage: str | None = None
        atexit.register(self.close)

    def _request(self, command: str, **payload: Any) -> Any:
        if self._closed:
            raise RuntimeError("persistent policy connection is closed")
        self._connection.send(
            {"protocol": SERVICE_PROTOCOL, "command": command, **payload}
        )
        reply = self._connection.recv()
        if reply.get("protocol") != SERVICE_PROTOCOL:
            raise RuntimeError("persistent policy reply protocol mismatch")
        if not reply.get("ok"):
            raise RuntimeError(
                f"persistent policy {reply.get('error_type')}: {reply.get('error')}"
            )
        return reply.get("result")

    def select(self, **kwargs: Any) -> tuple[tuple[float, ...], dict[str, Any]]:
        result = self._request("select", kwargs=kwargs)
        telemetry = dict(result["telemetry"])
        self._queued_steps_remaining = int(telemetry.get("chunk_steps_remaining") or 0)
        self._queued_stage = str(telemetry.get("stage") or "")
        return tuple(result["action"]), telemetry

    def has_queued_action(self, stage: str) -> bool:
        return bool(self._queued_steps_remaining > 0 and self._queued_stage == stage)

    def set_harness_config(self, config: MobileHarnessConfig) -> None:
        self._request("set_harness_config", config=asdict(config))

    def observe_contact_forces(self, left_force_n: float, right_force_n: float) -> None:
        self._request(
            "observe_contact_forces",
            left_force_n=float(left_force_n),
            right_force_n=float(right_force_n),
        )

    def clear_action_chunk(self) -> None:
        self._request("clear_action_chunk")
        self._queued_steps_remaining = 0
        self._queued_stage = None

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._request("end_episode")
        finally:
            self._closed = True
            self._connection.close()


def shutdown_mobile_vla_service(ready_path: Path) -> None:
    """Request an orderly shutdown so the server removes its local socket."""

    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    if ready.get("protocol") != SERVICE_PROTOCOL:
        raise RuntimeError("persistent policy ready-file protocol mismatch")
    connection = Client(
        str(ready["socket_path"]),
        family="AF_UNIX",
        authkey=bytes.fromhex(str(ready["authkey_hex"])),
    )
    try:
        connection.send({"protocol": SERVICE_PROTOCOL, "command": "shutdown"})
        reply = connection.recv()
        if not reply.get("ok"):
            raise RuntimeError(f"persistent policy shutdown failed: {reply}")
    finally:
        connection.close()
