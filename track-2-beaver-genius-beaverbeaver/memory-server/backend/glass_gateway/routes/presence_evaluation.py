from __future__ import annotations

import json
from pathlib import Path
import time
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse

from glass_gateway.app_state import app_state
from glass_gateway.auth import auth_registry
from glass_gateway.frontend import frontend_page


router = APIRouter()

SCENARIOS = (
    ("quiet", "silence", "安静静坐，不说话，也不要播放声音。"),
    ("keyboard", "environment_sound", "连续敲键盘或整理桌面，但不要说话。"),
    ("music", "environment_sound", "播放音乐，但不要跟唱或说话。"),
    ("near_speech", "speech", "正常音量连续说话，眼镜与嘴保持正常佩戴距离。"),
    ("far_speech", "speech", "让另一人在约 2–3 米外连续说话，佩戴者保持安静。"),
    ("speech_with_music", "mixed", "播放音乐，同时正常连续说话。"),
    ("two_speakers", "mixed", "两个人自然交谈，允许轮流或短暂重叠。"),
    ("walking", "environment_sound", "佩戴眼镜走动，保留脚步/道路声，但不要说话。"),
)


@router.get("/presence-eval", response_class=HTMLResponse)
async def presence_evaluation_page() -> HTMLResponse:
    page = frontend_page("presence-eval.html")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@router.post("/v1/evaluation/presence/session/start")
async def start_presence_session(authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    status = app_state.device_status.snapshot().get("device") or {}
    if not status.get("connected"):
        raise HTTPException(status_code=409, detail="眼镜未连接")
    if (status.get("battery") or {}).get("external_power") is not False:
        raise HTTPException(status_code=409, detail="请先拔线；插线状态不会采集记忆")
    if not status.get("memory_capture_active"):
        raise HTTPException(status_code=409, detail="眼镜尚未开始连续采集，请等待几秒后重试")

    now_ms = int(time.time() * 1000)
    cursor_ms = now_ms + 15_000
    scenarios = []
    for scenario_id, expected, instruction in SCENARIOS:
        start_ms = cursor_ms
        end_ms = start_ms + 60_000
        scenarios.append(
            {
                "id": scenario_id,
                "expected_presence": expected,
                "instruction": instruction,
                "start_ms": start_ms,
                "end_ms": end_ms,
            }
        )
        cursor_ms = end_ms + 15_000
    session = {
        "schema_version": 1,
        "session_id": f"glasses-presence-{now_ms}-{uuid.uuid4().hex[:8]}",
        "status": "running",
        "created_at_ms": now_ms,
        "scheduled_start_ms": scenarios[0]["start_ms"],
        "scheduled_end_ms": scenarios[-1]["end_ms"],
        "transition_ms": 15_000,
        "scenarios": scenarios,
        "device": status,
    }
    path = _session_root() / f"{session['session_id']}.json"
    _write_json(path, session)
    return {**session, "server_time_ms": now_ms}


@router.get("/v1/evaluation/presence/session/{session_id}")
async def get_presence_session(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    session = _read_session(session_id)
    return {
        **session,
        "server_time_ms": int(time.time() * 1000),
        "device": app_state.device_status.snapshot().get("device"),
    }


@router.post("/v1/evaluation/presence/session/{session_id}/finish")
async def finish_presence_session(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    session = _read_session(session_id)
    now_ms = int(time.time() * 1000)
    ready_at_ms = int(session["scheduled_end_ms"]) + 40_000
    if now_ms < ready_at_ms:
        raise HTTPException(
            status_code=409,
            detail=f"等待最后窗口落盘，还需 {max(1, (ready_at_ms - now_ms + 999) // 1000)} 秒",
        )
    session["status"] = "finished"
    session["finished_at_ms"] = now_ms
    path = _session_root() / f"{session_id}.json"
    _write_json(path, session)
    manifest = _build_private_manifest(session)
    return {
        "status": "finished",
        "session_id": session_id,
        "matched_windows": len(manifest),
        "manifest": str((_session_root() / f"{session_id}.manifest.jsonl").resolve()),
    }


def _build_private_manifest(session: dict[str, Any]) -> list[dict[str, Any]]:
    raw_root = Path(app_state.settings.raw_media_dir).resolve()
    scenarios = list(session.get("scenarios") or [])
    rows: list[dict[str, Any]] = []
    for manifest_path in raw_root.rglob("capsule-manifest.json"):
        try:
            capsule = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        clock = capsule.get("clock") or {}
        start_ms = int(clock.get("window_started_at_ms") or 0)
        end_ms = int(clock.get("window_ended_at_ms") or 0)
        if start_ms <= 0 or end_ms <= start_ms:
            continue
        scenario = next(
            (
                item
                for item in scenarios
                if start_ms >= int(item["start_ms"]) + 3_000
                and end_ms <= int(item["end_ms"]) - 3_000
            ),
            None,
        )
        if scenario is None:
            continue
        technical = capsule.get("technical_window") or {}
        wav_uri = str(technical.get("derived_audio_uri") or "")
        if not wav_uri.startswith("file://"):
            continue
        wav_path = Path(wav_uri[7:])
        if not wav_path.is_file():
            continue
        expected = str(scenario["expected_presence"])
        rows.append(
            {
                "sample_id": f"{session['session_id']}:{scenario['id']}:{capsule.get('window_id')}",
                "dataset": "glasses_presence_private",
                "split": "acceptance",
                "audio_path": str(wav_path.resolve()),
                "reference": "",
                "language": "zh" if expected in {"speech", "mixed"} else "non_speech",
                "metric": "none",
                "duration_ms": end_ms - start_ms,
                "tags": ["real_glasses", str(scenario["id"]), expected],
                "metadata": {
                    "expected_presence": expected,
                    "scenario_id": scenario["id"],
                    "source_manifest": str(manifest_path.resolve()),
                },
            }
        )
    rows.sort(key=lambda item: item["sample_id"])
    path = _session_root() / f"{session['session_id']}.manifest.jsonl"
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows),
        encoding="utf-8",
    )
    return rows


def _authorize(authorization: str | None) -> None:
    if not auth_registry.authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


def _session_root() -> Path:
    root = Path(app_state.settings.raw_media_dir).resolve().parent / "presence-eval"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _read_session(session_id: str) -> dict[str, Any]:
    if not session_id.startswith("glasses-presence-") or "/" in session_id:
        raise HTTPException(status_code=404, detail="session not found")
    path = _session_root() / f"{session_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="session not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
