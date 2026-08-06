#!/usr/bin/env python3
"""Download Qualia/HF model → rsync to a remote compute node → optional sidecar /load.

This is the generic version of the legacy `sync_pi05_to_gb10.py`. The remote
target is configurable via --host / --jump / --remote-dir / --sidecar-url, or
indirectly via --node-id (reads ~/.cache/botversex/remote_compute.json).

For local nodes (kind=local), rsync is a no-op: the HF download lands directly
in the model_root, and the sidecar is expected to load from there.

Examples:
  # Old-style explicit args (still works):
  python scripts/sync_model_to_remote.py --model-id qualia-robotics/pi05-xxx --host dgx-spark --remote-dir /home/zhouzhigang/outputs/pi05_icehockey_v1 --load

  # Node-driven (preferred):
  python scripts/sync_model_to_remote.py --node-id gb10_friend --model-id qualia-robotics/pi05-xxx --load

  # Local node (no rsync, just download + load):
  python scripts/sync_model_to_remote.py --node-id local --model-id qualia-robotics/pi05-xxx --load
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
REALTIME_ROOT = ROOT / "apps" / "realtime"
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(REALTIME_ROOT / "api"))

DEFAULT_HOST = os.environ.get("B601_GB10_SSH", "dgx-spark")
DEFAULT_REMOTE = os.environ.get("B601_GB10_REMOTE_DIR", "/home/zhouzhigang/outputs/pi05_icehockey_v1")
DEFAULT_SIDECAR = os.environ.get("BOTVERSEX_PI0_SIDECAR_URL", "http://192.168.100.106:8010")
DROP_KEYS = {
    "use_relative_actions",
    "relative_exclude_joints",
    "action_feature_names",
    "license",
    "tags",
    "private",
    "repo_id",
    "pretrained_path",
    "push_to_hub",
    "use_amp",
    "use_peft",
}


def _write_status(path: Path | None, **kwargs) -> None:
    if not path:
        return
    payload = {"ts": time.time(), **kwargs}
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _resolve_model_id(job_id: str | None, model_id: str | None) -> str:
    if model_id:
        return model_id.strip()
    if not job_id:
        raise SystemExit("need --model-id or --job-id")
    from app.services import qualia_service as q  # noqa: E402

    st = q.get_training_status(job_id)
    mid = st.get("output_model_id")
    status = (st.get("status") or "").lower()
    if not mid:
        raise SystemExit(
            f"job {job_id} has no output_model_id yet (status={status} phase={st.get('phase')})"
        )
    return str(mid)


def _hf_download(model_id: str, local_dir: Path) -> Path:
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download

        path = snapshot_download(repo_id=model_id, local_dir=str(local_dir))
        return Path(path)
    except Exception:
        pass
    cli = shutil.which("huggingface-cli") or shutil.which("hf")
    if not cli:
        raise SystemExit("huggingface_hub / huggingface-cli not available")
    subprocess.check_call(
        [cli, "download", model_id, "--local-dir", str(local_dir)],
    )
    return local_dir


def _patch_config(model_dir: Path) -> Path:
    cfg_path = model_dir / "config.json"
    if not cfg_path.is_file():
        return model_dir
    cfg = json.loads(cfg_path.read_text())
    changed = False
    for k in DROP_KEYS:
        if k in cfg:
            cfg.pop(k)
            changed = True
    if not changed:
        return model_dir
    patched = model_dir.parent / f"{model_dir.name}_patched"
    patched.mkdir(parents=True, exist_ok=True)
    for f in model_dir.iterdir():
        dest = patched / f.name
        if f.name == "config.json":
            continue
        if dest.exists() or dest.is_symlink():
            continue
        try:
            dest.symlink_to(f.resolve())
        except OSError:
            if f.is_file():
                shutil.copy2(f, dest)
    (patched / "config.json").write_text(json.dumps(cfg, indent=2))
    return patched


def _rsync(local_dir: Path, host: str, remote_dir: str, jump: str | None = None) -> None:
    """rsync local_dir → host:remote_dir. If host is None or 'local', no-op."""
    if not host or host == "local":
        return
    remote = f"{host}:{remote_dir.rstrip('/')}/"
    cmd = ["rsync", "-a", "--info=progress2", f"{str(local_dir).rstrip('/')}/", remote]
    if jump:
        cmd[1:1] = ["-e", f"ssh -J {jump}"]
    subprocess.check_call(cmd)


def _sidecar_load(sidecar_url: str, model_key: str, task_prompt: str) -> dict:
    import urllib.error
    import urllib.request

    payload = json.dumps(
        {
            "model_key": model_key,
            "prefer_device": "cuda",
            "task_prompt": task_prompt,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{sidecar_url.rstrip('/')}/load",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"/load {exc.code}: {detail}") from exc


def _resolve_node(node_id: str | None) -> dict:
    """Load a RemoteComputeNode by id. Returns dict with keys:
    sidecar_url, ssh_target, ssh_jump, remote_dir, is_local.
    """
    if not node_id:
        return {
            "sidecar_url": DEFAULT_SIDECAR,
            "ssh_target": DEFAULT_HOST,
            "ssh_jump": None,
            "remote_dir": DEFAULT_REMOTE,
            "is_local": False,
        }
    try:
        from remote_compute import get_node, resolve_remote_dir, resolve_sidecar_url, resolve_ssh_jump, resolve_ssh_target

        node = get_node(node_id)
        return {
            "sidecar_url": resolve_sidecar_url(node_id, None),
            "ssh_target": resolve_ssh_target(node_id),
            "ssh_jump": resolve_ssh_jump(node_id),
            "remote_dir": resolve_remote_dir(node_id, None),
            "is_local": node.kind == "local",
        }
    except Exception as exc:
        print(f"WARN: could not load node '{node_id}' ({exc}); falling back to env defaults", file=sys.stderr)
        return {
            "sidecar_url": DEFAULT_SIDECAR,
            "ssh_target": DEFAULT_HOST,
            "ssh_jump": None,
            "remote_dir": DEFAULT_REMOTE,
            "is_local": False,
        }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job-id", default=None)
    p.add_argument("--model-id", default=None)
    p.add_argument("--node-id", default=None, help="RemoteComputeNode id (preferred)")
    p.add_argument("--host", default=None, help="SSH target user@host (legacy override)")
    p.add_argument("--jump", default=None, help="SSH ProxyJump host (legacy override)")
    p.add_argument("--remote-dir", default=None, help="Remote model dir (legacy override)")
    p.add_argument("--sidecar-url", default=None, help="Sidecar HTTP URL (legacy override)")
    p.add_argument("--local-cache", default=str(Path.home() / ".cache/botversex/pi05_sync"))
    p.add_argument("--load", action="store_true")
    p.add_argument("--task-prompt", default="冰球游戏，将对方击过来的红色圆盘击回去")
    p.add_argument("--status-file", default="/tmp/b601_pi05_sync_status.json")
    args = p.parse_args()

    status_path = Path(args.status_file) if args.status_file else None
    try:
        node = _resolve_node(args.node_id)
        sidecar_url = (args.sidecar_url or node["sidecar_url"]).rstrip("/")
        remote_dir = args.remote_dir or node["remote_dir"]
        ssh_target = args.host or node["ssh_target"]
        ssh_jump = args.jump or node["ssh_jump"]
        is_local = node["is_local"] and not args.host

        _write_status(status_path, phase="resolve_model", job_id=args.job_id, model_id=args.model_id, node_id=args.node_id)
        model_id = _resolve_model_id(args.job_id, args.model_id)
        print("model_id=", model_id)

        local_root = Path(args.local_cache) / model_id.replace("/", "__")
        _write_status(status_path, phase="download", model_id=model_id, local=str(local_root))
        downloaded = _hf_download(model_id, local_root)
        print("downloaded", downloaded)

        _write_status(status_path, phase="patch", model_id=model_id)
        patched = _patch_config(Path(downloaded))
        print("sync_src", patched)

        if is_local:
            # Local node: the HF download IS the model dir. Skip rsync.
            print("local node — skipping rsync")
            remote_key = str(patched)
        else:
            _write_status(
                status_path,
                phase="rsync",
                model_id=model_id,
                host=ssh_target,
                remote_dir=remote_dir,
            )
            _rsync(patched, ssh_target, remote_dir, jump=ssh_jump)
            print("rsync ok →", f"{ssh_target}:{remote_dir}")
            remote_key = remote_dir.rstrip("/")

        load_result = None
        if args.load:
            _write_status(status_path, phase="load", model_key=remote_key)
            load_result = _sidecar_load(sidecar_url, remote_key, args.task_prompt)
            print("load ok", load_result)

        _write_status(
            status_path,
            phase="done",
            model_id=model_id,
            remote_dir=remote_dir,
            model_key=remote_key,
            load=load_result,
        )
        print("DONE")
        return 0
    except Exception as exc:
        _write_status(status_path, phase="error", error=str(exc))
        print("ERROR", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
