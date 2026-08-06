"""AI client helpers for Find it.

These classes let the web demo:
  - describe an image with a VLM (image → query text)
  - transcribe audio with an ASR service (audio → query text)
  - run the chunked video transcription worker
  - drive the agentic retrieval chat via a separate agent LLM

Configuration is loaded from this project's own ``.env`` (the file next to this
module — see DEFAULT_ENV_PATH), using the keys documented in ``.env.example``.
The agentic LLM uses a separate ``AGENT_LLM_*`` key family so it never shares
credentials with the VLM/ASR endpoints.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from PIL import Image

# Shared "agentic" logger — configured (with handlers + level) in agentic.py.
log = logging.getLogger("agentic")

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_ENV_PATH = Path(__file__).resolve().parent / ".env"


class Config:
    """Load VLM/ASR/processing settings from a .env file."""

    def __init__(self, env_path: str | Path | None = None) -> None:
        resolved = Path(env_path or DEFAULT_ENV_PATH)
        if not resolved.is_absolute():
            resolved = Path(__file__).resolve().parent / resolved
        if resolved.exists():
            load_dotenv(resolved)
            print(f"[config] Loaded from {resolved}", file=sys.stderr)
        else:
            print(f"[config] .env not found at {resolved}; using env vars/defaults", file=sys.stderr)

        # VLM
        self.vlm_api_url: str = self._get("VLM_API_URL", "http://localhost:11434/v1/chat/completions")
        self.vlm_model_name: str = self._get("VLM_MODEL_NAME", "minicpm-v4.5:8b")
        self.vlm_prompt: str = self._get("VLM_PROMPT", "描述这张图片中的内容。")
        self.vlm_max_resolution: int = int(self._get("VLM_MAX_RESOLUTION", "1344"))

        # ASR
        self.asr_api_url: str = self._get("ASR_API_URL", "http://127.0.0.1:8080/inference")
        self.asr_temperature: float = float(self._get("ASR_TEMPERATURE", "0.0"))
        self.asr_temperature_inc: float = float(self._get("ASR_TEMPERATURE_INC", "0.2"))
        self.asr_prompt: str = self._get("ASR_PROMPT", "")
        self.asr_carry_initial_prompt: bool = self._get("ASR_CARRY_INITIAL_PROMPT", "true").strip().lower() == "true"
        self.asr_response_format: str = self._get("ASR_RESPONSE_FORMAT", "srt")

        # Processing
        self.frame_interval: int = int(self._get("FRAME_INTERVAL", "1"))
        self.audio_chunk_duration: int = int(self._get("AUDIO_CHUNK_DURATION", "30"))

        # Mock
        self.mock_mode: bool = self._get("MOCK_MODE", "false").strip().lower() == "true"

    @staticmethod
    def _get(key: str, default: str) -> str:
        return os.environ.get(key) or default


class AgentConfig:
    """Settings for the agentic retrieval LLM (a separate model from VLM/ASR).

    Reads the ``AGENT_LLM_*`` keys from the same .env file as Config.  The
    agentic model is deliberately configured with its own credentials so the
    retrieval agent never shares an endpoint/key with the transcription stack.
    """

    def __init__(self, env_path: str | Path | None = None) -> None:
        resolved = Path(env_path or DEFAULT_ENV_PATH)
        if not resolved.is_absolute():
            resolved = Path(__file__).resolve().parent / resolved
        if resolved.exists():
            load_dotenv(resolved)
            print(f"[agent-config] Loaded from {resolved}", file=sys.stderr)
        else:
            print(f"[agent-config] .env not found at {resolved}; using env vars/defaults", file=sys.stderr)

        self.api_url: str = self._get("AGENT_LLM_API_URL", "http://localhost:11434/v1/chat/completions")
        self.model_name: str = self._get("AGENT_LLM_MODEL", "gpt-oss:20b")
        self.api_key: str = self._get("AGENT_LLM_API_KEY", "")
        self.temperature: float = float(self._get("AGENT_LLM_TEMPERATURE", "0.0"))
        self.max_turns: int = int(self._get("AGENT_LLM_MAX_TURNS", "8"))
        self.max_tokens: int = int(self._get("AGENT_LLM_MAX_TOKENS", "4096"))
        self.max_retries: int = int(self._get("AGENT_LLM_MAX_RETRIES", "2"))
        self.stream: bool = self._get("AGENT_LLM_STREAM", "true").strip().lower() == "true"

        # Mock defaults to the shared MOCK_MODE so the existing
        # "MOCK_MODE=true" test convention also mocks the agent.
        mock = self._get("AGENT_LLM_MOCK", "").strip().lower()
        if mock == "":
            mock = self._get("MOCK_MODE", "false").strip().lower()
        self.mock_mode: bool = mock == "true"

    @staticmethod
    def _get(key: str, default: str) -> str:
        return os.environ.get(key) or default


# --------------------------------------------------------------------------- #
# Image utilities
# --------------------------------------------------------------------------- #

MIME_MAP: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _resize_if_needed(image_path: Path, max_resolution: int) -> Path:
    img = Image.open(image_path)
    w, h = img.size
    current_max = max(w, h)
    if current_max <= max_resolution:
        return image_path
    scale = max_resolution / current_max
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    resized = image_path.with_stem(image_path.stem + "_resized")
    img_resized = img.resize((new_w, new_h), Image.LANCZOS)
    img_resized.save(resized, "JPEG", quality=90)
    return resized


# --------------------------------------------------------------------------- #
# VLM client
# --------------------------------------------------------------------------- #

class VLMClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def describe(self, image_path: Path) -> str:
        img_path = _resize_if_needed(image_path, self.config.vlm_max_resolution)
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = MIME_MAP.get(img_path.suffix.lower(), "image/jpeg")
        data_url = f"data:{mime};base64,{b64}"

        payload = {
            "model": self.config.vlm_model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.config.vlm_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": 1024,
        }
        log.info(
            "[VLM] request -> model=%s image=%s prompt=%r",
            self.config.vlm_model_name, img_path.name, self.config.vlm_prompt,
        )
        log.debug("[VLM] request url: %s", self.config.vlm_api_url)
        resp = requests.post(self.config.vlm_api_url, json=payload, timeout=600)
        resp.raise_for_status()
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        log.info("[VLM] response <- (%d chars): %s", len(content), content)
        return content


class MockVLMClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def describe(self, image_path: Path) -> str:
        return (
            f"[MOCK] 这是图片 {image_path.name} 的模拟描述。"
        )


# --------------------------------------------------------------------------- #
# SRT parsing
# --------------------------------------------------------------------------- #

_SRT_TIMESTAMP_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def _parse_srt_ts(ts: str) -> float:
    m = _SRT_TIMESTAMP_RE.match(ts)
    if not m:
        raise ValueError(f"Cannot parse SRT timestamp: '{ts}'")
    h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return float(h * 3600 + mi * 60 + s + ms / 1000)


def _fmt_srt_time(seconds: float) -> str:
    td = timedelta(seconds=seconds)
    total_ms = int(round(td.total_seconds() * 1000))
    h, r = divmod(total_ms, 3_600_000)
    m, r = divmod(r, 60_000)
    s, ms = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(srt_text: str, time_offset: float = 0.0) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    blocks = re.split(r"\n[ \t]*\n", srt_text.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue
        ts_match = re.match(r"(\S+)\s*-->\s*(\S+)", lines[1])
        if not ts_match:
            continue
        start_sec = _parse_srt_ts(ts_match.group(1)) + time_offset
        end_sec = _parse_srt_ts(ts_match.group(2)) + time_offset
        text = "\n".join(lines[2:]).strip()
        segments.append({
            "index": index,
            "start": _fmt_srt_time(start_sec),
            "end": _fmt_srt_time(end_sec),
            "start_seconds": start_sec,
            "end_seconds": end_sec,
            "text": text,
        })
    return segments


# --------------------------------------------------------------------------- #
# ASR client
# --------------------------------------------------------------------------- #

class ASRClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def transcribe(self, audio_path: Path) -> list[dict[str, Any]]:
        with open(audio_path, "rb") as f:
            files = {"file": (audio_path.name, f, "audio/wav")}
            data = {
                "temperature": str(self.config.asr_temperature),
                "temperature_inc": str(self.config.asr_temperature_inc),
                "prompt": self.config.asr_prompt,
                "carry_initial_prompt": str(self.config.asr_carry_initial_prompt).lower(),
                "response_format": self.config.asr_response_format,
            }
            resp = requests.post(self.config.asr_api_url, files=files, data=data, timeout=180)
        resp.raise_for_status()
        return parse_srt(resp.text)


class MockASRClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def transcribe(self, audio_path: Path) -> list[dict[str, Any]]:
        return [{
            "index": 1,
            "start": "00:00:00,000",
            "end": "00:00:03,000",
            "start_seconds": 0.0,
            "end_seconds": 3.0,
            "text": "[MOCK] 这是模拟语音转录文本。",
        }]


# --------------------------------------------------------------------------- #
# Agentic retrieval LLM client
# --------------------------------------------------------------------------- #

class AgentLLMResponse:
    """One decision from the agent LLM under the JSON ReAct protocol.

    kind:
      * ``tool_call`` — call ``tool`` with ``arguments``, then continue the loop
      * ``reply``     — final natural-language answer (``content``)
      * ``ask``       — a clarifying question back to the user (``content``)

    ``plain`` is True when the model produced natural-language text instead of
    a structured decision — the "plain conversation fallback" path.
    """

    __slots__ = ("kind", "tool", "arguments", "content", "plain")

    def __init__(
        self,
        kind: str,
        tool: str | None = None,
        arguments: dict | None = None,
        content: str | None = None,
        plain: bool = False,
    ) -> None:
        if kind not in ("tool_call", "reply", "ask"):
            raise ValueError(f"unknown agent response kind: {kind!r}")
        if kind == "tool_call" and not tool:
            raise ValueError("tool_call response requires a tool name")
        self.kind = kind
        self.tool = tool
        self.arguments = arguments or {}
        self.content = content or ""
        self.plain = plain

    def to_dict(self) -> dict:
        d: dict = {"action": self.kind}
        if self.kind == "tool_call":
            d["tool"] = self.tool
            d["arguments"] = self.arguments
        else:
            d["content"] = self.content
        return d


def _dump_messages(messages: list[dict]) -> str:
    """Compact, truncate messages for verbose logging."""
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content")
        if isinstance(content, str):
            content = content[:300]
        else:
            try:
                content = json.dumps(content, ensure_ascii=False)[:300]
            except (TypeError, ValueError):
                content = repr(content)[:300]
        lines.append(f"  [{role}] {content}")
    return "\n".join(lines)


def _response_from_tool_calls(tool_calls: list[dict]) -> AgentLLMResponse:
    """Build an AgentLLMResponse from a native OpenAI ``tool_calls`` item.

    Accepts both the native shape (``{"function": {"name", "arguments"}}``) and
    the flattened shape produced by the SSE reader (``{"name", "arguments"}``).
    """
    tc = tool_calls[0]
    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    name = fn.get("name") or tc.get("name") or ""
    args = fn.get("arguments") or tc.get("arguments") or "{}"
    if isinstance(args, str):
        args = args.strip() or "{}"
        try:
            arguments = json.loads(args)
        except json.JSONDecodeError:
            log.warning("[LLM] unparseable native tool args for %r: %r", name, args[:300])
            arguments = {}
    else:
        arguments = args or {}
    log.debug("[LLM] native tool_call -> %s %s", name, json.dumps(arguments, ensure_ascii=False))
    return AgentLLMResponse("tool_call", tool=name, arguments=arguments)


class AgentLLMClient:
    """Calls an OpenAI-compatible chat/completions endpoint.

    Understands BOTH the JSON ReAct protocol in ``content`` and native OpenAI
    ``tool_calls`` (used by DeepSeek / vLLM / OpenAI).  When ``stream`` is on
    (AGENT_LLM_STREAM, default true) the SSE stream is consumed and logged
    line-by-line so the backend shows the LLM output live.  Parse/network
    errors are retried up to ``max_retries`` (AGENT_LLM_MAX_RETRIES), then
    re-raised with the raw output + retry count attached for a specific error.
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def chat(
        self,
        messages: list[dict],
        tools_schema: list[dict],
        on_token: Callable[[str], None] | None = None,
    ) -> AgentLLMResponse:
        """Chat with the agent model.

        ``on_token`` (optional) is called with each content token as it streams
        (used by the SSE chat endpoint to push live output to the frontend).
        """
        stream = self.config.stream
        for attempt in range(1, self.config.max_retries + 1):
            try:
                return self._chat_once(messages, tools_schema, attempt, stream, on_token)
            except AgentProtocolError as exc:
                exc.retries = attempt
                log.warning(
                    "[LLM] protocol/parse error (attempt %d/%d): %s | raw=%r",
                    attempt, self.config.max_retries, exc,
                    getattr(exc, "raw", "")[:300],
                )
                if attempt >= self.config.max_retries:
                    raise
                time.sleep(0.8 * attempt)
            except requests.RequestException as exc:
                exc.retries = attempt
                log.warning(
                    "[LLM] HTTP/network error (attempt %d/%d): %s",
                    attempt, self.config.max_retries, exc,
                )
                if stream and attempt >= self.config.max_retries:
                    # Streaming unsupported / failed at transport level: try once
                    # without streaming before giving up.
                    log.warning("[LLM] streaming failed; retrying once without streaming")
                    return self._chat_once(messages, tools_schema, attempt + 1, stream=False, on_token=on_token)
                if attempt >= self.config.max_retries:
                    raise
                time.sleep(0.8 * attempt)
        raise AgentProtocolError("no LLM attempts made", raw="")

    def _chat_once(
        self,
        messages: list[dict],
        tools_schema: list[dict],
        attempt: int,
        stream: bool,
        on_token: Callable[[str], None] | None = None,
    ) -> AgentLLMResponse:
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.model_name:
            payload["model"] = self.config.model_name
        if tools_schema:
            payload["tools"] = tools_schema
        if stream:
            payload["stream"] = True
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        log.debug(
            "[LLM] request attempt %d  %s  model=%s stream=%s tools=%s",
            attempt, self.config.api_url, self.config.model_name or "(default)",
            stream, [t.get("function", {}).get("name") for t in tools_schema],
        )
        log.debug("[LLM] messages:\n%s", _dump_messages(messages))

        resp = requests.post(
            self.config.api_url, json=payload, headers=headers,
            stream=stream, timeout=600,
        )
        resp.raise_for_status()

        if stream:
            content, tool_calls = self._read_sse(resp)
            log.debug("[LLM] streamed content (%d chars): %r", len(content), content[:1200])
            if tool_calls:
                log.debug("[LLM] streamed tool_calls: %s",
                          json.dumps(tool_calls, ensure_ascii=False))
        else:
            body = resp.json()
            log.debug("[LLM] response body: %s",
                      json.dumps(body, ensure_ascii=False)[:3000])
            message = body["choices"][0]["message"]
            content = message.get("content") or ""
            tool_calls = message.get("tool_calls") or []

        if tool_calls:
            return _response_from_tool_calls(tool_calls)

        result = parse_agent_json(content)
        log.debug("[LLM] parsed -> kind=%s tool=%r content=%r",
                  result.kind, result.tool, (result.content or "")[:200])
        # Only forward the PARSED reply text (never the raw JSON/ReAct wrapper,
        # and never tool-call content) so the frontend streams clean markdown.
        if on_token and result.kind in ("reply", "ask"):
            self._emit_reply(result.content or "", on_token)
        return result

    @staticmethod
    def _emit_reply(content: str, on_token: Callable[[str], None]) -> None:
        """Forward a final reply to on_token in small chunks so the frontend
        renders it progressively (streaming feel)."""
        if not content:
            return
        step = 24
        for i in range(0, len(content), step):
            on_token(content[i : i + step])
            if i + step < len(content):
                time.sleep(0.004)

    @staticmethod
    def _iter_response_lines(resp):
        """Yield decoded SSE lines from a requests streaming response."""
        for line in resp.iter_lines(decode_unicode=False):
            if not line:
                continue
            yield line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line

    def _read_sse(self, resp) -> tuple[str, list[dict]]:
        """Consume a streamed chat/completions response, logging every line.

        Accumulates ``content`` deltas and fragmented ``tool_calls`` arguments,
        returning ``(content, tool_calls)``.  Content is buffered (not streamed
        live) so the caller can forward only the PARSED reply text — raw JSON
        ReAct wrappers and tool-call content are never leaked to the frontend.
        """
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        for line in self._iter_response_lines(resp):
            log.debug("[LLM] SSE: %s", line)
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if not data:
                continue
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            c = delta.get("content")
            if c:
                content_parts.append(c)
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = tool_calls.setdefault(idx, {"name": "", "arguments": []})
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["arguments"].append(fn["arguments"])
        content = "".join(content_parts)
        calls: list[dict[str, Any]] = []
        for idx in sorted(tool_calls):
            slot = tool_calls[idx]
            calls.append({
                "name": slot["name"],
                "arguments": "".join(slot["arguments"]),
            })
        return content, calls


