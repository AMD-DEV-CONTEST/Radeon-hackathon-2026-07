from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .config import Settings
from .schemas import RetrievalHit


SYSTEM_PROMPT = """You are OpenAlpha Sentinel, a local research intelligence agent.
Answer in the user's language. Use only the supplied source excerpts and conversation context.
Every factual strategy claim must cite one or more supplied labels such as [S1].
If evidence is missing, say that the available sources are insufficient. Never invent a URL,
strategy, metric, license, or test result. Separate source-author claims from system observations.
This is research and educational information, not investment advice.
When comparing sources, never transfer a limitation, metric, or assumption from one source to another.
"""


def _context_text(hits: list[RetrievalHit]) -> str:
    blocks = []
    for index, hit in enumerate(hits, 1):
        blocks.append(
            f"[S{index}] title={hit.card_title or 'Unknown'}\n"
            f"url={hit.immutable_url}\n"
            f"lines={hit.start_line}-{hit.end_line}\n{hit.text[:1800]}"
        )
    return "\n\n".join(blocks)


def _language_instruction(question: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", question):
        return "Answer entirely in Simplified Chinese, except for source titles and technical identifiers."
    return "Answer in the same language as the question."


class LocalLLM(ABC):
    name = "unknown"

    @abstractmethod
    def health(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def answer(self, question: str, hits: list[RetrievalHit], history: list[dict[str, Any]]) -> str:
        raise NotImplementedError


class HeuristicLLM(LocalLLM):
    name = "heuristic-local"

    def health(self) -> bool:
        return True

    def answer(self, question: str, hits: list[RetrievalHit], history: list[dict[str, Any]]) -> str:
        chinese = bool(re.search(r"[\u4e00-\u9fff]", question))
        if not hits:
            return "现有资料不足，未检索到可以核验的策略或来源。" if chinese else (
                "The current knowledge base does not contain enough evidence to answer this question."
            )
        lines = []
        seen: set[str] = set()
        for index, hit in enumerate(hits[:5], 1):
            title = hit.card_title or "Untitled source"
            if title in seen:
                continue
            seen.add(title)
            excerpt = re.sub(r"\s+", " ", hit.text).strip()[:220]
            lines.append(f"- {title}: {excerpt} [S{index}]")
        intro = "根据本地知识库，找到以下可核验资料：" if chinese else "The local knowledge base contains these verifiable results:"
        ending = "资料仅用于研究与教育，不构成投资建议。" if chinese else (
            "This material is for research and education, not investment advice."
        )
        return f"{intro}\n\n" + "\n".join(lines) + f"\n\n{ending}"


class OllamaLLM(LocalLLM):
    name = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def health(self) -> bool:
        try:
            return httpx.get(f"{self.base_url}/api/tags", timeout=0.8).is_success
        except httpx.HTTPError:
            return False

    def answer(self, question: str, hits: list[RetrievalHit], history: list[dict[str, Any]]) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(
            {"role": item["role"], "content": item["content"]}
            for item in history[-6:]
            if item.get("role") in {"user", "assistant"}
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    f"{_language_instruction(question)}\n\n"
                    f"Source excerpts:\n{_context_text(hits)}\n\nQuestion: {question}"
                ),
            }
        )
        response = httpx.post(
            f"{self.base_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": False, "options": {"temperature": 0.1}},
            timeout=120,
        )
        response.raise_for_status()
        return str(response.json()["message"]["content"]).strip()


class LlamaCppLLM(LocalLLM):
    name = "llama.cpp-rocm"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def health(self) -> bool:
        try:
            return httpx.get(f"{self.base_url}/models", timeout=0.8).is_success
        except httpx.HTTPError:
            return False

    def answer(self, question: str, hits: list[RetrievalHit], history: list[dict[str, Any]]) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(
            {"role": item["role"], "content": item["content"]}
            for item in history[-6:]
            if item.get("role") in {"user", "assistant"}
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    f"{_language_instruction(question)}\n\n"
                    f"Source excerpts:\n{_context_text(hits)}\n\nQuestion: {question}"
                ),
            }
        )
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            json={"model": self.model, "messages": messages, "temperature": 0.1, "max_tokens": 900},
            timeout=120,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"]).strip()


class LocalModelRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.heuristic = HeuristicLLM()
        self.ollama = OllamaLLM(settings.ollama_url, settings.ollama_model)
        self.llama = LlamaCppLLM(settings.llama_url, settings.llama_model)

    def active(self) -> LocalLLM:
        backend = self.settings.llm_backend
        if backend == "heuristic":
            return self.heuristic
        if backend == "ollama":
            return self.ollama
        if backend in {"llama", "llama_cpp", "rocm"}:
            return self.llama
        if self.llama.health():
            return self.llama
        if self.ollama.health():
            return self.ollama
        return self.heuristic

    @property
    def name(self) -> str:
        return self.active().name

    def answer(self, question: str, hits: list[RetrievalHit], history: list[dict[str, Any]]) -> tuple[str, str]:
        backend = self.active()
        try:
            return backend.answer(question, hits, history), backend.name
        except (httpx.HTTPError, KeyError, ValueError):
            if self.settings.llm_backend != "auto":
                raise
            return self.heuristic.answer(question, hits, history), self.heuristic.name


def validate_citation_labels(answer: str, hit_count: int) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return match.group(0) if 1 <= index <= hit_count else ""

    return re.sub(r"\[S(\d+)\]", replace, answer)
