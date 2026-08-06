"""M27 — 实时语音助手桥接（嵌入式，不开 Gradio 新标签页）.

支持两家兼容 OpenAI Realtime 协议的上游：
- `openai`：OpenAI Realtime API（gpt-realtime，用户自带 OpenAI key）。
- `qwen` ：阿里云百炼 Qwen-Omni-Realtime（用户自带 DashScope key，国内可用）。
  百炼官方文档明确「协议采用和 OpenAI 的 Realtime API 相同的协议风格」，因此这里
  用同一套桥接，只在连接地址 / session.update 形状 / 音频采样率上按 provider 分流。

为什么需要这个模块（vs `reachy_conversation.py` 的 openai_pro 路线）：
- 官方 Conversation App 走「装 HF Space + spawn 子进程 + 开 Gradio 网页」的路子，
  跳出 botversex 自己的 UI，也不认识我们的 customMoves / 动作库。
- 这里改成浏览器麦克风直连一个 WebSocket，本进程原样转发到上游 Realtime API，
  完全嵌在 `ReachyChatTab` 里，而且把模型的 function calling 接到我们已有的
  `/api/reachy/move/*`、`/api/reachy/camera/head-tracker/*` 端点上——语音助手
  能一边聊一边真的让机器人做表情/跳舞/转头，不是纯聊天。

协议（浏览器 <-> 本模块）：
  1. 浏览器建立 WS 连接后，第一帧必须是：
     {"type": "botversex.init", "provider"?: "openai"|"qwen", "api_key": "...",
      "model"?: str, "voice"?: str, "instructions"?: str}
     （key 只在这条内存里转发给上游，不落盘、不进日志——跟 Pro 路线的约定一致）
  2. 之后浏览器发送的事件就是上游 Realtime 的原生事件（`input_audio_buffer.append`
     `conversation.item.create`、`response.create` 等），本模块原样转发给上游。
  3. 上游的事件原样转发回浏览器；但当模型触发 function_call 时，本模块会
     拦截、在本机执行、并把结果自动喂回上游（浏览器不需要知道 tool 怎么跑的），
     同时额外推一条 `botversex.tool_executed` 事件方便前端展示"已执行：xxx"。
  4. 握手成功后本模块会先推一条 `botversex.ready`，带上协商好的输入/输出采样率
     （OpenAI 输入输出都 24kHz；Qwen 输入 16kHz、输出 24kHz），前端据此配置音频。

参考：https://developers.openai.com/api/docs/guides/realtime-websocket
     https://developers.openai.com/api/docs/guides/realtime-conversations
     https://help.aliyun.com/zh/model-studio/realtime
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

ws_router = APIRouter(tags=["reachy-realtime-voice"])

# ---- Provider registry -----------------------------------------------------

OPENAI_REALTIME_WS_BASE = "wss://api.openai.com/v1/realtime"
QWEN_REALTIME_WS_BASE = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"

OPENAI_MODEL_DEFAULT = "gpt-realtime-2.1"
OPENAI_VOICE_DEFAULT = "marin"
OPENAI_VOICES = ["marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"]

# Qwen-Omni-Realtime：flash 便宜快、plus 效果更好。音色见百炼「音色列表」，
# 这里选官方示例里明确用过的几个作为可选项，默认用 Cherry（中文女声）。
QWEN_MODEL_DEFAULT = "qwen3.5-omni-flash-realtime"
QWEN_VOICE_DEFAULT = "Cherry"
QWEN_VOICES = ["Cherry", "Ethan", "Chelsie", "Serena", "Tina", "Dylan"]

# 一次工具调用最多给多久（本地 HTTP 调用，理论上应该在几十毫秒内完成）。
_TOOL_CALL_TIMEOUT_S = 6.0


def _local_api_base() -> str:
    """本进程自己的 HTTP 地址（Local Agent 固定跑在 :8002，见 run_api.py）。"""
    port = os.environ.get("BOTVERSEX_LOCAL_API_PORT", "8002")
    return f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------------------
# 语音助手可调用的工具 —— 复用 copilot_agent_service.py 里已经在用的动作词表，
# 保持语音路线和文字聊天路线认识的动作名字一致。
# ---------------------------------------------------------------------------

REACHY_VOICE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "play_emotion",
        "description": "让 Reachy Mini 播放一个表情动作，比如点头、摇头、开心、生气、惊讶等。",
        "parameters": {
            "type": "object",
            "properties": {
                "emotion": {
                    "type": "string",
                    "enum": [
                        "happy", "sad", "excited", "calm",
                        "angry", "surprised", "yes", "no",
                    ],
                }
            },
            "required": ["emotion"],
        },
    },
    {
        "type": "function",
        "name": "play_dance",
        "description": "让 Reachy Mini 播放一段动作或舞蹈，比如打招呼、挥手、跳舞。",
        "parameters": {
            "type": "object",
            "properties": {
                "dance": {
                    "type": "string",
                    "enum": ["hello", "wave", "nod", "shake", "wiggle", "dance"],
                }
            },
            "required": ["dance"],
        },
    },
    {
        "type": "function",
        "name": "goto_pose",
        "description": "让 Reachy Mini 的头转向某个方向，或者转动身体朝向。角度用弧度表示。",
        "parameters": {
            "type": "object",
            "properties": {
                "yaw": {
                    "type": "number",
                    "description": "头左右转，弧度。负数=转向右边，正数=转向左边。范围约 -0.6~0.6。",
                },
                "pitch": {
                    "type": "number",
                    "description": "头上下转，弧度。负数=抬头，正数=低头。范围约 -0.4~0.4。",
                },
                "roll": {
                    "type": "number",
                    "description": "头侧向倾斜，弧度。范围约 -0.3~0.3。",
                },
                "body_yaw": {
                    "type": "number",
                    "description": "身体转向，弧度。",
                },
            },
        },
    },
    {
        "type": "function",
        "name": "start_head_tracker",
        "description": "开启头部跟踪，让 Reachy Mini 的头自动看着摄像头画面里的人脸。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "stop_head_tracker",
        "description": "关闭头部跟踪。",
        "parameters": {"type": "object", "properties": {}},
    },
]

REACHY_VOICE_INSTRUCTIONS = (
    "你是 Reachy Mini 桌面机器人的语音助手。用简体中文回复，语气活泼、简短、口语化，"
    "像朋友聊天一样，不要长篇大论。如果用户想让机器人做表情、跳舞、转头、看着他们，"
    "请调用对应的工具函数真正去控制机器人，而不是只用语言描述——执行后可以用一两句话"
    "确认一下（比如「好嘞，跟你打个招呼」），不用逐字报告调用细节。"
)


def _resolve_local_api_key(provider: str) -> tuple[str, str]:
    """Fall back to a locally-configured key when the browser didn't supply one.

    Returns (key, source). Order:
      - qwen  : $DASHSCOPE_API_KEY  ->  ~/.bailian/config.json["api_key"]
      - openai: $OPENAI_API_KEY
    Never logs the key; only the source label is surfaced to the client.
    """
    if provider == "qwen":
        env_key = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
        if env_key:
            return env_key, "env:DASHSCOPE_API_KEY"
        try:
            cfg_path = os.path.expanduser("~/.bailian/config.json")
            with open(cfg_path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            cfg_key = str(cfg.get("api_key") or "").strip()
            if cfg_key:
                return cfg_key, "bl-cli"
        except (OSError, json.JSONDecodeError):
            pass
        return "", ""

    env_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if env_key:
        return env_key, "env:OPENAI_API_KEY"
    return "", ""


def _build_session_update(
    provider: str, model: str, voice: str, instructions: str
) -> dict[str, Any]:
    """按 provider 构造 session.update。

    - qwen：百炼用的是 OpenAI *beta* 风格——扁平的 `modalities` / `input_audio_format`
      / `output_audio_format`（输入 16kHz、输出 24kHz PCM）。
    - openai：GA 风格——`output_modalities` + 嵌套的 `audio.input/output.format`。
    两家的 `tools` / `tool_choice` 形状一致（都跟 Chat Completions 的 function 定义相同）。
    """
    if provider == "qwen":
        return {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": voice,
                "instructions": instructions,
                "input_audio_format": "pcm",
                "output_audio_format": "pcm",
                "input_audio_transcription": {"model": "qwen3-asr-flash-realtime"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.1,
                    "prefix_padding_ms": 500,
                    "silence_duration_ms": 900,
                    # Qwen 默认不会自动提交音频并生成回复；缺这两项就会一直
                    # "已连接 · 等待说话" 但你说什么都没反应。
                    "create_response": True,
                    "interrupt_response": True,
                },
                "tools": REACHY_VOICE_TOOLS,
                "tool_choice": "auto",
            },
        }
    # openai GA
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": model,
            "output_modalities": ["audio", "text"],
            "instructions": instructions,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "turn_detection": {"type": "semantic_vad"},
                    "transcription": {"model": "whisper-1"},
                },
                "output": {
                    "format": {"type": "audio/pcm"},
                    "voice": voice,
                },
            },
            "tools": REACHY_VOICE_TOOLS,
            "tool_choice": "auto",
        },
    }


async def _call_local_api(
    method: str, path: str, json_body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """向本进程自己的 /api/reachy/* 端点发请求（跟浏览器打到 Local Agent 是同一套逻辑，
    这样虚拟模式 / 真实机器人分流都自动生效，不用在这里重复判断）。"""
    url = f"{_local_api_base()}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TOOL_CALL_TIMEOUT_S, trust_env=False) as client:
            r = await client.request(method, url, json=json_body)
        try:
            body: Any = r.json()
        except ValueError:
            body = r.text[:200]
        return {"ok": r.status_code < 400, "status": r.status_code, "body": body}
    except httpx.RequestError as exc:
        return {"ok": False, "error": str(exc)}


_DANCE_DATASET = "pollen-robotics/reachy-mini-dances-library"
_EMOTION_DATASET = "pollen-robotics/reachy-mini-emotions-library"
_DEFAULT_DANCE = "polyrhythm_combo"
_DEFAULT_EMOTION = "welcoming1"
_GENERIC_DANCE = frozenset({"dance", "dances", "随便", "跳一个", "跳个舞", "跳舞", "随便跳", "any", "random"})


def _resolve_dance_name(raw: str) -> str:
    move = raw.strip()
    if not move or move.lower() in _GENERIC_DANCE:
        return _DEFAULT_DANCE
    return move


def _resolve_emotion_name(raw: str) -> str:
    aliases = {
        "happy": "laughing1", "开心": "laughing1", "高兴": "laughing1", "笑": "laughing1",
        "welcome": "welcoming1", "欢迎": "welcoming1", "打招呼": "welcoming1",
        "shy": "shy1", "害羞": "shy1",
    }
    key = raw.strip().lower()
    return aliases.get(key, raw.strip() or _DEFAULT_EMOTION)


async def _play_recorded_move(dataset: str, move: str) -> dict[str, Any]:
    from urllib.parse import quote
    path = (
        f"/api/reachy/move/recorded-move-datasets/play/"
        f"{quote(dataset, safe='')}/{quote(move, safe='')}"
    )
    res = await _call_local_api("POST", path)
    if res.get("ok"):
        return res
    return await _call_local_api("POST", f"/api/reachy/move/play/local-move/{move}")


async def _execute_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """执行语音模型触发的 function call，返回给模型看的结果（会被 json 序列化后回填）。"""
    try:
        if name == "play_emotion":
            move = _resolve_emotion_name(str(arguments.get("emotion") or ""))
            if not move:
                return {"ok": False, "error": "missing_emotion"}
            res = await _play_recorded_move(_EMOTION_DATASET, move)
            return {"ok": res.get("ok", False), "played": move, "detail": res.get("body")}

        if name == "play_dance":
            move = _resolve_dance_name(str(arguments.get("dance") or ""))
            if not move:
                return {"ok": False, "error": "missing_dance"}
            res = await _play_recorded_move(_DANCE_DATASET, move)
            return {"ok": res.get("ok", False), "played": move, "detail": res.get("body")}

        if name == "goto_pose":
            body = {
                "head_pose": {
                    "roll": float(arguments.get("roll", 0.0) or 0.0),
                    "pitch": float(arguments.get("pitch", 0.0) or 0.0),
                    "yaw": float(arguments.get("yaw", 0.0) or 0.0),
                },
                "body_yaw": float(arguments.get("body_yaw", 0.0) or 0.0),
                "duration": 1.0,
            }
            res = await _call_local_api("POST", "/api/reachy/move/goto", body)
            return {"ok": res.get("ok", False), "detail": res.get("body")}

        if name == "start_head_tracker":
            res = await _call_local_api("POST", "/api/reachy/camera/head-tracker/start?device=0")
            return {"ok": res.get("ok", False), "detail": res.get("body")}

        if name == "stop_head_tracker":
            res = await _call_local_api("POST", "/api/reachy/camera/head-tracker/stop")
            return {"ok": res.get("ok", False), "detail": res.get("body")}

        return {"ok": False, "error": f"unknown_tool: {name}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice tool call %s(%r) failed: %s", name, arguments, exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# WebSocket bridge
# ---------------------------------------------------------------------------


@ws_router.websocket("/ws/reachy/voice/realtime")
async def ws_reachy_voice_realtime(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        init_raw = await asyncio.wait_for(websocket.receive_text(), timeout=15.0)
        init = json.loads(init_raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await _safe_send(websocket, {"type": "botversex.error", "error": "init_timeout_or_invalid"})
        await websocket.close(code=4000)
        return
    except WebSocketDisconnect:
        return

    if init.get("type") != "botversex.init":
        await _safe_send(websocket, {"type": "botversex.error", "error": "expected_init_frame"})
        await websocket.close(code=4000)
        return

    provider = str(init.get("provider") or "openai").strip().lower()
    if provider not in ("openai", "qwen"):
        provider = "openai"

    api_key = str(init.get("api_key") or "").strip()
    key_source = "client"
    if not api_key:
        # 浏览器没填 key 时，尝试用本机已配置的凭据（环境变量 / bl CLI 登录留下的
        # ~/.bailian/config.json），这样 `bl auth login` 过的用户可以留空直接开始。
        api_key, key_source = _resolve_local_api_key(provider)
    if not api_key:
        key_label = "DashScope (阿里云百炼)" if provider == "qwen" else "OpenAI"
        hint = (
            "，或先在终端跑 `bl auth login` 登录阿里云百炼后留空重试"
            if provider == "qwen"
            else ""
        )
        await _safe_send(websocket, {
            "type": "botversex.error",
            "error": "missing_api_key",
            "message": f"需要填写 {key_label} API Key 才能启动实时语音对话{hint}。",
        })
        await websocket.close(code=4001)
        return

    if provider == "qwen":
        base_url = QWEN_REALTIME_WS_BASE
        model = str(init.get("model") or "").strip() or QWEN_MODEL_DEFAULT
        voice = str(init.get("voice") or "").strip() or QWEN_VOICE_DEFAULT
        input_rate, output_rate = 16000, 24000
    else:
        base_url = OPENAI_REALTIME_WS_BASE
        model = str(init.get("model") or "").strip() or OPENAI_MODEL_DEFAULT
        voice = str(init.get("voice") or "").strip() or OPENAI_VOICE_DEFAULT
        input_rate, output_rate = 24000, 24000

    instructions = str(init.get("instructions") or "").strip() or REACHY_VOICE_INSTRUCTIONS
    upstream_url = f"{base_url}?model={model}"
    session_update = _build_session_update(provider, model, voice, instructions)
    upstream_label = "通义千问 (阿里云百炼)" if provider == "qwen" else "OpenAI Realtime API"

    try:
        async with websockets.connect(
            upstream_url,
            additional_headers={"Authorization": f"Bearer {api_key}"},
            max_size=16 * 1024 * 1024,
        ) as upstream:
            await upstream.send(json.dumps(session_update))

            await _safe_send(websocket, {
                "type": "botversex.ready",
                "provider": provider,
                "model": model,
                "voice": voice,
                "input_sample_rate": input_rate,
                "output_sample_rate": output_rate,
                "key_source": key_source,
            })

            processed_calls: set[str] = set()
            client_to_upstream = asyncio.create_task(_pump_client_to_upstream(websocket, upstream))
            upstream_to_client = asyncio.create_task(
                _pump_upstream_to_client(websocket, upstream, processed_calls)
            )

            done, pending = await asyncio.wait(
                [client_to_upstream, upstream_to_client],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, ConnectionClosed)):
                    logger.warning("reachy voice bridge pump ended with error: %s", exc)

    except WebSocketDisconnect:
        pass
    except (ConnectionClosed, OSError, asyncio.TimeoutError) as exc:
        detail = str(exc) or type(exc).__name__
        await _safe_send(websocket, {
            "type": "botversex.error",
            "error": "upstream_connection_failed",
            "message": f"无法连接 {upstream_label}：{detail}",
        })
    except Exception as exc:  # noqa: BLE001 — covers e.g. websockets.exceptions.InvalidStatus
        # (bad key / bad model name / handshake rejected by upstream) as well as any
        # genuinely unexpected bug — either way the browser needs a clean error,
        # not a hung socket.
        detail = str(exc) or type(exc).__name__
        logger.warning("reachy voice bridge ended with error: %s", detail)
        await _safe_send(websocket, {
            "type": "botversex.error",
            "error": "upstream_connection_failed",
            "message": f"无法连接 {upstream_label}：{detail}",
        })
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def _pump_client_to_upstream(websocket: WebSocket, upstream: Any) -> None:
    """浏览器 -> OpenAI：原样转发（浏览器直接讲 OpenAI Realtime 的原生协议）。"""
    while True:
        msg = await websocket.receive_text()
        await upstream.send(msg)


async def _pump_upstream_to_client(
    websocket: WebSocket, upstream: Any, processed_calls: set[str]
) -> None:
    """上游 -> 浏览器：原样转发，同时拦截 function_call 在本地执行。

    function_call 在不同 provider / 协议版本里出现在不同事件里，这里覆盖：
      - `response.function_call_arguments.done`（beta 直接带 name/call_id/arguments）
      - `response.output_item.done` 里 item.type == function_call（GA）
      - `response.done` 里 response.output[] 扫出 function_call（兜底）
    用 call_id 去重，避免同一次调用被执行多次。
    """
    async for raw in upstream:
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await _safe_send_raw(websocket, raw)
            continue

        for call in _extract_function_calls(event):
            call_id, name, args = call
            if call_id in processed_calls:
                continue
            processed_calls.add(call_id)
            asyncio.create_task(_handle_tool_call(upstream, websocket, call_id, name, args))

        await _safe_send_raw(websocket, raw)


def _extract_function_calls(event: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Pull (call_id, name, args) tuples out of whatever function-call event shape arrived."""
    out: list[tuple[str, str, dict[str, Any]]] = []
    etype = event.get("type")

    def _parse_args(raw_args: Any) -> dict[str, Any]:
        if isinstance(raw_args, dict):
            return raw_args
        try:
            return json.loads(raw_args or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    if etype == "response.function_call_arguments.done":
        call_id = event.get("call_id")
        name = event.get("name")
        if call_id and name:
            out.append((call_id, name, _parse_args(event.get("arguments"))))

    elif etype == "response.output_item.done":
        item = event.get("item") or {}
        if item.get("type") == "function_call" and item.get("call_id") and item.get("name"):
            out.append((item["call_id"], item["name"], _parse_args(item.get("arguments"))))

    elif etype == "response.done":
        for item in (event.get("response") or {}).get("output") or []:
            if isinstance(item, dict) and item.get("type") == "function_call" \
                    and item.get("call_id") and item.get("name"):
                out.append((item["call_id"], item["name"], _parse_args(item.get("arguments"))))

    return out


async def _handle_tool_call(
    upstream: Any, websocket: WebSocket, call_id: str, name: str, args: dict[str, Any]
) -> None:
    result = await _execute_tool_call(name, args)
    try:
        await upstream.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result, ensure_ascii=False),
            },
        }))
        await upstream.send(json.dumps({"type": "response.create"}))
    except (ConnectionClosed, OSError):
        return
    await _safe_send(websocket, {
        "type": "botversex.tool_executed",
        "name": name,
        "arguments": args,
        "result": result,
    })


async def _safe_send(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


async def _safe_send_raw(websocket: WebSocket, raw: str) -> None:
    try:
        await websocket.send_text(raw)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Small HTTP helper — lets the frontend know the default model/voice without
# hardcoding them, and confirms this feature exists (older Local Agent builds
# won't have this router at all, which the frontend can detect via 404).
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/reachy/voice/realtime", tags=["reachy-realtime-voice"])


@router.get("/config")
async def voice_realtime_config() -> dict[str, Any]:
    return {
        "default_provider": "openai",
        "providers": {
            "openai": {
                "label": "OpenAI Realtime",
                "key_env": "OPENAI_API_KEY",
                "key_hint": "https://platform.openai.com/api-keys",
                "default_model": OPENAI_MODEL_DEFAULT,
                "default_voice": OPENAI_VOICE_DEFAULT,
                "voices": OPENAI_VOICES,
                "input_sample_rate": 24000,
                "output_sample_rate": 24000,
            },
            "qwen": {
                "label": "通义千问 Omni (阿里云百炼)",
                "key_env": "DASHSCOPE_API_KEY",
                "key_hint": "https://bailian.console.aliyun.com/?apiKey=1",
                "default_model": QWEN_MODEL_DEFAULT,
                "default_voice": QWEN_VOICE_DEFAULT,
                "voices": QWEN_VOICES,
                "models": ["qwen3.5-omni-flash-realtime", "qwen3.5-omni-plus-realtime"],
                "input_sample_rate": 16000,
                "output_sample_rate": 24000,
            },
        },
    }