class MockAgentLLMClient:
    """Deterministic agent LLM for tests.

    Two construction modes:
      * ``responses`` — a list/iterator of AgentLLMResponse (or JSON strings).
        Each ``chat`` call pops the next one; exhausted -> a default reply.
      * ``responder`` — a callable ``(messages, tools_schema) -> AgentLLMResponse``
        that inspects the conversation and decides what to do.
    """

    def __init__(self, config: AgentConfig | None = None, *,
                 responses: list | None = None,
                 responder=None) -> None:
        self.config = config
        self._responses = list(responses) if responses is not None else []
        self._responder = responder
        self.calls: list[dict] = []          # history of (messages, tools_schema)
        self.called_tools: list[str] = []    # tool names requested so far

    def chat(
        self,
        messages: list[dict],
        tools_schema: list[dict],
        on_token=None,
    ) -> AgentLLMResponse:
        self.calls.append({"messages": messages, "tools_schema": tools_schema})
        if self._responder is not None:
            resp = self._responder(messages, tools_schema)
        elif self._responses:
            raw = self._responses.pop(0)
            resp = raw if isinstance(raw, AgentLLMResponse) else parse_agent_json(raw)
        else:
            resp = AgentLLMResponse("reply", content="[MOCK] I have nothing more to add.")
        if resp.kind == "tool_call":
            self.called_tools.append(resp.tool)
        elif on_token and resp.content:
            # Simulate a stream of the final reply for tests / non-native models.
            on_token(resp.content)
        return resp


