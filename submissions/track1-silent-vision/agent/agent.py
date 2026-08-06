from backend.schemas import AgentResult, CommandDecision

VALID_DISPLAY_LANGUAGES = {"zh", "en"}


class AgentPolicy:
    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def decide_command(self, decision: CommandDecision) -> AgentResult:
        if not decision.accepted:
            return AgentResult(
                action="reject",
                language="unknown",
                text="",
                arguments={"intent": decision.intent, "reason": decision.reason},
                requiresConfirmation=False,
            )
        if not decision.executable:
            return AgentResult(
                action="ignore",
                language=_decision_language(decision),
                text=_decision_text(decision),
                arguments={"intent": decision.intent, "reason": decision.reason},
                requiresConfirmation=False,
            )
        return AgentResult(
            action="execute",
            language=_decision_language(decision),
            text=_decision_text(decision),
            arguments={"intent": decision.intent, "confidence": decision.confidence},
            requiresConfirmation=False,
        )


def _decision_language(decision: CommandDecision) -> str:
    value = decision.metadata.get("language") or decision.metadata.get("matchedLanguage")
    return value if isinstance(value, str) and value in VALID_DISPLAY_LANGUAGES else "unknown"


def _decision_text(decision: CommandDecision) -> str:
    value = decision.metadata.get("displayText") or decision.metadata.get("matchedPhrase")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(decision.intent)
