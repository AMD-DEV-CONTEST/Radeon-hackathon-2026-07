"""Chat LLM for interactive radiology Q&A.

This module talks to a single external OpenAI-compatible chat server (e.g. a
llama-server instance) configured via ``CHAT_OPENAI_BASE_URL``. It supports
plain text Q&A as well as multimodal turns (image + text), and it accepts a
``history`` list so a conversation can continue across turns instead of being
rebuilt from scratch every time.

If no server is configured, ``answer``/``stream_answer`` return a warning
instead of fabricating a response. A startup warning is also printed so the
operator knows chat is disabled.
"""

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests


NO_MODEL_WARNING = (
    "No chat server is configured. Set CHAT_OPENAI_BASE_URL to an "
    "OpenAI-compatible server (e.g. llama-server) to enable conversational answers."
)

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful radiology assistant. Answer questions based on the provided "
    "chest X-ray report and findings. Be concise, accurate, and avoid giving "
    "definitive medical diagnoses. Do not show your reasoning or thinking process; "
    "just give the final answer."
)


@dataclass
class ChatAnswer:
    text: str
    tokens_generated: int
    latency_seconds: float
    model_name: str


class ChatLLM:
    """Conversational LLM wrapper around a single external llama-server."""

    def __init__(self, device: str = "cpu"):
        self.device = device
        self.max_new_tokens = int(os.environ.get("CHAT_MAX_TOKENS", "512"))
        self._openai_backend: Optional["OpenAIChatBackend"] = None
        self._load_backend()

    def _load_backend(self):
        from models.chat_status import CHAT_STATUS

        base_url = os.environ.get("CHAT_OPENAI_BASE_URL", "")
        if not base_url:
            CHAT_STATUS.set_error(NO_MODEL_WARNING)
            print(f"WARNING: {NO_MODEL_WARNING}")
            return

        try:
            self._openai_backend = OpenAIChatBackend(
                base_url=base_url,
                model_name=os.environ.get("CHAT_OPENAI_MODEL", "local-model"),
            )
            print(f"Configured chat backend at {base_url}")
            if self._openai_backend.is_available():
                CHAT_STATUS.set_ready(
                    base_url,
                    f"Chat server ready ({self._openai_backend.model_name}).",
                    model_name=self._openai_backend.model_name,
                )
            else:
                CHAT_STATUS.set_loading(f"Waiting for chat server at {base_url}...")
        except Exception as exc:
            CHAT_STATUS.set_error(str(exc))
            print(f"WARNING: Chat backend '{base_url}' could not be configured: {exc}")
            self._openai_backend = None

    def is_available(self) -> bool:
        if self._openai_backend is None:
            return False
        return self._openai_backend.is_available()

    def answer(
        self,
        report: str,
        findings: list,
        question: str,
        max_new_tokens: Optional[int] = None,
        temperature: float = 0.7,
        image: Optional[Any] = None,
        system_prompt: Optional[str] = None,
        history: Optional[list[dict[str, Any]]] = None,
    ) -> ChatAnswer:
        if max_new_tokens is None:
            max_new_tokens = self.max_new_tokens

        if self._openai_backend is None:
            return ChatAnswer(
                text=NO_MODEL_WARNING,
                tokens_generated=0,
                latency_seconds=0.0,
                model_name="none",
            )

        return self._openai_backend.answer(
            report, findings, question, max_new_tokens, temperature,
            image=image, system_prompt=system_prompt, history=history,
        )

    def stream_answer(
        self,
        report: str,
        findings: list,
        question: str,
        max_new_tokens: Optional[int] = None,
        temperature: float = 0.7,
        image: Optional[Any] = None,
        system_prompt: Optional[str] = None,
        history: Optional[list[dict[str, Any]]] = None,
    ):
        """Yield answer tokens as they are generated."""
        if max_new_tokens is None:
            max_new_tokens = self.max_new_tokens

        if self._openai_backend is None:
            yield NO_MODEL_WARNING
            return

        yield from self._openai_backend.stream_answer(
            report, findings, question, max_new_tokens, temperature,
            image=image, system_prompt=system_prompt, history=history,
        )