# --------------------------------------------------------------------------- #
# Agent JSON ReAct protocol parsing
# --------------------------------------------------------------------------- #

class AgentProtocolError(ValueError):
    """Raised when the agent LLM output is not valid JSON ReAct output.

    ``raw`` carries the model's output so callers can log / surface it.
    ``retries`` is set by the client after the last failed retry.
    """

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw
        self.retries = 0


def _lenient_json_data(text: str) -> dict[str, Any] | None:
    """Recover an agent ReAct object when strict JSON parsing fails.

    Models often emit pretty-printed JSON with literal newlines and unescaped
    quotes inside the ``content`` string (invalid control characters).  This
    extracts the top-level fields by pattern so the loop can continue.

    Returns a dict shaped like the ReAct protocol, or None if nothing matches.
    """
    t = text
    action = re.search(r'"action"\s*:\s*"(tool|reply|ask)"', t)
    if not action:
        return None
    act = action.group(1)
    out: dict[str, Any] = {"action": act}
    if act == "tool":
        tm = re.search(r'"tool"\s*:\s*"([^"]+)"', t)
        if not tm:
            return None
        out["tool"] = tm.group(1)
        am = re.search(r'"arguments"\s*:\s*(\{.*\})', t, re.DOTALL)
        if am:
            try:
                args = json.loads(am.group(1))
                out["arguments"] = args if isinstance(args, dict) else {}
            except json.JSONDecodeError:
                out["arguments"] = {}
    else:
        # content = everything between the opening quote and the closing quote
        # that precedes the final '}' (tolerates embedded quotes / newlines).
        cm = re.search(r'"content"\s*:\s*"(.*)"\s*}\s*$', t, re.DOTALL)
        out["content"] = cm.group(1) if cm else ""
    return out


