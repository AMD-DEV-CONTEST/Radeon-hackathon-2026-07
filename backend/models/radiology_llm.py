"""Unified radiology LLM that generates reports and chats about them.

This module merges the AI Radiology Report generator and the Ask the AI chat
into a single model class. The same ``RadiologyLLM`` instance is responsible
for:

1. Generating a structured radiology report from clinical findings.
2. Answering questions about the generated report (and the findings).

The generated report content is cached so the chat can reuse it directly
without requiring callers to resend it. When a dedicated chat backend is
configured via ``CHAT_MODEL`` / ``CHAT_OPENAI_BASE_URL`` it is used; otherwise
the report generator's built-in chat fallback answers questions.
"""
import os
import threading
import time
from typing import Any, Optional

from models.chat_llm import ChatAnswer, ChatLLM
from models.report_generator import ReportGenerator, ReportResult


class RadiologyLLM:
    """Single model class for report generation and report-aware chat."""

    def __init__(self, device: str = "cpu"):
        self.device = device
        # The same chat backend is reused for report generation and follow-up chat.
        self.chat_engine = ChatLLM(device=device)
        self.report_generator = ReportGenerator(chat_engine=self.chat_engine, device=device)

        self._chat_ready = threading.Event()
        self._chat_error: Optional[str] = None

        # Cache the last generated report so chat can reuse it directly.
        self._last_report_result: Optional[ReportResult] = None
        self._last_findings: list = []
        self._last_structured: Optional[dict[str, Any]] = None

    def load_chat_engine(self) -> None:
        """Notify that the shared chat backend is available and set status.

        The chat backend is created synchronously with RadiologyLLM because the
        same backend now generates reports. This method just marks readiness
        and updates the shared status object.
        """
        from models.chat_status import CHAT_STATUS

        openai_base_url = os.environ.get("CHAT_OPENAI_BASE_URL", "")
        chat_model = os.environ.get("CHAT_MODEL", "")

        if not openai_base_url and not chat_model:
            CHAT_STATUS.set_ready(
                "report-generator-fallback",
                "Chat ready via report-generator fallback (no CHAT_MODEL configured).",
                model_name="report-generator-fallback",
            )
            self._chat_ready.set()
            return

        try:
            print("[radiology-llm] Verifying shared chat/report backend...")
            if self.chat_engine is None:
                self.chat_engine = ChatLLM(device=self.device)
                self.report_generator.chat_engine = self.chat_engine
            if not self.chat_engine.is_available() and not self._chat_engine_has_async_backend(
                self.chat_engine
            ):
                self._chat_error = (
                    "Dedicated chat backend could not be initialized; "
                    "using report-generator fallback."
                )
                print(f"[radiology-llm] {self._chat_error}")
            else:
                print("[radiology-llm] Shared chat/report backend ready.")
        except Exception as exc:  # pragma: no cover - defensive
            self._chat_error = str(exc)
            print(f"[radiology-llm] Dedicated chat backend failed to load: {exc}")
        finally:
            self._chat_ready.set()

    def wait_for_chat(self, timeout: Optional[float] = None) -> bool:
        """Wait until the chat backend has finished initializing."""
        return self._chat_ready.wait(timeout=timeout)

    def wait_for_chat_available(self, timeout: float = 300.0, poll_interval: float = 0.5) -> bool:
        """Poll until a chat backend is actually available (or timeout).

        The fallback report-generator chat is always considered available.
        If the background load finished but no usable backend was produced,
        stop waiting early so the fallback can take over.
        """
        if self.is_chat_available():
            return True
        start = time.time()
        while time.time() - start < timeout:
            if self.is_chat_available():
                return True
            if self._chat_ready.is_set() and self._chat_error:
                # Initialization failed; fallback will be used.
                return False
            time.sleep(poll_interval)
        return self.is_chat_available()

    def is_chat_available(self) -> bool:
        """Return True if a chat backend can answer right now."""
        if self.chat_engine is not None:
            return self.chat_engine.is_available()
        # No dedicated chat engine: the report generator's fallback chat is
        # always available.
        return True

    @staticmethod
    def _chat_engine_has_async_backend(chat_engine: ChatLLM) -> bool:
        """Return True if the chat engine has a backend that may become ready later."""
        return (
            chat_engine._openai_backend is not None
            or chat_engine._gguf_backend is not None
            or chat_engine._ternary_worker is not None
        )

    def generate_report(
        self,
        findings: list,
        image: Optional[Any] = None,
        structured_findings: Optional[dict[str, Any]] = None,
        image_info: Optional[dict] = None,
        max_new_tokens: int = 128,
    ) -> ReportResult:
        """Generate a radiology report and cache it for follow-up chat."""
        result = self.report_generator.generate(
            image=image,
            findings=findings,
            structured_findings=structured_findings,
            image_info=image_info,
            max_new_tokens=max_new_tokens,
        )
        self._last_report_result = result
        self._last_findings = findings
        self._last_structured = structured_findings
        return result

    def chat(
        self,
        report: Optional[str] = None,
        findings: Optional[list] = None,
        question: str = "",
        max_new_tokens: Optional[int] = None,
        temperature: float = 0.7,
        history=None,
    ) -> ChatAnswer:
        """Answer a question about the report, reusing the cached report if possible."""
        report, findings = self._resolve_context(report, findings)
        history = self._resolve_history(history)

        if self.chat_engine is not None and self.chat_engine.is_available():
            return self.chat_engine.answer(
                report, findings, question, max_new_tokens, temperature, history=history
            )

        # Dedicated chat unavailable: use the report generator's built-in chat.
        answer_text = self.report_generator.chat(report, findings, question)
        return ChatAnswer(
            text=answer_text,
            tokens_generated=0,
            latency_seconds=0.0,
            model_name=self.report_generator.model_name or "report-generator-fallback",
        )

    def stream_chat(
        self,
        report: Optional[str] = None,
        findings: Optional[list] = None,
        question: str = "",
        max_new_tokens: Optional[int] = None,
        temperature: float = 0.7,
        history=None,
    ):
        """Stream an answer about the report.

        Yields tokens when a streaming chat backend is available. Otherwise it
        yields the full fallback answer as a single chunk.
        """
        report, findings = self._resolve_context(report, findings)
        history = self._resolve_history(history)

        if self.chat_engine is not None and self.chat_engine.is_available():
            yield from self.chat_engine.stream_answer(
                report, findings, question, max_new_tokens, temperature, history=history
            )
            return

        # Fallback: yield the whole rule-based answer at once.
        yield self.report_generator.chat(report, findings, question)

    def _resolve_history(self, history):
        """If the caller has no history yet, seed it from the cached report exchange."""
        if history:
            return history
        if self._last_report_result is not None:
            return self._last_report_result.chat_seed
        return []

    def _resolve_context(
        self, report: Optional[str], findings: Optional[list]
    ) -> tuple[str, list]:
        """Resolve report/findings, falling back to cached generated content."""
        if report is None and self._last_report_result is not None:
            report = self._last_report_result.report
        if findings is None:
            findings = self._last_findings
        if report is None:
            report = ""
        if findings is None:
            findings = []
        return report, findings
