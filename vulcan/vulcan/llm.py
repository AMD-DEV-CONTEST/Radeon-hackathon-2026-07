"""Thin client for any OpenAI-compatible server (Ollama, vLLM, llama.cpp)."""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from .config import Config

RETRIES = 3
RETRY_BACKOFF_S = 1.5


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    ttft_s: float | None
    total_s: float


class LLM:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._client = httpx.Client(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=300,
        )
        # Same client unless embeddings are pointed elsewhere, so the common
        # single-endpoint case opens exactly one connection pool as before.
        self._embed_client = (
            self._client
            if cfg.embed_base_url == cfg.base_url
            else httpx.Client(
                base_url=cfg.embed_base_url,
                headers={"Authorization": f"Bearer {cfg.embed_api_key}"},
                timeout=300,
            )
        )

    def chat(self, messages: list[dict], stream: bool = False) -> ChatResult:
        """Retries transport failures, because a remote GPU is reached over a
        link that drops. Observed against the Radeon Cloud proxy as
        `ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING]` part way through an
        agent run. A stream is only retried while nothing has been emitted
        yet, so a half-delivered answer is never silently duplicated.
        """
        last: Exception | None = None
        for attempt in range(RETRIES):
            try:
                return self._chat_once(messages, stream)
            except httpx.TransportError as exc:
                last = exc
                if attempt < RETRIES - 1:
                    time.sleep(RETRY_BACKOFF_S * (attempt + 1))
        raise RuntimeError(
            f"{self.cfg.base_url} failed after {RETRIES} attempts: {last}"
        ) from last

    def _chat_once(self, messages: list[dict], stream: bool = False) -> ChatResult:
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "stream": stream,
        }
        if self.cfg.enable_thinking is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": self.cfg.enable_thinking}
        start = time.perf_counter()
        if not stream:
            r = self._client.post("/chat/completions", json=payload)
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage") or {}
            return ChatResult(
                text=data["choices"][0]["message"]["content"],
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                ttft_s=None,
                total_s=time.perf_counter() - start,
            )

        # Streaming: measure time-to-first-token for the benchmark harness.
        ttft = None
        chunks: list[str] = []
        n_tokens = 0
        try:
            with self._client.stream("POST", "/chat/completions", json=payload) as r:
                if r.status_code >= 400:
                    # raise_for_status() on a streaming response reports the
                    # code and nothing else, and reading .text afterwards fails
                    # with ResponseNotRead, so the server's own explanation is
                    # unreachable exactly when it is needed. Read the body
                    # first and put it in the error.
                    r.read()
                    raise RuntimeError(
                        f"{r.status_code} from {self.cfg.base_url}: {r.text[:400]}"
                    )
                for line in r.iter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    import json as _json

                    delta = _json.loads(line[6:])["choices"][0].get("delta", {})
                    piece = delta.get("content")
                    if piece:
                        if ttft is None:
                            ttft = time.perf_counter() - start
                        chunks.append(piece)
                        n_tokens += 1
        except httpx.TransportError:
            # Nothing delivered yet, so the caller can safely start over.
            if not chunks:
                raise
            # Content already streamed. Retrying would duplicate it, so return
            # the truncated answer rather than losing the whole turn.
        return ChatResult(
            text="".join(chunks),
            prompt_tokens=0,
            completion_tokens=n_tokens,
            ttft_s=ttft,
            total_s=time.perf_counter() - start,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = self._embed_client.post("/embeddings", json={"model": self.cfg.embed_model, "input": texts})
        if r.status_code == 404:
            raise RuntimeError(
                f"No /v1/embeddings route at {self.cfg.embed_base_url}. A vLLM server "
                "started with task=generate does not serve embeddings. Set "
                "VULCAN_EMBED_BASE_URL (and VULCAN_EMBED_API_KEY) to an embeddings-capable "
                "endpoint, for example a local Ollama at http://localhost:11434/v1."
            )
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]