def parse_agent_json(content: str) -> AgentLLMResponse:
    """Parse an AgentLLMResponse from the model's content.

    Tolerates ```json ... ``` code fences and prose around the JSON object.
    If no JSON object is present, the raw text is returned as a *plain*
    conversational reply (``plain=True``) rather than raising — this is the
    "plain conversation fallback" so the agent never hard-fails on models that
    do not emit structured tool calls.
    """
    text = content.strip()
    if not text:
        raise AgentProtocolError("empty agent output", raw=content)
    # Strip a ```json ... ``` fence if present.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().lstrip("`").strip().lower() in ("json", ""):
            text = "\n".join(lines[1:])
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3].rstrip()
    # If there is prose before/after the JSON object, extract the first {...}.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        # Plain conversation fallback: surface the model's text as the answer.
        return AgentLLMResponse("reply", content=text, plain=True)
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        # Strict JSON failed — the model often pretty-prints its ReAct JSON with
        # literal newlines / unescaped quotes inside the content string.  Try a
        # lenient field-extraction fallback before giving up.
        data = _lenient_json_data(text[start : end + 1])
        if data is None:
            log.warning("[LLM] agent output unparseable (strict + lenient): %s | raw=%r",
                        exc, content[:500])
            raise AgentProtocolError(f"invalid JSON in agent output: {exc}", raw=content) from exc
        log.debug("[LLM] parsed via lenient fallback -> action=%s", data.get("action"))
    if not isinstance(data, dict):
        raise AgentProtocolError(f"agent output is not an object: {data!r}", raw=content)

    action = data.get("action")
    if action == "tool":
        tool = data.get("tool")
        if not tool:
            raise AgentProtocolError("tool action missing 'tool' name", raw=content)
        arguments = data.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise AgentProtocolError("tool action 'arguments' must be an object", raw=content)
        return AgentLLMResponse("tool_call", tool=tool, arguments=arguments)
    if action in ("reply", "ask"):
        return AgentLLMResponse(action, content=str(data.get("content") or ""))
    raise AgentProtocolError(f"unknown agent action: {action!r}", raw=content)


