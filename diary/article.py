"""Export a day's diary as a polished article in a famous writer's voice.

``generate_article`` gathers the day's recorded entries (and any planned todos)
and asks the local LLM to rewrite them as a cohesive first-person article that
sounds like the chosen author. Read-only: it only reads the graph, it never
mutates the diary.

Language is hard-locked: a Chinese article must contain only Chinese script, an
English article only Latin. If the model leaks foreign script we run one cleanup
pass and, as a last resort, strip the offending runs so the UI never shows a
mixed-script article.
"""

from __future__ import annotations

import re

from diary import config
from diary.day_view import get_day_view
from openai import OpenAI

_CLIENT: OpenAI | None = None

# Latin runs of >=2 letters count as "foreign" inside a zh article.
_LATIN = re.compile(r"[A-Za-z]{2,}")
# Arabic / Cyrillic / CJK count as "foreign" inside an en article.
_NON_LATIN = re.compile(r"[\u4e00-\u9fff\u0600-\u06FF\u0400-\u04FF]")


def _client() -> OpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(api_key=config.LLM_API_KEY or "local", base_url=config.LLM_BASE_URL)
    return _CLIENT


def _raw_diary(date: str) -> str:
    data = get_day_view(date)
    lines = []
    for i, e in enumerate(data.get("entries", []), 1):
        lines.append(f"{i}. {e.get('text', '')}")
    todos = data.get("todos", [])
    if todos:
        planned = "; ".join(
            f"{t['text']}" + (f" (on {t['for_date']})" if t.get("for_date") else "")
            for t in todos
        )
        lines.append(f"Plans noted: {planned}")
    return "\n".join(lines)


def _has_foreign(text: str, lang: str) -> bool:
    return bool(_LATIN.search(text)) if lang == "zh" else bool(_NON_LATIN.search(text))


def _strip_foreign(text: str, lang: str) -> str:
    """Last-resort fallback: remove any foreign-script runs entirely."""
    if lang == "zh":
        return _LATIN.sub("", text)
    return _NON_LATIN.sub("", text)


def _cleanup(text: str, lang: str) -> str:
    if lang == "zh":
        sys_msg = (
            "The Chinese text below accidentally contains English/Latin words. "
            "Rewrite it in PURE Chinese (Chinese characters and punctuation only). "
            "Translate or transliterate every English word into Chinese. Preserve all "
            "meaning and the author's voice. Output ONLY the corrected Chinese text, "
            "nothing else — no preamble, no quotes."
        )
    else:
        sys_msg = (
            "The English text below accidentally contains non-English characters "
            "(Chinese, Arabic, etc.). Rewrite it in PURE English (Latin alphabet only), "
            "translating any non-English words into English. Preserve meaning and voice. "
            "Output ONLY the corrected English text, nothing else — no preamble, no quotes."
        )
    kwargs = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": text},
        ],
        "temperature": 0.3,
        "max_tokens": 1100,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    try:
        resp = _client().chat.completions.create(**kwargs)
    except Exception:
        kwargs.pop("extra_body", None)
        resp = _client().chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def generate_article(date: str, style: str, lang: str = "en") -> str:
    """Rewrite the day's diary as an article in ``style``'s voice.

    ``style`` is a writer name (e.g. "Hemingway", "鲁迅"). ``lang`` is "en"/"zh".
    Returns the article text, or "" if there is nothing recorded for the day.
    """
    raw = _raw_diary(date)
    if not raw.strip():
        return ""

    lang_name = "Chinese (中文)" if lang == "zh" else "English"
    if lang == "zh":
        script_rule = (
            "CRITICAL: Write ONLY in Chinese. Use Chinese characters and Chinese "
            "punctuation exclusively. You MUST NOT output any Latin, Cyrillic, Arabic, "
            "or any other non-Chinese script — not even for names or quotes. If a name "
            "is originally foreign, transliterate it into Chinese characters."
        )
    else:
        script_rule = (
            "CRITICAL: Write ONLY in English using the Latin alphabet. You MUST NOT "
            "output any Arabic, Chinese, Cyrillic, or any other non-Latin script — not "
            "even for names (transliterate foreign names into English)."
        )
    sys_msg = (
        "You are a skilled ghostwriter who rewrites a person's raw voice-diary "
        "into a finished, publishable first-person article. You preserve every "
        "real event, person, place, and plan exactly as recorded — you NEVER invent "
        "new facts, dialogue, or happenings. You only elevate the prose, voice, and "
        "flow.\n"
        f"CRITICAL: Write ONLY in {lang_name}. Do not mix in any other language.\n"
        f"{script_rule}\n"
        "Output the article text and nothing else — no preamble, no quotes, no title line."
    )
    user_msg = (
        f"Author style to imitate: {style}\n\n"
        f"Raw diary for {date} (verbatim):\n"
        f"{raw}\n\n"
        "Rewrite this as a cohesive first-person article in that author's voice, "
        "in the requested language. Keep it to a few short paragraphs."
    )

    kwargs = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.8,
        "max_tokens": 1100,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    try:
        resp = _client().chat.completions.create(**kwargs)
    except Exception:
        kwargs.pop("extra_body", None)
        resp = _client().chat.completions.create(**kwargs)
    article = (resp.choices[0].message.content or "").strip()

    # Guarantee a single-script article: one cleanup pass, then strip any remainder.
    if _has_foreign(article, lang):
        cleaned = _cleanup(article, lang)
        article = cleaned if cleaned else article
        if _has_foreign(article, lang):
            article = _strip_foreign(article, lang).strip()
    return article
