"""Deterministic English keyword parser for redaction policies.

Pure python, zero ML dependencies. Used as the guaranteed fallback when the
LLM policy parser is unavailable and directly when POLICYCUT_NO_LLM=1.

Behavior:
- The policy text is split into clauses on sentence boundaries and connectors
  (period, semicolon, comma, newline, "and", "but"; "except"/"excluding" start
  a new clause of their own).
- A clause containing a negation cue ("do not", "don't", "dont", "not", "no",
  "never", "except", "excluding", "avoid", "skip") BANS the categories it
  mentions: they are removed from the final spec regardless of clause order.
- Actions found in a clause apply to the targets of that clause; clauses with
  targets but no action inherit the most recent action/strength seen in a
  previous non-negated clause ("blur faces and plates" -> both blurred),
  otherwise defaults apply (visual: pixelate 65, audio: mute).
- "strength 40" / "at 80" / "80%" set visual strength, clamped to 1..100.
- Curated unsupported nouns (tattoo, name, voice, minor, child, logo,
  signature) appearing near a privacy verb are collected into
  unsupported_terms (surface form, deduplicated, order preserved).

The result is 100% deterministic for a given input string.
"""

import re

from .schema import (
    AudioAction,
    AudioTarget,
    DEFAULT_PROMPTS,
    PolicySpec,
    VisualAction,
    VisualTarget,
)

DEFAULT_VISUAL_ACTION = "pixelate"
DEFAULT_VISUAL_STRENGTH = 65
DEFAULT_AUDIO_ACTION = "mute"

# --------------------------------------------------------------------------
# Category phrases. Most specific first: matched character spans are consumed
# so e.g. "email address" is claimed by the email pattern before the bare
# "address" pattern can see it, and "phone screen" is claimed by screen before
# any phone pattern runs.
# --------------------------------------------------------------------------
_CATEGORY_PHRASES: list[tuple[str, str, str]] = [
    # license plates
    (r"vehicle\s+registration\s+plates?", "visual", "license_plate"),
    (r"registration\s+plates?", "visual", "license_plate"),
    (r"licen[cs]e\s+plates?", "visual", "license_plate"),
    (r"number\s+plates?", "visual", "license_plate"),
    # identity documents
    (r"identity\s+documents?", "visual", "id_document"),
    (r"identity\s+cards?", "visual", "id_document"),
    (r"id\s+documents?", "visual", "id_document"),
    (r"id\s+cards?", "visual", "id_document"),
    (r"driver'?s?\s+licen[cs]es?", "visual", "id_document"),
    (r"driving\s+licen[cs]es?", "visual", "id_document"),
    (r"passports?", "visual", "id_document"),
    # screens
    (r"laptop\s+screens?", "visual", "screen"),
    (r"smartphone\s+screens?", "visual", "screen"),
    (r"phone\s+screens?", "visual", "screen"),
    (r"computer\s+screens?", "visual", "screen"),
    (r"tablet\s+screens?", "visual", "screen"),
    (r"computer\s+monitors?", "visual", "screen"),
    # audio: phone numbers
    (r"telephone\s+numbers?", "audio", "phone"),
    (r"phone\s+numbers?", "audio", "phone"),
    (r"telephones?", "audio", "phone"),
    # audio: email
    (r"e-?mail\s+address(?:es)?", "audio", "email"),
    (r"e-?mails?", "audio", "email"),
    # audio: address
    (r"street\s+address(?:es)?", "audio", "address"),
    (r"home\s+address(?:es)?", "audio", "address"),
    (r"mailing\s+address(?:es)?", "audio", "address"),
    (r"address(?:es)?", "audio", "address"),
    # bare visual nouns last (least specific)
    (r"faces?", "visual", "face"),
    (r"plates?", "visual", "license_plate"),
    (r"screens?", "visual", "screen"),
    (r"monitors?", "visual", "screen"),
    (r"displays?", "visual", "screen"),
    (r"ids?", "visual", "id_document"),
]
_CATEGORY_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(rf"\b(?:{rx})\b"), kind, cat) for rx, kind, cat in _CATEGORY_PHRASES
]

# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
_VISUAL_ACTION_PHRASES: list[tuple[str, str]] = [
    (r"blur(?:red|ring|s)?", "blur"),
    (r"pixelat(?:e|es|ed|ing|ion)", "pixelate"),
    (r"mosaics?", "pixelate"),
    (r"black(?:ed)?\s*outs?", "solid"),
    (r"black", "solid"),
    (r"cover(?:ed|ing|s)?", "solid"),
    (r"block(?:ed|ing|s)?", "solid"),
    (r"solid", "solid"),
]
_AUDIO_ACTION_PHRASES: list[tuple[str, str]] = [
    (r"mut(?:e|es|ed|ing)", "mute"),
    (r"silenc(?:e|es|ed|ing)", "mute"),
    (r"beep(?:ed|ing|s)?", "beep"),
    (r"bleep(?:ed|ing|s)?", "beep"),
]
_VISUAL_ACTION_PATTERNS = [
    (re.compile(rf"\b(?:{rx})\b"), action) for rx, action in _VISUAL_ACTION_PHRASES
]
_AUDIO_ACTION_PATTERNS = [
    (re.compile(rf"\b(?:{rx})\b"), action) for rx, action in _AUDIO_ACTION_PHRASES
]

# --------------------------------------------------------------------------
# Curated unsupported nouns (recorded when near a privacy verb)
# --------------------------------------------------------------------------
_UNSUPPORTED_PHRASES = [
    r"tattoos?",
    r"names?",
    r"voices?",
    r"minors?",
    r"child(?:ren)?",
    r"logos?",
    r"signatures?",
]
_UNSUPPORTED_PATTERNS = [re.compile(rf"\b(?:{rx})\b") for rx in _UNSUPPORTED_PHRASES]

_PRIVACY_VERBS = (
    r"blur(?:red|ring|s)?|pixelat\w*|mosaics?|black(?:ed)?(?:\s*outs?)?|cover\w*|block\w*|solid|"
    r"mut(?:e|es|ed|ing)|silenc\w*|beep\w*|bleep\w*|redact\w*|hid(?:e|es|ing)|hidden|censor\w*|"
    r"obscur\w*|anonymi[sz]\w*|mask\w*|remov\w*|conceal\w*|eras(?:e|es|ed|ing)|scrub\w*|protect\w*"
)
_PRIVACY_VERB_RE = re.compile(rf"\b(?:{_PRIVACY_VERBS})\b")

# Negation cues (clause-level scope)
_NEG_RE = re.compile(r"\b(?:do\s+not|don'?t|never|not|no|except|excluding|avoid|skip)\b")

# Clause splitting: sentence boundaries + connectors
_CLAUSE_SPLIT_RE = re.compile(r"[.;,\n!?]+|\band\b|\bbut\b")

# Strength: "strength 40", "strength of 40", "at 80", "80%"
_STRENGTH_RE = re.compile(
    r"\bstrength\s*(?:of|=|:)?\s*(\d{1,3})\b|\bat\s+(\d{1,3})\b|\b(\d{1,3})\s*%"
)


def _prepare(text: str) -> str:
    """Lowercase, normalize apostrophes, and give exception clauses their own split."""
    t = text.lower().replace("’", "'").replace("‘", "'")
    # "blur everything except faces" -> ". except faces" so the negated part
    # becomes its own clause and does not poison sibling targets.
    t = re.sub(r"\b(except|excluding)\b", r". \1", t)
    return t


def _find_action(clause: str, patterns: list[tuple[re.Pattern, str]]) -> str | None:
    """Earliest action match in the clause wins."""
    best: tuple[int, str] | None = None
    for pattern, action in patterns:
        m = pattern.search(clause)
        if m is not None and (best is None or m.start() < best[0]):
            best = (m.start(), action)
    return best[1] if best else None


def _find_strength(clause: str) -> int | None:
    m = _STRENGTH_RE.search(clause)
    if m is None:
        return None
    value = int(next(g for g in m.groups() if g is not None))
    return max(1, min(100, value))