# --------------------------------------------------------------------------- #
# Chunk-aware media extraction
# --------------------------------------------------------------------------- #

def _run_ffmpeg(cmd: list[str], description: str = "ffmpeg", timeout: int = 3600) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{description} failed: {exc.stderr}") from exc
    return result.stdout


def extract_frames_for_interval(
    video_path: Path,
    work_dir: Path,
    start_seconds: float,
    duration: float,
    interval: int,
) -> list[dict[str, Any]]:
    """Extract frames from [start_seconds, start_seconds+duration) every interval seconds."""
    out_dir = work_dir / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(out_dir / "frame_%06d.jpg")
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(max(start_seconds, 0.0)),
        "-t", str(max(duration, 0.1)),
        "-i", str(video_path),
        "-vf", f"fps=1/{interval}",
        "-qscale:v", "2",
        output_pattern,
    ]
    _run_ffmpeg(cmd, "frame extraction")
    frame_files = sorted(out_dir.glob("frame_*.jpg"))
    frames: list[dict[str, Any]] = []
    for i, fpath in enumerate(frame_files):
        frames.append({
            "timestamp": start_seconds + float(i * interval),
            "path": fpath,
        })
    return frames


def extract_audio_for_interval(
    video_path: Path,
    work_dir: Path,
    start_seconds: float,
    duration: float,
) -> Path:
    """Extract a WAV snippet from [start_seconds, start_seconds+duration)."""
    out_path = work_dir / "chunk.wav"
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(max(start_seconds, 0.0)),
        "-t", str(max(duration, 0.1)),
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(out_path),
    ]
    _run_ffmpeg(cmd, "audio extraction")
    return out_path


