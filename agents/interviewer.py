"""Interviewer FSM with dynamic priority queue.

Ensures the interviewer covers all life phases without getting stuck in rich narratives.
The FSM decides WHAT phase to ask about; the LLM handles HOW to ask it.

States: CHILDHOOD → EDUCATION → CAREER → RELATIONSHIPS → CHALLENGES → VALUES → LEGACY
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL
from memory.structurizer import structurize_text

logger = logging.getLogger(__name__)


class LifePhase(str, Enum):
    CHILDHOOD = "childhood"
    EDUCATION = "education"
    CAREER = "career"
    RELATIONSHIPS = "relationships"
    CHALLENGES = "challenges"
    VALUES = "values"
    LEGACY = "legacy"


PHASE_SEQUENCE = list(LifePhase)

PHASE_PROMPTS = {
    LifePhase.CHILDHOOD: "童年和家庭背景",
    LifePhase.EDUCATION: "教育经历和成长过程",
    LifePhase.CAREER: "事业发展和成就",
    LifePhase.RELATIONSHIPS: "重要的人和关系",
    LifePhase.CHALLENGES: "困难、挫折和转折",
    LifePhase.VALUES: "信念、价值观和处世之道",
    LifePhase.LEGACY: "传承、影响和留给后人的东西",
}


FSM_SYSTEM_PROMPT = """You are an empathetic biographer conducting a life story interview.

## Your Personality
- Warm, curious, and patient — like a good journalist or documentary filmmaker
- Listen carefully and follow emotional threads, but don't get lost in any single topic
- Use the user's own words and details to show you were paying attention

## HARD STATE MACHINE CONSTRAINT
{machine_directive}

## Current Coverage
{coverage_summary}

## Conversation So Far
{conversation_history}

## Your Task
Generate ONE warm, natural question (in Chinese) that follows the state machine directive above.
- Ask about the SPECIFIED life phase, not other phases
- Reference something the user said earlier to show you were listening
- One question at a time, no preamble, no analysis
- Keep it natural — you're having tea with someone, not conducting an interrogation"""


@dataclass
class InterviewState:
    """State tracked by the FSM."""

    conversation: list[dict] = field(default_factory=list)
    current_phase: LifePhase = LifePhase.CHILDHOOD
    phase_turn_count: int = 0
    questions_asked: int = 0
    coverage: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.coverage:
            self.coverage = {phase: 0.0 for phase in LifePhase}


