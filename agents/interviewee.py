"""Simulated interviewee - a user persona that answers interview questions.

Used for testing the interviewer agent. The interviewee has:
  - A pre-defined life story (persona)
  - Personality traits (verbosity, openness, tangent_rate)
  - Emotional guard topics (questions that make them defensive)
  - Variable response timing (simulating thinking pauses)

Configuration:
  persona_text: str   - the person's life story
  verbosity: float     - 0.5 (terse) to 1.5 (very detailed)
  tangent_rate: float  - 0.0 to 1.0, chance of going off-topic
  guard_topics: list   - topics that trigger shorter/guarded responses
"""

import logging
import random
import time

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL
from utils.timing import timing

logger = logging.getLogger(__name__)


INTERVIEWEE_SYSTEM = """You are roleplaying as a person being interviewed about your life.
You have a specific life story, personality, and way of speaking.

## Your Life Story
{persona}

## Your Personality
- Verbosity: {verbosity_label} ({verbosity_desc})
- You speak in {language} naturally
- You are {openness_label} about sharing personal stories
- Your emotional guard topics: {guard_topics_str}

## Interview Context
The interviewer is trying to understand your life and build a life graph.
Answer naturally, as a real person would.
Share specific details, emotions, and memories - not just abstract summaries.

## Response Rules
1. Answer the question directly, then add a personal detail or feeling
2. Use your life story as the source of truth - don't make up things not in your story
3. If the question touches a guard topic, be shorter and more reserved
4. {tangent_rule}
5. Keep answers to 2-5 sentences
6. Speak naturally, as if talking to someone over tea
7. Do NOT mention that you are a simulated interviewee
"""


def _pick_verbosity(level: float) -> tuple[str, str]:
    if level > 1.2:
        return "talkative", "you enjoy elaborating and sharing details freely"
    elif level > 0.8:
        return "moderate", "you answer directly but add personal touches"
    else:
        return "terse", "you keep answers short and to the point"


def _pick_openness(level: float) -> str:
    if level > 0.8:
        return "very open and comfortable"
    elif level > 0.5:
        return "generally open"
    else:
        return "somewhat reserved and private"


def _tangent_rule(rate: float) -> str:
    if rate > 0.2:
        return (
            f"About {int(rate * 100)}% of the time, add a brief unrelated "
            f"thought or memory after answering"
        )
    elif rate > 0.05:
        return "Occasionally, add an unrelated personal observation after answering"
    else:
        return "Stay focused on the question, don't go off-topic"


@timing(name="interviewee_respond")
def respond(
    question: str,
    persona_text: str,
    verbosity: float = 1.0,
    tangent_rate: float = 0.1,
    guard_topics: list[str] | None = None,
    language: str = "Chinese",
) -> str:
    """Generate a natural response to an interview question.

    Returns the simulated user's response text.
    """
    if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
        return _mock_response(question, persona_text, guard_topics)

    verb_label, verb_desc = _pick_verbosity(verbosity)
    openness_label = _pick_openness(1.0 - len(guard_topics or []) * 0.2)
    tangent_rule = _tangent_rule(tangent_rate)
    guard_str = ", ".join(guard_topics) if guard_topics else "none"

    system = INTERVIEWEE_SYSTEM.format(
        persona=persona_text,
        verbosity_label=verb_label,
        verbosity_desc=verb_desc,
        openness_label=openness_label,
        guard_topics_str=guard_str,
        tangent_rule=tangent_rule,
        language=language,
    )

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        temperature=0.8,
        max_tokens=400,
    )

    return resp.choices[0].message.content.strip()


def respond_with_delay(
    question: str,
    persona_text: str,
    verbosity: float = 1.0,
    tangent_rate: float = 0.1,
    guard_topics: list[str] | None = None,
    think_time: tuple[float, float] = (0.5, 3.0),
    language: str = "Chinese",
) -> str:
    """Respond with a simulated thinking delay."""
    delay = random.uniform(*think_time)
    logger.debug("Thinking for %.1fs...", delay)
    time.sleep(min(delay, 2.0))  # Cap real delay at 2s, longer delays are simulated

    return respond(question, persona_text, verbosity, tangent_rate, guard_topics, language)


def _mock_response(question: str, persona: str, guard_topics: list[str] | None = None) -> str:
    """Simple mock response (no API key)."""
    # Very simple: extract a relevant sentence from persona
    lines = persona.split("。")
    for line in lines:
        words = question.replace("？", "").replace("?", "")
        if any(w in line for w in words.split()):
            return line.strip() + "。"
    return lines[0].strip() + "。"
