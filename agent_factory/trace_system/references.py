from __future__ import annotations

from pathlib import Path
from typing import Any


def runtime_trace_ref(
    *,
    recorder: Any | None,
    trace_id: str,
    run_id: str | None = None,
) -> dict[str, str] | None:
    trace_id = str(trace_id or "").strip()
    if not trace_id:
        return None
    ref: dict[str, str] = {"trace_id": trace_id}
    run_id = str(run_id or "").strip()
    if run_id:
        ref["run_id"] = run_id
    manifest = recorder.manifest_for(trace_id) if recorder is not None else None
    if isinstance(manifest, dict):
        for key in ("package_id", "agent_id", "session_id", "producer_type", "status"):
            value = str(manifest.get(key) or "").strip()
            if value:
                ref[key] = value
    store = getattr(recorder, "store", None) if recorder is not None else None
    root = getattr(store, "root", None)
    if root is not None:
        trace_root = Path(root)
        trace_path = trace_root / "runs" / trace_id
        ref["trace_root"] = str(trace_root)
        ref["trace_path"] = str(trace_path)
        ref["manifest_path"] = str(trace_path / "manifest.json")
    return ref