def extract_audio_for_whole_video(video_path: Path, work_dir: Path) -> Path:
    """Extract the full audio track as 16kHz mono WAV."""
    out_path = work_dir / "audio.wav"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(out_path),
    ]
    _run_ffmpeg(cmd, "audio extraction")
    return out_path


def convert_audio_to_wav(input_path: Path, work_dir: Path) -> Path:
    """Convert an arbitrary audio file to 16kHz mono WAV for ASR."""
    out_path = work_dir / "query_audio.wav"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(out_path),
    ]
    _run_ffmpeg(cmd, "audio conversion")
    return out_path


# --------------------------------------------------------------------------- #
# Convenience singleton
# --------------------------------------------------------------------------- #

_AI_CONFIG: Config | None = None


def get_ai_config() -> Config:
    global _AI_CONFIG
    if _AI_CONFIG is None:
        _AI_CONFIG = Config()
    return _AI_CONFIG


def vlm_client(config: Config | None = None) -> VLMClient | MockVLMClient:
    cfg = config or get_ai_config()
    return MockVLMClient(cfg) if cfg.mock_mode else VLMClient(cfg)


def asr_client(config: Config | None = None) -> ASRClient | MockASRClient:
    cfg = config or get_ai_config()
    return MockASRClient(cfg) if cfg.mock_mode else ASRClient(cfg)


_AGENT_CONFIG: AgentConfig | None = None


def get_agent_config() -> AgentConfig:
    """Singleton AgentConfig for the agentic retrieval LLM."""
    global _AGENT_CONFIG
    if _AGENT_CONFIG is None:
        _AGENT_CONFIG = AgentConfig()
    return _AGENT_CONFIG


def agent_llm_client(config: AgentConfig | None = None) -> AgentLLMClient | MockAgentLLMClient:
    """Factory returning a mock agent LLM in mock mode, else the real client."""
    cfg = config or get_agent_config()
    return MockAgentLLMClient(cfg) if cfg.mock_mode else AgentLLMClient(cfg)
