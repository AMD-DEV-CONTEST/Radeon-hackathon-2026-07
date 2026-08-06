"""Remote Compute Node abstraction.

BotverseX must run for users who own:
  - only a laptop (no GPU)        → cloud training + cloud inference, or local CPU inference for small models
  - a laptop with a local GPU     → run a sidecar locally on 127.0.0.1
  - a remote GPU box (friend's GB10, a cloud VM, a home server) → run a sidecar there, point BotverseX at it

This module replaces the previous hardcoded assumption that the user has access to
a specific GB10 machine (`dgx-spink` / `192.168.100.106` / `/home/zhouzhigang/outputs/...`).
A "Remote Compute Node" is any HTTP sidecar endpoint + optional SSH target used to
rsync model files there.

Storage: ~/.cache/botversex/remote_compute.json
Schema: { "nodes": [ {id, name, kind, ...}, ... ], "default_node_id": "local" }

Kinds:
  - "local"      : sidecar runs on this laptop. No SSH. sidecar_url=http://127.0.0.1:8010
  - "remote_ssh" : sidecar runs on a remote box reachable via SSH. We rsync models there.
  - "remote_http": sidecar is reachable via HTTP only (e.g. a cloud-hosted inference endpoint).
                   No SSH; models must already be loadable by the sidecar (e.g. HF id).

Accelerator (vendor stack the node is intended to use for train/infer):
  - "auto"  : probe / runtime decides
  - "rocm"  : AMD Radeon + ROCm (PyTorch ROCm)
  - "cuda"  : NVIDIA + CUDA
  - "cpu"   : CPU only

The "local" node is always present and cannot be deleted.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/remote_compute", tags=["remote_compute"])

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path.home() / ".cache" / "botversex"
_CONFIG_FILE = _CONFIG_DIR / "remote_compute.json"

# Legacy env-based defaults, kept for backward compatibility. If a user has been
# relying on BOTVERSEX_PI0_SIDECAR_URL / B601_GB10_SSH without configuring nodes,
# we still honor those envs by folding them into a "legacy_gb10" template node.
_LEGACY_SIDECAR_URL = os.environ.get("BOTVERSEX_PI0_SIDECAR_URL", "").strip()
_LEGACY_SSH_HOST = os.environ.get("B601_GB10_SSH", "").strip()
_LEGACY_REMOTE_DIR = os.environ.get("B601_GB10_REMOTE_DIR", "").strip() or "/home/zhouzhigang/outputs/pi05_icehockey_v1"
_LEGACY_MODEL_PATH = os.environ.get("B601_PI05_MODEL", "").strip() or "/home/zhouzhigang/outputs/pi05_smoke_patched"


def _default_local_node() -> "RemoteComputeNode":
    return RemoteComputeNode(
        id="local",
        name="本机 · AMD ROCm（推荐）",
        kind="local",
        accelerator="rocm",
        sidecar_url="http://127.0.0.1:8010",
        model_root=str(Path.home() / ".cache" / "botversex" / "models"),
        description=(
            "在本机用 AMD Radeon + ROCm 跑训练/推理（source apps/realtime/rocm_env.sh）。"
            "无 GPU 时可改 accelerator=cpu 跑小模型。"
        ),
    )


def _legacy_gb10_template() -> "RemoteComputeNode":
    """Example node mirroring the old hardcoded GB10 config. Disabled by default."""
    return RemoteComputeNode(
        id="gb10_friend_example",
        name="远端 · NVIDIA CUDA（示例，未启用）",
        kind="remote_ssh",
        accelerator="cuda",
        sidecar_url=_LEGACY_SIDECAR_URL or "http://192.168.100.106:8010",
        ssh_host=_LEGACY_SSH_HOST or "dgx-spark",
        ssh_user="zhouzhigang",
        ssh_port=22,
        ssh_jump=None,
        model_root="/home/zhouzhigang/outputs",
        default_model_path="/home/zhouzhigang/outputs/pi05_smoke_patched",
        description="示例：朋友的 GB10 / DGX Spark（NVIDIA CUDA）。按实际机器改 SSH，启用后可选为默认节点。",
        enabled=False,
    )


def _seed_config() -> Dict[str, Any]:
    nodes = [_default_local_node().model_dump(), _legacy_gb10_template().model_dump()]
    return {"nodes": nodes, "default_node_id": "local"}


def _load_config() -> Dict[str, Any]:
    if not _CONFIG_FILE.is_file():
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = _seed_config()
        _CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        return cfg
    try:
        cfg = json.loads(_CONFIG_FILE.read_text())
    except Exception:
        cfg = _seed_config()
    # Always ensure "local" exists and is enabled.
    if not any(n.get("id") == "local" for n in cfg.get("nodes", [])):
        cfg.setdefault("nodes", []).insert(0, _default_local_node().model_dump())
    else:
        for n in cfg["nodes"]:
            if n.get("id") == "local":
                n["enabled"] = True
                n["kind"] = "local"
    # Soft-migrate older configs that predate the accelerator field.
    for n in cfg.get("nodes", []):
        if not n.get("accelerator"):
            if n.get("id") == "local":
                n["accelerator"] = "rocm"
            elif "gb10" in str(n.get("id", "")).lower() or "cuda" in str(n.get("name", "")).lower():
                n["accelerator"] = "cuda"
            else:
                n["accelerator"] = "auto"
    if not cfg.get("default_node_id"):
        cfg["default_node_id"] = "local"
    return cfg


def _save_config(cfg: Dict[str, Any]) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RemoteComputeNode(BaseModel):
    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=120)
    kind: str = Field("local", pattern=r"^(local|remote_ssh|remote_http)$")
    accelerator: str = Field("auto", pattern=r"^(auto|rocm|cuda|cpu)$")
    sidecar_url: str = "http://127.0.0.1:8010"
    # SSH fields (only used when kind == "remote_ssh")
    ssh_host: Optional[str] = None
    ssh_user: Optional[str] = None
    ssh_port: int = 22
    ssh_jump: Optional[str] = None  # e.g. "root@43.156.102.67" for ProxyJump
    # Where model files live on the remote box (or local for "local" kind).
    model_root: str = str(Path.home() / ".cache" / "botversex" / "models")
    # Default model path under this node (used by B601 deploy as the "current model").
    default_model_path: Optional[str] = None
    # Optional: which policy types this sidecar can serve.
    policy_types: List[str] = Field(default_factory=lambda: ["pi05"])
    enabled: bool = True
    description: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class RemoteComputeNodeCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=120)
    kind: str = Field("local", pattern=r"^(local|remote_ssh|remote_http)$")
    accelerator: str = Field("auto", pattern=r"^(auto|rocm|cuda|cpu)$")
    sidecar_url: str = "http://127.0.0.1:8010"
    ssh_host: Optional[str] = None
    ssh_user: Optional[str] = None
    ssh_port: int = 22
    ssh_jump: Optional[str] = None
    model_root: str = str(Path.home() / ".cache" / "botversex" / "models")
    default_model_path: Optional[str] = None
    policy_types: List[str] = Field(default_factory=lambda: ["pi05"])
    enabled: bool = True
    description: str = ""


class RemoteComputeNodeUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    accelerator: Optional[str] = Field(None, pattern=r"^(auto|rocm|cuda|cpu)$")
    sidecar_url: Optional[str] = None
    ssh_host: Optional[str] = None
    ssh_user: Optional[str] = None
    ssh_port: Optional[int] = None
    ssh_jump: Optional[str] = None
    model_root: Optional[str] = None
    default_model_path: Optional[str] = None
    policy_types: Optional[List[str]] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None


class SetDefaultNodeRequest(BaseModel):
    node_id: str


# ---------------------------------------------------------------------------
# Public API for other modules (b601.py, sync_model_to_remote.py)
# ---------------------------------------------------------------------------


def list_nodes() -> List[RemoteComputeNode]:
    cfg = _load_config()
    return [RemoteComputeNode(**n) for n in cfg.get("nodes", [])]


def get_node(node_id: Optional[str]) -> RemoteComputeNode:
    """Resolve a node by id. Falls back to default, then to 'local'."""
    cfg = _load_config()
    nodes = cfg.get("nodes", [])
    if node_id:
        for n in nodes:
            if n.get("id") == node_id:
                return RemoteComputeNode(**n)
        raise HTTPException(404, f"remote compute node not found: {node_id}")
    default_id = cfg.get("default_node_id") or "local"
    for n in nodes:
        if n.get("id") == default_id:
            return RemoteComputeNode(**n)
    # Last resort: local
    for n in nodes:
        if n.get("id") == "local":
            return RemoteComputeNode(**n)
    return _default_local_node()


def get_default_node() -> RemoteComputeNode:
    return get_node(None)


def resolve_sidecar_url(node_id: Optional[str], explicit_url: Optional[str] = None) -> str:
    """Return the sidecar URL to use, honoring an explicit override first."""
    if explicit_url:
        return explicit_url.rstrip("/")
    node = get_node(node_id)
    return (node.sidecar_url or "").rstrip("/")


def resolve_model_path(node_id: Optional[str], explicit_path: Optional[str] = None) -> str:
    """Return the default model path under a node, honoring an explicit override first."""
    if explicit_path:
        return explicit_path.strip()
    node = get_node(node_id)
    if node.default_model_path:
        return node.default_model_path
    # Fall back to <model_root>/pi05_smoke_patched for backward compat
    return str(Path(node.model_root.rstrip("/")) / "pi05_smoke_patched")


def resolve_remote_dir(node_id: Optional[str], explicit_dir: Optional[str] = None) -> str:
    """Return the rsync target dir on a remote node."""
    if explicit_dir:
        return explicit_dir.strip()
    node = get_node(node_id)
    return str(Path(node.model_root.rstrip("/")) / "pi05_icehockey_v1")


def resolve_ssh_target(node_id: Optional[str]) -> Optional[str]:
    """Return 'user@host' for SSH/rsync, or None for local nodes."""
    node = get_node(node_id)
    if node.kind != "remote_ssh":
        return None
    if not node.ssh_host:
        return None
    if node.ssh_user:
        return f"{node.ssh_user}@{node.ssh_host}"
    return node.ssh_host


def resolve_ssh_jump(node_id: Optional[str]) -> Optional[str]:
    node = get_node(node_id)
    if node.kind != "remote_ssh":
        return None
    return node.ssh_jump


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


@router.get("/nodes")
async def list_nodes_endpoint() -> Dict[str, Any]:
    cfg = _load_config()
    return {
        "nodes": cfg.get("nodes", []),
        "default_node_id": cfg.get("default_node_id", "local"),
    }


@router.post("/nodes")
async def create_node(body: RemoteComputeNodeCreate) -> Dict[str, Any]:
    cfg = _load_config()
    if any(n.get("id") == body.id for n in cfg.get("nodes", [])):
        raise HTTPException(409, f"node id already exists: {body.id}")
    node = RemoteComputeNode(**body.model_dump())
    cfg.setdefault("nodes", []).append(node.model_dump())
    _save_config(cfg)
    return {"ok": True, "node": node.model_dump()}


@router.put("/nodes/{node_id}")
async def update_node(node_id: str, body: RemoteComputeNodeUpdate) -> Dict[str, Any]:
    if node_id == "local":
        # Local node: name / accelerator / sidecar / model paths / description editable.
        # Kind and SSH fields are fixed.
        body.kind = "local"
        body.ssh_host = None
        body.ssh_user = None
        body.ssh_port = 22
        body.ssh_jump = None
        body.enabled = True
    cfg = _load_config()
    found = None
    for n in cfg.get("nodes", []):
        if n.get("id") == node_id:
            found = n
            break
    if not found:
        raise HTTPException(404, f"node not found: {node_id}")
    update_data = body.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        if v is not None:
            found[k] = v
    found["updated_at"] = time.time()
    _save_config(cfg)
    return {"ok": True, "node": found}


@router.delete("/nodes/{node_id}")
async def delete_node(node_id: str) -> Dict[str, Any]:
    if node_id == "local":
        raise HTTPException(400, "cannot delete the 'local' node")
    cfg = _load_config()
    before = len(cfg.get("nodes", []))
    cfg["nodes"] = [n for n in cfg.get("nodes", []) if n.get("id") != node_id]
    if cfg.get("default_node_id") == node_id:
        cfg["default_node_id"] = "local"
    _save_config(cfg)
    return {"ok": True, "deleted": before - len(cfg["nodes"])}


@router.post("/default")
async def set_default_node(body: SetDefaultNodeRequest) -> Dict[str, Any]:
    cfg = _load_config()
    if not any(n.get("id") == body.node_id for n in cfg.get("nodes", [])):
        raise HTTPException(404, f"node not found: {body.node_id}")
    cfg["default_node_id"] = body.node_id
    _save_config(cfg)
    return {"ok": True, "default_node_id": body.node_id}


@router.get("/nodes/{node_id}/probe")
async def probe_node(node_id: str) -> Dict[str, Any]:
    """Lightweight health probe: hit sidecar /healthz."""
    import asyncio
    import urllib.error
    import urllib.request

    node = get_node(node_id)
    url = (node.sidecar_url or "").rstrip("/")
    if not url:
        return {"ok": False, "error": "no sidecar_url configured"}

    def _get() -> dict:
        req = urllib.request.Request(f"{url}/healthz", method="GET")
        with urllib.request.urlopen(req, timeout=4) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        data = await asyncio.to_thread(_get)
        return {"ok": True, "sidecar_url": url, **data}
    except urllib.error.URLError as exc:
        return {"ok": False, "sidecar_url": url, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "sidecar_url": url, "error": str(exc)}


# ---------------------------------------------------------------------------
# 本机计算设备探测（M48）
#
# 用户在训练页选 ROCm/CUDA 节点时，看不到节点上到底有没有可用 GPU——
# 选了 ROCm 实际是 CPU 就白选。这里探测「本机」（realtime 所在机器）的
# 实际可用计算设备，供训练页展示。
#
# 安全：gfx1151 栈上 in-process 触碰 torch.cuda 可硬崩解释器（SIGSEGV），
# 探测在隔离子进程里跑，崩了只死子进程（与 setup.py 的 _probe_rocm 同模式）。
# ---------------------------------------------------------------------------

_PROBE_CODE = r"""
import json
out = {"ok": None, "accelerator": "cpu", "device_name": None, "message": "unknown"}
try:
    import torch