class OpenAIChatBackend:
    """External OpenAI-compatible chat backend (e.g. a llama-server instance).

    Speaks the standard OpenAI chat completion protocol, including streaming
    via SSE, and supports image input via ``image_url`` content blocks.

    ``history`` entries are dicts of the form ``{"role": ..., "content": ...}``
    and may optionally include ``"image_b64"`` on a ``"user"`` turn (used to
    seed the conversation with the image + prompt that produced the initial
    report, so later questions continue that same exchange).
    """

    def __init__(self, base_url: str, model_name: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        self.model_name = model_name
        self.timeout = timeout
        self._check_url = self.base_url.replace("/v1", "/health")

    def is_available(self) -> bool:
        try:
            response = requests.get(self._check_url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def _encode_image(self, image: Optional[Any]) -> Optional[str]:
        if image is None:
            return None
        from io import BytesIO
        import base64

        if isinstance(image, str):
            return image
        buf = BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _build_messages(
        self,
        report: str,
        findings: list,
        question: str,
        image: Optional[Any] = None,
        system_prompt: Optional[str] = None,
        history: Optional[list[dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        history = history or []
        messages: list[dict[str, Any]] = []

        # Only synthesize a system message from report/findings if the
        # conversation doesn't already carry one (e.g. from a report-seed).
        has_seed_system = any(turn.get("role") == "system" for turn in history)
        if not has_seed_system:
            finding_lines = "\n".join(
                f"- {f.label}: {f.confidence:.0%}" for f in findings if f.confidence > 0.05
            )
            base_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
            if report or finding_lines:
                base_prompt += f"\n\nReport:\n{report}\n\nFindings:\n{finding_lines}"
            messages.append({"role": "system", "content": base_prompt})

        for turn in history:
            role = turn.get("role")
            content = turn.get("content", "")
            if role not in ("system", "user", "assistant"):
                continue
            img_b64 = turn.get("image_b64")
            if role == "user" and img_b64:
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": content},
                    ],
                })
            elif content.strip() or role == "system":
                messages.append({"role": role, "content": content})

        # Current turn. An explicit `image` here is normally only used the
        # very first time (report generation); follow-up questions rely on
        # the image already present in history.
        image_b64 = self._encode_image(image)
        if image_b64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                    {"type": "text", "text": question or "Answer:"},
                ],
            })
        else:
            messages.append({"role": "user", "content": question})

        return messages

    def answer(
        self,
        report: str,
        findings: list,
        question: str,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        image: Optional[Any] = None,
        system_prompt: Optional[str] = None,
        history: Optional[list[dict[str, Any]]] = None,
    ) -> ChatAnswer:
        messages = self._build_messages(
            report, findings, question, image=image, system_prompt=system_prompt, history=history
        )
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_new_tokens,
            "temperature": temperature,
            "top_p": 0.95,
            "stream": False,
        }
        start = time.time()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        latency = time.time() - start
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        text = message.get("content", "") if message else ""
        usage = data.get("usage", {})
        return ChatAnswer(
            text=text.strip(),
            tokens_generated=usage.get("completion_tokens", 0),
            latency_seconds=latency,
            model_name=self.model_name,
        )

    def stream_answer(
        self,
        report: str,
        findings: list,
        question: str,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        image: Optional[Any] = None,
        system_prompt: Optional[str] = None,
        history: Optional[list[dict[str, Any]]] = None,
    ):
        """Yield answer tokens as they are generated."""
        messages = self._build_messages(
            report, findings, question, image=image, system_prompt=system_prompt, history=history
        )
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_new_tokens,
            "temperature": temperature,
            "top_p": 0.95,
            "stream": True,
        }
        start = time.time()
        first = True
        try:
            with requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                stream=True,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        data = line[6:]
                    elif line.startswith("data:"):
                        data = line[5:]
                    else:
                        continue
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        if first:
                            print(f"[chat] First token after {time.time() - start:.2f}s")
                            first = False
                        yield token
        except Exception as exc:
            print(f"[chat] Streaming error: {exc}")
            yield f"[Chat error: {exc}]"