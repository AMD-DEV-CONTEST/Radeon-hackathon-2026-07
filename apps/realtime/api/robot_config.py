"""Config-driven robot manifest loader.

This is intentionally JSON-based to avoid adding a YAML dependency to the
realtime service. The manifest is the first step toward adding robots by
configuration instead of by scattering constants across routers and pages.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


REALTIME_ROOT = Path(__file__).parent.parent.resolve()
DEFAULT_MANIFEST_PATH = REALTIME_ROOT / "config" / "robots.json"


@lru_cache(maxsize=1)
def load_robot_config() -> dict[str, Any]:
    path = Path(os.environ.get("BOTVERSEX_ROBOTS_CONFIG", str(DEFAULT_MANIFEST_PATH))).expanduser()
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    robots = data.get("robots")
    if not isinstance(robots, list):
        raise ValueError(f"Robot config {path} must contain a robots list")
    return data


def list_robot_manifests() -> list[dict[str, Any]]:
    return list(load_robot_config().get("robots", []))


def list_catalog_robot_manifests() -> list[dict[str, Any]]:
    """Robots visible on the /robots catalog page.

    Hides entries marked `hidden_from_catalog: true` (e.g. B601-DM and bi_b601_dm
    are exposed as variants inside the B601-RS page, not as separate cards).
    """
    return [r for r in list_robot_manifests() if not r.get("hidden_from_catalog")]


def get_robot_manifest(runtime_id: str) -> dict[str, Any]:
    for robot in list_robot_manifests():
        if robot.get("runtime_id") == runtime_id:
            return robot
    available = ", ".join(sorted(str(r.get("runtime_id")) for r in list_robot_manifests()))
    raise KeyError(f"Unknown robot runtime_id={runtime_id!r}. Available: {available}")


def get_service_config(runtime_id: str) -> dict[str, Any]:
    return dict(get_robot_manifest(runtime_id).get("service") or {"kind": "none"})


def get_transport_config(runtime_id: str) -> dict[str, Any]:
    return dict(get_robot_manifest(runtime_id).get("transport") or {"kind": "unknown"})


def manifest_with_runtime_info(manifest: dict[str, Any], runtime_info: Any | None = None) -> dict[str, Any]:
    """Merge static manifest with RuntimeInfo fields when available."""
    out = dict(manifest)
    if runtime_info is None:
        return out
    out.setdefault("runtime_id", getattr(runtime_info, "runtime_id", None))
    out.setdefault("robot_type", getattr(runtime_info, "robot_type", None))
    out.setdefault("display_name", getattr(runtime_info, "display_name", None))
    out.setdefault("joint_names", getattr(runtime_info, "joint_names", None))
    out.setdefault("urdf_url", getattr(runtime_info, "urdf_url", None))
    out["joint_count"] = getattr(runtime_info, "joint_count", len(out.get("joint_names") or []))
    out["supports_telemetry"] = getattr(runtime_info, "supports_telemetry", False)
    camera_sources = getattr(runtime_info, "camera_sources", None) or []
    if camera_sources:
        out["camera_sources"] = [getattr(src, "__dict__", src) for src in camera_sources]
    return out