except Exception as e:
    out = {"ok": None, "accelerator": "cpu", "device_name": None,
           "message": f"torch not importable: {e}"}
else:
    try:
        if not torch.cuda.is_available():
            out = {"ok": False, "accelerator": "cpu", "device_name": None,
                   "message": "torch.cuda.is_available() is False (CPU only)"}
        else:
            x = torch.randn(4, 4, device="cuda")
            _ = float((x @ x).sum().item())
            name = torch.cuda.get_device_name(0)
            # ROCm 的 torch 把 AMD 卡也报成 cuda；按设备名粗判加速器
            acc = "rocm" if "AMD" in name or "Radeon" in name else "cuda"
            out = {"ok": True, "accelerator": acc, "device_name": name,
                   "message": "CUDA kernel launched successfully"}
    except Exception as e:
        out = {"ok": False, "accelerator": "cpu", "device_name": None,
               "message": f"{type(e).__name__}: {e}"}
print(json.dumps(out, ensure_ascii=True))
"""


@router.get("/device")
async def probe_local_device() -> dict:
    """本机计算设备探测（子进程隔离，返回 ok/accelerator/device_name/message）。

    注意：探测的是 realtime 所在机器（通常是用户本机/服务器），
    远端节点（GB10/云 GPU）无法从这里探测。
    """
    import asyncio
    import subprocess
    import sys

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", _PROBE_CODE],
            capture_output=True,
            text=True,
            timeout=60,
        )
        import json as _json

        return _json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"ok": None, "accelerator": "cpu", "device_name": None,
                "message": f"probe failed: {e}"}
