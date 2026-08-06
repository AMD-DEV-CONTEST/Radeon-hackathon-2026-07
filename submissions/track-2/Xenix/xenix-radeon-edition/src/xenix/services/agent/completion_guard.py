from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from ..llm import AgentProvider, ProviderMessage


TURN_COMPLETION_GUARD_REMINDER = (
    "You appear to have stated a next action in this turn but did not complete it. "
    "Continue now by using tools or by providing the final answer. "
    "Stop only if you truly need user input."
)

_GUARD_SYSTEM_PROMPT = """You classify whether an assistant stopped too early.

You will receive only the final assistant text from a single turn.

Return strict JSON only:
{"verdict":"continue","reason":"short reason"}
or
{"verdict":"complete","reason":"short reason"}

Use "continue" only when the assistant text states an immediate next action inside the current turn, such as checking, training, predicting, running, calling, inspecting, generating, or looking up something, but does not provide a result and does not ask the user for input.

Use "complete" when the text is a final answer, a normal summary, empty/ambiguous, or asks the user for input."""


class TurnCompletionGuardVerdict(StrEnum):
    CONTINUE = "continue"
    COMPLETE = "complete"


class TurnCompletionGuardResult(BaseModel):
    verdict: TurnCompletionGuardVerdict
    reason: str = ""
    usage_payload: dict[str, Any] | None = None
    retry_events: list[dict[str, Any]] = Field(default_factory=list)
    provider_failed: bool = False


class TurnCompletionGuard:
    def __init__(self, provider: AgentProvider) -> None:
        self._provider = provider

    @property
    def provider(self) -> AgentProvider:
        return self._provider

    def evaluate(self, last_assistant_text: str) -> TurnCompletionGuardResult:
        if not last_assistant_text.strip():
            return TurnCompletionGuardResult(
                verdict=TurnCompletionGuardVerdict.COMPLETE,
                reason="No assistant text to inspect.",
            )

        try:
            response = self._provider.complete(
                [
                    ProviderMessage(role="system", content=_GUARD_SYSTEM_PROMPT),
                    ProviderMessage(
                        role="user",
                        content=json.dumps(
                            {"last_assistant_text": last_assistant_text},
                            ensure_ascii=False,
                        ),
                    ),
                ],
                [],
            )
            result = _parse_guard_output(_content_blocks_to_text(response.assistant_content_blocks))
            result.usage_payload = response.usage_payload
            return result
        except Exception as exc:
            return TurnCompletionGuardResult(
                verdict=TurnCompletionGuardVerdict.COMPLETE,
                reason=f"Guard failed closed: {exc}",
                provider_failed=True,
            )


def _parse_guard_output(text: str) -> TurnCompletionGuardResult:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return TurnCompletionGuardResult(
            verdict=TurnCompletionGuardVerdict.COMPLETE,
            reason="Guard returned invalid JSON.",
        )
    if not isinstance(payload, dict):
        return TurnCompletionGuardResult(
            verdict=TurnCompletionGuardVerdict.COMPLETE,
            reason="Guard returned a non-object JSON value.",
        )
    verdict = payload.get("verdict")
    if verdict not in {TurnCompletionGuardVerdict.CONTINUE.value, TurnCompletionGuardVerdict.COMPLETE.value}:
        return TurnCompletionGuardResult(
            verdict=TurnCompletionGuardVerdict.COMPLETE,
            reason="Guard returned an unsupported verdict.",
        )
    reason = payload.get("reason")
    return TurnCompletionGuardResult(
        verdict=TurnCompletionGuardVerdict(verdict),
        reason=str(reason or ""),
    )


def _content_blocks_to_text(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type in {"text", "markdown"}:
            lines.append(str(block.get("text", "")))
        else:
            lines.append(json.dumps(block, ensure_ascii=False))
    return "\n".join(line for line in lines if line).strip()