class InterviewerFSM:
    """State-machine-driven interviewer with priority queue.

    FSM decides WHERE to go; LLM handles conversational styling.
    """

    def __init__(self, person_name: str = "unnamed", max_turns_per_phase: int = 3):
        self.name = person_name
        self.max_turns = max_turns_per_phase
        self.state = InterviewState()
        self.graph_data = None
        self._last_directive = ""

    def update_coverage(self, extracted_data: dict):
        """Update phase coverage — distributed weighted boost across all phases.

        Each entity type maps to a specific phase. Multiple entities of the same
        type yield diminishing returns to prevent over-boosting from verbose answers.
        """
        entities = extracted_data.get("entities", [])
        events = extracted_data.get("events", [])
        relationships = extracted_data.get("relationships", [])

        type_to_phase = {
            "person": LifePhase.RELATIONSHIPS,
            "object": LifePhase.CAREER,
            "place": LifePhase.CHILDHOOD,
            "skill": LifePhase.CAREER,
            "trait": LifePhase.VALUES,
            "concept": LifePhase.VALUES,
            "body_part": LifePhase.CHALLENGES,
            "feeling": LifePhase.CHALLENGES,
        }

        # Count entities per phase
        phase_hits: dict[LifePhase, int] = {p: 0 for p in LifePhase}
        for e in entities:
            phase = type_to_phase.get(e.get("type", ""))
            if phase:
                phase_hits[phase] += 1

        # Count relationships that touch specific phases
        for r in relationships:
            rtype = r.get("type", "")
            if rtype in ("parent_of", "birthplace_of"):
                phase_hits[LifePhase.CHILDHOOD] += 1
            elif rtype in ("educated_at", "masters"):
                phase_hits[LifePhase.EDUCATION] += 1
            elif rtype in ("works_at", "creates", "builds"):
                phase_hits[LifePhase.CAREER] += 1
            elif rtype in ("married", "friend_of", "mentor_of"):
                phase_hits[LifePhase.RELATIONSHIPS] += 1
            elif rtype == "has_trait":
                phase_hits[LifePhase.VALUES] += 1

        # Distribute event count evenly as general signal
        ev_boost = min(0.15, len(events) * 0.03)

        for phase in LifePhase:
            # Diminishing returns: first hit = 0.15, second = 0.07, third+ = 0.03
            hits = phase_hits.get(phase, 0)
            entity_boost = 0.0
            for i in range(hits):
                entity_boost += max(0.03, 0.15 - i * 0.06)

            # Current phase gets a bonus multiplier
            multiplier = 1.5 if phase == self.state.current_phase else 1.0
            boost = min(0.3, (entity_boost + ev_boost) * multiplier)
            self.state.coverage[phase] = min(1.0, self.state.coverage[phase] + boost)

    def get_directive(self) -> dict:
        """Determine the next FSM action and target phase."""
        self.state.phase_turn_count += 1
        self.state.questions_asked += 1

        current_cov = self.state.coverage[self.state.current_phase]
        turns_exceeded = self.state.phase_turn_count >= self.max_turns

        # Transition condition: coverage >= 70% OR max turns hit
        if current_cov >= 0.70 or turns_exceeded:
            # Find phase with lowest coverage
            next_phase = min(self.state.coverage, key=self.state.coverage.get)

            if self.state.coverage[next_phase] < 0.8:
                old = self.state.current_phase
                self.state.current_phase = next_phase
                self.state.phase_turn_count = 0

                directive = {
                    "action": "PIVOT",
                    "from_phase": old.value,
                    "target_phase": next_phase.value,
                    "target_label": PHASE_PROMPTS[next_phase],
                    "instruction": (
                        f"Acknowledge the user's previous answer warmly, "
                        f"then pivot the conversation to {PHASE_PROMPTS[next_phase]}. "
                        f"Find a natural narrative bridge if possible."
                    ),
                }
                logger.info(
                    "FSM PIVOT: %s → %s (coverage was %.0f%%)",
                    old.value,
                    next_phase.value,
                    current_cov * 100,
                )
                return directive

        directive = {
            "action": "CONTINUE",
            "target_phase": self.state.current_phase.value,
            "target_label": PHASE_PROMPTS[self.state.current_phase],
            "instruction": (
                "Ask a follow-up or clarifying question about "
                f"{PHASE_PROMPTS[self.state.current_phase]}. "
                "Reference specifics the user mentioned to dig deeper."
            ),
        }
        return directive

    def ask(self) -> str:
        """Generate the next interview question following FSM directive."""
        directive = self.get_directive()
        self._last_directive = directive

        if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
            return self._simple_question()

        # Build coverage summary
        cov_lines = []
        for phase in LifePhase:
            pct = self.state.coverage[phase]
            bar = "█" * int(pct * 10) + "░" * (10 - int(pct * 10))
            cov_lines.append(
                f"  {PHASE_PROMPTS[phase]}: [{bar}] {int(pct * 100)}% "
                f"{'← CURRENT' if phase == self.state.current_phase else ''}"
            )
        coverage_text = "\n".join(cov_lines)

        # Build conversation history (last 4 turns)
        history = ""
        for msg in self.state.conversation[-4:]:
            role = "Interviewer" if msg["role"] == "assistant" else "User"
            history += f"- {role}: {msg['content'][:150]}\n"

        machine_directive = (
            f"Action: {directive['action']}\n"
            f"Target Phase: {directive['target_label']}\n"
            f"Instruction: {directive['instruction']}\n\n"
            f"Do NOT ask about other life phases right now."
        )

        prompt = FSM_SYSTEM_PROMPT.format(
            machine_directive=machine_directive,
            coverage_summary=coverage_text,
            conversation_history=history if history else "(First question — start the interview)",
        )

        client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
        resp = client.chat.completions.create(
            model=QWEN_LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "Generate the next interview question (Chinese, one sentence):",
                },
            ],
            temperature=0.7,
            max_tokens=150,
        )

        question = resp.choices[0].message.content.strip()
        self.state.conversation.append({"role": "assistant", "content": question})
        return question

    def process_answer(self, answer: str) -> dict:
        """Process the user's answer and update coverage."""
        self.state.conversation.append({"role": "user", "content": answer})

        try:
            data = structurize_text(answer)
        except Exception:
            data = {
                "entities": [],
                "events": [],
                "phases": [],
                "relationships": [],
                "causal_links": [],
                "symbols": [],
            }

        self.update_coverage(data)
        return data

    def is_complete(self, min_coverage: float = 0.5) -> bool:
        """Check if all phases have minimum coverage."""
        if self.state.questions_asked < 4:
            return False
        covered = sum(1 for v in self.state.coverage.values() if v >= min_coverage)
        return covered >= 5  # 5 of 7 phases covered

    def get_coverage(self) -> str:
        lines = []
        for phase in LifePhase:
            pct = self.state.coverage[phase]
            lines.append(f"{PHASE_PROMPTS[phase]}: {int(pct * 100)}%")
        return "\n".join(lines)

    def get_last_directive(self) -> str:
        return str(self._last_directive) if self._last_directive else "N/A"

    def _simple_question(self) -> str:
        """Fallback questions (no API)."""
        questions = [
            ("CHILDHOOD", "能跟我聊聊你的童年吗？在什么样的环境里长大的？"),
            ("EDUCATION", "上学的时候是什么样的？有没有特别喜欢的老师或科目？"),
            ("CAREER", "你做的是什么工作？是怎么入行的？"),
            ("RELATIONSHIPS", "人生中对你影响最大的一个人是谁？"),
            ("CHALLENGES", "有没有哪段时间特别难熬？是怎么走过来的？"),
            ("VALUES", "你觉得什么是最重要的？为什么？"),
            ("LEGACY", "有没有什么事情，你希望别人记住的？"),
        ]
        idx = self.state.questions_asked % len(questions)
        phase, q = questions[idx]
        self.state.current_phase = (
            LifePhase(phase) if phase in [p.value for p in LifePhase] else self.state.current_phase
        )
        self._last_directive = f"{phase}: {q}"
        self.state.conversation.append({"role": "assistant", "content": q})
        self.state.questions_asked += 1
        return q
