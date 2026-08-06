from glass_gateway.schemas.cards import (
    AnswerCard,
    AnswerCardProps,
    ErrorCard,
    ErrorCardProps,
    ThinkingCard,
    UiPatch,
    WakeCard,
)


def clamp_body(text: str, limit: int = 180) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


class CardPlanner:
    def wake_patch(self, seq: int) -> UiPatch:
        return UiPatch(seq=seq, cards=[WakeCard()])

    def thinking_patch(self, seq: int) -> UiPatch:
        return UiPatch(seq=seq, cards=[ThinkingCard()])

    def answer_patch(self, seq: int, text: str) -> UiPatch:
        return UiPatch(
            seq=seq,
            cards=[AnswerCard(props=AnswerCardProps(title="海狸", body=clamp_body(text, 220)))],
        )

    def error_patch(self, seq: int, text: str) -> UiPatch:
        return UiPatch(
            seq=seq,
            cards=[ErrorCard(props=ErrorCardProps(title="没听清", body=clamp_body(text, 160)))],
        )

    def memory_patch(self, seq: int, text: str | None) -> UiPatch:
        body = text or "没有找到可靠记忆"
        return UiPatch(
            seq=seq,
            cards=[AnswerCard(props=AnswerCardProps(title="记忆", body=clamp_body(body, 220)))],
        )