def _find_categories(clause: str) -> list[tuple[str, str]]:
    """Return (kind, category) pairs in order of appearance, spans consumed."""
    consumed: list[tuple[int, int]] = []
    hits: list[tuple[int, str, str]] = []
    for pattern, kind, cat in _CATEGORY_PATTERNS:
        for m in pattern.finditer(clause):
            start, end = m.span()
            if any(s < end and start < e for s, e in consumed):
                continue  # overlaps a more specific phrase already claimed
            consumed.append((start, end))
            hits.append((start, kind, cat))
    hits.sort(key=lambda h: h[0])
    ordered: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, kind, cat in hits:
        if (kind, cat) not in seen:
            seen.add((kind, cat))
            ordered.append((kind, cat))
    return ordered


def _find_unsupported(clause: str) -> list[str]:
    """Curated unsupported nouns in order of appearance (surface form)."""
    hits: list[tuple[int, str]] = []
    for pattern in _UNSUPPORTED_PATTERNS:
        for m in pattern.finditer(clause):
            hits.append((m.start(), m.group(0)))
    hits.sort(key=lambda h: h[0])
    return [term for _, term in hits]


def parse_keyword_policy(text: str) -> PolicySpec:
    """Parse an English policy string into a PolicySpec. 100% deterministic."""
    prepared = _prepare(text or "")
    clauses = [c for c in _CLAUSE_SPLIT_RE.split(prepared) if c and c.strip()]

    visual_found: dict[str, tuple[str, int]] = {}  # category -> (action, strength)
    audio_found: dict[str, str] = {}  # category -> action
    banned_visual: set[str] = set()
    banned_audio: set[str] = set()
    unsupported: list[str] = []
    unsupported_seen: set[str] = set()

    carried_visual_action: str | None = None
    carried_strength: int | None = None
    carried_audio_action: str | None = None
    verb_seen = False

    for clause in clauses:
        negated = _NEG_RE.search(clause) is not None
        visual_action = _find_action(clause, _VISUAL_ACTION_PATTERNS)
        audio_action = _find_action(clause, _AUDIO_ACTION_PATTERNS)
        strength = _find_strength(clause)
        categories = _find_categories(clause)
        has_verb = _PRIVACY_VERB_RE.search(clause) is not None

        if negated:
            # A negated clause removes its targets: ban them outright.
            for kind, cat in categories:
                (banned_visual if kind == "visual" else banned_audio).add(cat)
            verb_seen = verb_seen or has_verb
            continue

        # Update carried state only from non-negated clauses.
        if visual_action is not None:
            carried_visual_action = visual_action
        if strength is not None:
            carried_strength = strength
        if audio_action is not None:
            carried_audio_action = audio_action

        for kind, cat in categories:
            if kind == "visual":
                act = visual_action or carried_visual_action or DEFAULT_VISUAL_ACTION
                stg = strength if strength is not None else carried_strength
                if stg is None:
                    stg = DEFAULT_VISUAL_STRENGTH
                visual_found[cat] = (act, stg)  # last instruction wins
            else:
                audio_found[cat] = audio_action or carried_audio_action or DEFAULT_AUDIO_ACTION

        if has_verb or verb_seen:
            for term in _find_unsupported(clause):
                if term not in unsupported_seen:
                    unsupported_seen.add(term)
                    unsupported.append(term)
        verb_seen = verb_seen or has_verb

    visual_targets = [
        VisualTarget(
            category=cat,
            prompts=list(DEFAULT_PROMPTS[cat]),
            action=VisualAction(type=act, strength=stg),
        )
        for cat, (act, stg) in visual_found.items()
        if cat not in banned_visual
    ]
    audio_targets = [
        AudioTarget(category=cat, action=AudioAction(type=act))
        for cat, act in audio_found.items()
        if cat not in banned_audio
    ]
    return PolicySpec(
        visual_targets=visual_targets,
        audio_targets=audio_targets,
        unsupported_terms=unsupported,
    )
