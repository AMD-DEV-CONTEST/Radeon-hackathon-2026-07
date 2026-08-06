"""Runtime-scoped robot platform API.

This router is the compatibility layer that turns the static robot manifest
into a platform API. Existing SO-101 and Reachy-specific routes still work,
but new UI can start depending on this stable runtime-scoped shape.
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from .platform_paths import venv_executable
from .robot_config import (
    get_robot_manifest,
    get_service_config,
    get_transport_config,
    list_catalog_robot_manifests,
    list_robot_manifests,
    manifest_with_runtime_info,
)
from .websocket import manager

router = APIRouter(prefix="/api/robots", tags=["robots"])
ws_router = APIRouter(tags=["robots"])

logger = logging.getLogger(__name__)


def _runtime_info(runtime_id: str) -> Any | None:
    try:
        from runtimes import get_runtime_class  # type: ignore

        return get_runtime_class(runtime_id).info
    except Exception:
        return None


def _manifest_or_404(runtime_id: str) -> dict[str, Any]:
    try:
        return get_robot_manifest(runtime_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _reachy_base_url() -> str:
    service = get_service_config("reachy_mini")
    host = os.environ.get("REACHY_MINI_HOST", str(service.get("host") or "127.0.0.1"))
    raw_port = os.environ.get("REACHY_MINI_PORT", str(service.get("port") or 8010))
    try:
        port = int(raw_port)
    except ValueError:
        port = int(service.get("port") or 8010)
    return f"http://{host}:{port}"


async def _forward_reachy_json(
    request: Request,
    method: str,
    path: str,
    *,
    json_body: Any | None = None,
) -> Response:
    params = dict(request.query_params)
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.request(
                method,
                f"{_reachy_base_url()}{path}",
                params=params,
                json=json_body,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "robot_adapter_unreachable",
                "message": f"Cannot reach reachy_mini adapter at {_reachy_base_url()}",
                "hint": "Use POST /api/robots/reachy_mini/service/start first.",
                "error": str(exc),
            },
        ) from exc

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return JSONResponse(status_code=response.status_code, content=response.json())
        except ValueError:
            pass
    return Response(
        status_code=response.status_code,
        content=response.content,
        media_type=content_type or None,
    )


def _so101_state_payload() -> dict[str, Any]:
    latest = manager.latest_data
    if latest is None:
        return {
            "type": "robot_state",
            "robot_id": getattr(manager, "last_robot_id", "so101-001"),
            "runtime_id": "so101",
            "timestamp": time.time(),
            "connected": False,
            "joints": {},
        }
    return {
        "type": "robot_state",
        "robot_id": getattr(manager, "last_robot_id", "so101-001"),
        "runtime_id": "so101",
        "timestamp": latest.timestamp,
        "connected": True,
        "joints": {
            "1": latest.j1,
            "2": latest.j2,
            "3": latest.j3,
            "4": latest.j4,
            "5": latest.j5,
            "6": latest.j6,
        },
        "servo_values": getattr(manager, "last_servo_values", None),
        "telemetry": {
            "temperatures_c": getattr(manager, "last_temperatures", None),
            "currents_ma": getattr(manager, "last_currents", None),
            "voltages_v": getattr(manager, "last_voltages", None),
            "fps_observed": manager.fps_observed(),
        },
    }


def _serial_status(port: str) -> dict[str, Any]:
    path = Path(port)
    return {
        "port": port,
        "exists": path.exists(),
        "readable": os.access(port, os.R_OK) if path.exists() else False,
        "writable": os.access(port, os.W_OK) if path.exists() else False,
    }


def _dependency_python_executable(manifest: dict[str, Any]) -> str:
    service = manifest.get("service") or {}
    if service.get("python_env") == "adapter_venv":
        sdk_path = Path(str(service.get("sdk_path") or "")).expanduser()
        venv_python = venv_executable(sdk_path, "python")
        if venv_python.exists():
            return str(venv_python)
    return sys.executable


def _check_python_modules(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    deps = manifest.get("dependencies") or {}
    modules = deps.get("python_modules") or []
    python_executable = _dependency_python_executable(manifest)
    checks: list[dict[str, Any]] = []
    for module in modules:
        if python_executable == sys.executable:
            ok = importlib.util.find_spec(str(module)) is not None
        else:
            code = f"import importlib.util, sys; sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"
            result = subprocess.run(
                [python_executable, "-c", code],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            ok = result.returncode == 0
        checks.append({"name": module, "ok": ok, "kind": "python_module"})
    return checks


def _check_binaries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    deps = manifest.get("dependencies") or {}
    return [
        {"name": binary, "ok": shutil.which(str(binary)) is not None, "kind": "binary"}
        for binary in (deps.get("binaries") or [])
    ]


def _run_command(cmd: list[str], cwd: Path | None = None, timeout_s: int = 300) -> dict[str, Any]:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_s,
        check=False,
    )
    output = result.stdout or ""
    return {
        "command": cmd,
        "returncode": result.returncode,
        "ok": result.returncode == 0,
        "output": output[-8000:],
    }


def _provision_adapter_venv(manifest: dict[str, Any]) -> dict[str, Any]:
    service = manifest.get("service") or {}
    sdk_path = Path(str(service.get("sdk_path") or "")).expanduser()
    if not sdk_path.exists():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "adapter_sdk_path_missing",
                "message": f"Adapter SDK path does not exist: {sdk_path}",
            },
        )

    venv_dir = sdk_path / ".venv"
    venv_python = venv_dir / "bin" / "python"
    steps: list[dict[str, Any]] = []
    if not venv_python.exists():
        steps.append(_run_command([sys.executable, "-m", "venv", str(venv_dir)], timeout_s=120))
        if not steps[-1]["ok"]:
            return {"ok": False, "policy": "adapter_venv", "venv": str(venv_dir), "steps": steps}

    steps.append(_run_command([
        str(venv_python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-e",
        str(sdk_path),
    ], cwd=sdk_path, timeout_s=600))

    return {
        "ok": all(step["ok"] for step in steps),
        "policy": "adapter_venv",
        "venv": str(venv_dir),
        "python": str(venv_python),
        "steps": steps,
    }


_robots_list_cache: dict[str, Any] | None = None
_robots_list_cache_at: float = 0.0
_ROBOTS_LIST_CACHE_TTL_S = 60.0


@router.get("")
async def list_robots() -> dict[str, Any]:
    global _robots_list_cache, _robots_list_cache_at
    now = time.monotonic()
    if _robots_list_cache and (now - _robots_list_cache_at) < _ROBOTS_LIST_CACHE_TTL_S:
        return _robots_list_cache

    manifests = [
        manifest_with_runtime_info(manifest, _runtime_info(str(manifest.get("runtime_id"))))
        for manifest in list_catalog_robot_manifests()
    ]
    payload = {"schema_version": "botversex.robot-manifest.v0", "robots": manifests}
    _robots_list_cache = payload
    _robots_list_cache_at = now
    return payload


@router.get("/{runtime_id}")
async def get_robot(runtime_id: str) -> dict[str, Any]:
    manifest = _manifest_or_404(runtime_id)
    return manifest_with_runtime_info(manifest, _runtime_info(runtime_id))


@router.get("/{runtime_id}/status")
async def get_robot_status(runtime_id: str) -> Response:
    manifest = _manifest_or_404(runtime_id)
    service = manifest.get("service") or {"kind": "none"}
    if runtime_id == "reachy_mini":
        from .reachy_proxy import get_local_daemon_status

        return await get_local_daemon_status()
    if service.get("kind") == "none":
        return JSONResponse(
            content={
                "runtime_id": runtime_id,
                "service": service,
                "transport": manifest.get("transport"),
                "state": _so101_state_payload() if runtime_id == "so101" else None,
            }
        )
    raise HTTPException(status_code=501, detail=f"Unsupported service kind: {service.get('kind')}")


@router.post("/{runtime_id}/service/start")
async def start_robot_service(runtime_id: str) -> Response:
    manifest = _manifest_or_404(runtime_id)
    service = manifest.get("service") or {"kind": "none"}
    if runtime_id == "reachy_mini":
        from .reachy_proxy import start_local_daemon

        return await start_local_daemon()
    if service.get("kind") == "none":
        return JSONResponse(
            content={
                "ok": True,
                "runtime_id": runtime_id,
                "message": "This robot runtime does not require a managed local service.",
                "service": service,
            }
        )
    raise HTTPException(status_code=501, detail=f"Unsupported service kind: {service.get('kind')}")


@router.post("/{runtime_id}/service/stop")
async def stop_robot_service(runtime_id: str) -> Response:
    manifest = _manifest_or_404(runtime_id)
    service = manifest.get("service") or {"kind": "none"}
    if runtime_id == "reachy_mini":
        from .reachy_proxy import stop_local_daemon

        return await stop_local_daemon()
    if service.get("kind") == "none":
        return JSONResponse(
            content={
                "ok": True,
                "runtime_id": runtime_id,
                "message": "This robot runtime does not run a managed local service.",
                "service": service,
            }
        )
    raise HTTPException(status_code=501, detail=f"Unsupported service kind: {service.get('kind')}")


@router.get("/{runtime_id}/dependencies")
async def get_robot_dependencies(runtime_id: str) -> dict[str, Any]:
    manifest = _manifest_or_404(runtime_id)
    checks = _check_python_modules(manifest) + _check_binaries(manifest)
    return {
        "runtime_id": runtime_id,
        "policy": (manifest.get("dependencies") or {}).get("policy", "workspace_venv"),
        "python": _dependency_python_executable(manifest),
        "checks": checks,
        "ok": all(item["ok"] for item in checks),
        "install_hint": (manifest.get("dependencies") or {}).get("install_hint"),
    }


@router.post("/{runtime_id}/dependencies/provision")
async def provision_robot_dependencies(runtime_id: str) -> dict[str, Any]:
    manifest = _manifest_or_404(runtime_id)
    policy = (manifest.get("dependencies") or {}).get("policy", "workspace_venv")
    if policy == "adapter_venv":
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _provision_adapter_venv, manifest)
    return {
        "ok": True,
        "runtime_id": runtime_id,
        "policy": policy,
        "message": "This runtime uses the workspace environment; no adapter venv provisioning is required.",
    }


@router.get("/{runtime_id}/ports")
async def get_robot_ports(runtime_id: str) -> dict[str, Any]:
    manifest = _manifest_or_404(runtime_id)
    transport = get_transport_config(runtime_id)
    ports = transport.get("ports") or {}
    return {
        "runtime_id": runtime_id,
        "transport": transport,
        "ports": {name: _serial_status(str(port)) for name, port in ports.items()},
    }


@router.get("/{runtime_id}/state")
async def get_robot_state(runtime_id: str, request: Request) -> Response:
    _manifest_or_404(runtime_id)
    if runtime_id == "so101":
        return JSONResponse(content=_so101_state_payload())
    if runtime_id == "reachy_mini":
        return await _forward_reachy_json(request, "GET", "/api/state/full")
    if runtime_id == "b601_rs":
        from .b601 import get_b601_runtime_state

        return JSONResponse(content=await get_b601_runtime_state())
    return await _generic_runtime_state(runtime_id)


async def _generic_runtime_state(runtime_id: str) -> Response:
    """Runtime reader fallback — new robots.json entries get state without editing this file."""
    try:
        from runtimes import get_runtime_class  # type: ignore

        rt_cls = get_runtime_class(runtime_id)
        if hasattr(rt_cls, "create_reader"):
            reader = rt_cls.create_reader()
            payload = await asyncio.to_thread(reader.read_state_snapshot)
            return JSONResponse(content=payload)
    except ValueError:
        pass
    except NotImplementedError:
        pass
    except Exception as exc:
        logger.warning("generic runtime state failed for %s: %s", runtime_id, exc)
    raise HTTPException(status_code=501, detail=f"State endpoint not implemented for {runtime_id}")


@router.post("/{runtime_id}/motor-mode/{mode}")
async def set_robot_motor_mode(runtime_id: str, mode: str, request: Request) -> Response:
    manifest = _manifest_or_404(runtime_id)
    if not (manifest.get("capabilities") or {}).get("motor_mode"):
        raise HTTPException(status_code=404, detail=f"{runtime_id} does not expose motor_mode")
    if runtime_id == "reachy_mini":
        return await _forward_reachy_json(request, "POST", f"/api/motors/set_mode/{mode}")
    raise HTTPException(status_code=501, detail=f"motor_mode not implemented for {runtime_id}")


@router.get("/{runtime_id}/moves")
async def list_robot_moves(runtime_id: str, request: Request) -> Response:
    manifest = _manifest_or_404(runtime_id)
    if not (manifest.get("capabilities") or {}).get("local_moves"):
        raise HTTPException(status_code=404, detail=f"{runtime_id} does not expose local_moves")
    if runtime_id == "reachy_mini":
        return await _forward_reachy_json(request, "GET", "/api/move/local-categories")
    raise HTTPException(status_code=501, detail=f"moves not implemented for {runtime_id}")


@router.post("/{runtime_id}/moves/{move_name}")
async def play_robot_move(runtime_id: str, move_name: str, request: Request) -> Response:
    manifest = _manifest_or_404(runtime_id)
    if not (manifest.get("capabilities") or {}).get("local_moves"):
        raise HTTPException(status_code=404, detail=f"{runtime_id} does not expose local_moves")
    if runtime_id == "reachy_mini":
        return await _forward_reachy_json(request, "POST", f"/api/move/play/local-move/{move_name}")
    raise HTTPException(status_code=501, detail=f"moves not implemented for {runtime_id}")


@router.get("/{runtime_id}/teleop")
async def get_robot_teleop_status(runtime_id: str) -> dict[str, Any]:
    manifest = _manifest_or_404(runtime_id)
    if not (manifest.get("capabilities") or {}).get("teleop"):
        raise HTTPException(status_code=404, detail=f"{runtime_id} does not expose teleop")
    return {
        "runtime_id": runtime_id,
        "supported": True,
        "status_endpoint": "/api/teleop/status",
        "start_endpoint": "/api/teleop/start",
        "stop_endpoint": "/api/teleop/stop",
    }


@router.get("/{runtime_id}/calibration")
async def get_robot_calibration_status(runtime_id: str) -> dict[str, Any]:
    manifest = _manifest_or_404(runtime_id)
    if not (manifest.get("capabilities") or {}).get("calibration"):
        raise HTTPException(status_code=404, detail=f"{runtime_id} does not expose calibration")
    return {
        "runtime_id": runtime_id,
        "supported": True,
        "status_endpoint": "/api/calibrate/status",
        "files_endpoint": "/api/calibrate/files",
        "auto_endpoint": "/api/calibrate/auto",
        "manual_ws": "/ws/calibrate/manual",
    }


@ws_router.websocket("/ws/robots/{runtime_id}/state")
async def websocket_robot_state(websocket: WebSocket, runtime_id: str) -> None:
    _manifest_or_404(runtime_id)
    if runtime_id == "reachy_mini":
        from .reachy_proxy import websocket_reachy_state

        await websocket_reachy_state(websocket)
        return
    if runtime_id == "b601_rs":
        from .b601 import stream_b601_state

        await stream_b601_state(websocket)
        return
    if runtime_id == "so101":
        arm_id = websocket.query_params.get("arm_id", "arm_0")
        client_id = f"robot_state_{runtime_id}_{arm_id}_{int(time.time() * 1000)}"
        await manager.connect_ui(websocket, client_id)
        if client_id in manager.clients:
            manager.clients[client_id]["runtime_id"] = runtime_id
            manager.clients[client_id]["arm_id"] = arm_id
        try:
            await websocket.send_json(_so101_state_payload())
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket, client_id)
        except Exception:
            manager.disconnect(websocket, client_id)
        return

    try:
        from runtimes import get_runtime_class  # type: ignore

        rt_cls = get_runtime_class(runtime_id)
        if hasattr(rt_cls, "create_reader"):
            reader = rt_cls.create_reader()
            await websocket.accept()
            try:
                while True:
                    payload = await asyncio.to_thread(reader.read_state_snapshot)
                    await websocket.send_json(payload)
                    await asyncio.sleep(float(payload.get("stream_interval_s") or 1.0))
            except WebSocketDisconnect:
                pass
            return
    except (ValueError, NotImplementedError):
        pass
    except Exception as exc:
        logger.warning("generic runtime ws failed for %s: %s", runtime_id, exc)

    await websocket.accept()
    await websocket.send_json({
        "type": "robot_error",
        "runtime_id": runtime_id,
        "message": f"State stream not implemented for {runtime_id}",
    })
    await websocket.close()
