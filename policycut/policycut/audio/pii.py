"""Audio PII detection: regex + spoken-form normalization (+ optional presidio).

detect_pii(transcript, policy, settings) -> list[RedactionEvent] (kind="audio").

Detection runs per transcript segment on two views of the words:
- the raw join (formatted numbers, literal emails, cue phrases), and
- the spoken-form normalized string ("five five five dash ..." -> "555-...").

Character ranges are mapped back to word indices (via the char maps from
policycut.audio.spoken) and then to start/end seconds from word timestamps.
Segments without word timestamps fall back to whole-segment events with
confidence 0.4 and warning "segment_level_timestamps".

text_preview NEVER contains the full raw value — only a redaction-safe label
such as "PHONE ending ...34", "EMAIL domain example.com",
"ADDRESS (cue: i live at)".
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field

from policycut.audio.spoken import DIGIT_WORDS, join_raw, normalize_spoken
from policycut.core.models import RedactionEvent

logger = logging.getLogger(__name__)

try:
    from policycut.core.ids import new_id
except ImportError:  # pragma: no cover - ids.py is trivial and always present
    def new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:10]}"

# --- regexes ---------------------------------------------------------------

# Raw text: formatted numbers like +1 (555) 123-4567, 555-123-4567, 5551234567.
RAW_PHONE_RE = re.compile(r"\+?\(?\d{1,4}\)?(?:[\s().\-]{0,3}\d{2,4}){1,5}")
# Normalized string: 7+ digits with optional separators (spoken digits glue).
NORM_PHONE_RE = re.compile(r"\d(?:[\s().\-]{0,3}\d){6,}")

RAW_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Spoken "at" can produce extra "@" before the real address ("reach me at john
# dot doe at example dot com" -> "reach me@john.doe@example.com"), so allow a
# chain of @-joined pieces and anchor the domain/TLD at the end.
NORM_EMAIL_RE = re.compile(
    r"[a-z0-9._%+\-]+(?:@[a-z0-9._%+\-]+)*@[a-z0-9.\-]+\.[a-z]{2,}"
)

ZIP_RE = re.compile(r"(?<!\d)\d{5}(?!\d)")

CUE_PHRASES = ("my address is", "i live at", "located at")
STREET_SUFFIXES = {
    "street", "st", "avenue", "ave", "road", "rd", "boulevard", "blvd",
    "lane", "ln", "drive", "dr", "court", "ct", "way", "place",
}

_MERGE_GAP_S = 0.2
_MIN_PHONE_DIGITS = 7

# presidio analyzer cache: None = untried, False = unavailable.
_PRESIDIO = None

_EDGE_PUNCT_RE = re.compile(r"^\W+|\W+$")


@dataclass
class _Hit:
    start: float
    end: float
    confidence: float
    preview: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Word:
    text: str
    start: float
    end: float


@dataclass
class _Segment:
    text: str
    start: float
    end: float
    words: list[_Word] = field(default_factory=list)


# --- helpers ---------------------------------------------------------------

def _field(obj, *names, default=None):
    """First present, non-None field among `names` (attribute or dict key)."""
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        else:
            value = getattr(obj, name, None)
            if value is not None:
                return value
    return default


def _coerce_segments(transcript) -> list[_Segment]:
    """Normalize a Transcript (dataclass / pydantic model / plain dict, e.g.
    parsed transcript JSON) into a uniform list of _Segment with _Word items.

    Tolerates whisper-style ("word"/"start"/"end") and contract-style
    ("text"/"start_s"/"end_s") key names.
    """
    segments: list[_Segment] = []
    for seg in _field(transcript, "segments", default=[]) or []:
        words: list[_Word] = []
        for w in _field(seg, "words", default=[]) or []:
            text = str(_field(w, "text", "word", default="")).strip()
            if not text:
                continue
            start = float(_field(w, "start", "start_s", default=0.0))
            end = float(_field(w, "end", "end_s", default=start))
            words.append(_Word(text=text, start=start, end=max(start, end)))
        seg_start = float(_field(seg, "start", "start_s", default=0.0))
        seg_end = float(_field(seg, "end", "end_s", default=seg_start))
        segments.append(_Segment(
            text=str(_field(seg, "text", default="")),
            start=seg_start,
            end=max(seg_start, seg_end),
            words=words,
        ))
    return segments

def _clean_tok(token: str) -> str:
    return _EDGE_PUNCT_RE.sub("", str(token).strip().lower())


def _is_number_tok(tok: str) -> bool:
    return bool(re.fullmatch(r"\d+", tok)) or tok in DIGIT_WORDS


def _span_seconds(words, cmap: list[int], c0: int, c1: int) -> tuple[float, float] | None:
    """Map a char range [c0, c1) to (start_s, end_s) via word timestamps."""
    if not cmap or not words:
        return None
    c1 = max(c0 + 1, c1)
    i = cmap[min(max(c0, 0), len(cmap) - 1)]
    j = cmap[min(c1 - 1, len(cmap) - 1)]
    if i > j:
        i, j = j, i
    i = min(i, len(words) - 1)
    j = min(j, len(words) - 1)
    return float(words[i].start), float(words[j].end)


def _digits_of(text: str) -> str:
    return re.sub(r"\D", "", text)


def _phone_preview(match_text: str) -> str:
    digits = _digits_of(match_text)
    return f"PHONE ending ...{digits[-2:]}" if len(digits) >= 2 else "PHONE"


def _email_preview(match_text: str) -> str:
    domain = match_text.rsplit("@", 1)[-1].strip().rstrip(".").lower()
    return f"EMAIL domain {domain}" if domain else "EMAIL"


def _get_presidio():
    """Optional presidio analyzer; import guarded, tried at most once."""
    global _PRESIDIO
    if _PRESIDIO is None:
        try:
            from presidio_analyzer import AnalyzerEngine

            _PRESIDIO = AnalyzerEngine()
            logger.info("presidio analyzer available (extra ADDRESS recall)")
        except Exception as exc:
            logger.info("presidio not available (%s); skipping", type(exc).__name__)
            _PRESIDIO = False
    return _PRESIDIO if _PRESIDIO is not False else None


# --- per-category detectors (word-level) -------------------------------------

def _phone_hits(words, raw, rmap, norm, nmap) -> list[_Hit]:
    hits: list[_Hit] = []
    for text, cmap, regex in ((raw, rmap, RAW_PHONE_RE), (norm, nmap, NORM_PHONE_RE)):
        for m in regex.finditer(text):
            digits = _digits_of(m.group())
            if len(digits) < _MIN_PHONE_DIGITS:
                continue
            span = _span_seconds(words, cmap, m.start(), m.end())
            if span is None:
                continue
            hits.append(_Hit(span[0], span[1], 0.9, _phone_preview(m.group())))
    return hits


def _email_hits(words, raw, rmap, norm, nmap) -> list[_Hit]:
    hits: list[_Hit] = []
    for text, cmap, regex in ((raw, rmap, RAW_EMAIL_RE), (norm, nmap, NORM_EMAIL_RE)):
        for m in regex.finditer(text):
            span = _span_seconds(words, cmap, m.start(), m.end())
            if span is None:
                continue
            hits.append(_Hit(span[0], span[1], 0.9, _email_preview(m.group())))
    return hits


def _address_hits(words, raw, rmap, norm, nmap) -> list[_Hit]:
    hits: list[_Hit] = []
    toks = [_clean_tok(w.text) for w in words]
    n = len(toks)
    covered: set[int] = set()

    # street suffix with a number within the previous 6 words -> 0.85
    for idx, tok in enumerate(toks):
        if tok not in STREET_SUFFIXES:
            continue
        num_idx = None
        for back in range(max(0, idx - 6), idx):
            if _is_number_tok(toks[back]):
                num_idx = back
                break
        if num_idx is None:
            continue
        end_idx = idx
        for fwd in range(idx + 1, min(n, idx + 4)):  # trailing zip extends span
            if re.fullmatch(r"\d{5}", toks[fwd]):
                end_idx = fwd
        hits.append(_Hit(float(words[num_idx].start), float(words[end_idx].end),
                         0.85, f"ADDRESS (street suffix: {tok})"))
        covered.update(range(num_idx, end_idx + 1))

    # cue phrases -> 0.6 covering the following words
    raw_lower = raw.lower()
    for cue in CUE_PHRASES:
        pos = raw_lower.find(cue)
        while pos != -1:
            cue_last_word = rmap[min(pos + len(cue) - 1, len(rmap) - 1)]
            ws = min(cue_last_word + 1, n - 1)
            we = min(cue_last_word + 8, n - 1)
            hits.append(_Hit(float(words[ws].start), float(words[we].end),
                             0.6, f"ADDRESS (cue: {cue})"))
            pos = raw_lower.find(cue, pos + 1)

    # standalone 5-digit zip (raw or spoken) -> 0.6
    for text, cmap in ((raw, rmap), (norm, nmap)):
        for m in ZIP_RE.finditer(text):
            widx = cmap[min(m.start(), len(cmap) - 1)] if cmap else None
            if widx is None or widx in covered:
                continue
            span = _span_seconds(words, cmap, m.start(), m.end())
            if span is None:
                continue
            hits.append(_Hit(span[0], span[1], 0.6, "ADDRESS (zip code)"))

    # optional presidio LOCATION -> 0.7
    analyzer = _get_presidio()
    if analyzer is not None:
        try:
            for res in analyzer.analyze(text=raw, entities=["LOCATION"], language="en"):
                span = _span_seconds(words, rmap, res.start, res.end)
                if span is None:
                    continue
                hits.append(_Hit(span[0], span[1], 0.7, "ADDRESS (location)"))
        except Exception as exc:
            logger.warning("presidio analysis failed: %s", exc)
    return hits


# --- segment-level fallback (no word timestamps) -----------------------------

def _segment_level_hit(segment, category: str) -> _Hit | None:
    tokens = str(segment.text or "").split()
    raw, _ = join_raw(tokens)
    norm, _ = normalize_spoken(tokens)
    preview = None

    if category == "phone":
        for text, regex in ((raw, RAW_PHONE_RE), (norm, NORM_PHONE_RE)):
            for m in regex.finditer(text):
                if len(_digits_of(m.group())) >= _MIN_PHONE_DIGITS:
                    preview = _phone_preview(m.group())
                    break
            if preview:
                break
    elif category == "email":
        m = RAW_EMAIL_RE.search(raw) or NORM_EMAIL_RE.search(norm)
        if m:
            preview = _email_preview(m.group())
    elif category == "address":
        raw_lower = raw.lower()
        cue = next((c for c in CUE_PHRASES if c in raw_lower), None)
        toks = [_clean_tok(t) for t in tokens]
        has_suffix_number = any(
            tok in STREET_SUFFIXES
            and any(_is_number_tok(toks[b]) for b in range(max(0, i - 6), i))
            for i, tok in enumerate(toks)
        )
        if cue:
            preview = f"ADDRESS (cue: {cue})"
        elif has_suffix_number:
            preview = "ADDRESS (street suffix)"
        elif ZIP_RE.search(raw) or ZIP_RE.search(norm):
            preview = "ADDRESS (zip code)"

    if preview is None:
        return None
    return _Hit(float(segment.start), float(segment.end), 0.4, preview,
                warnings=["segment_level_timestamps"])


# --- merge / assemble --------------------------------------------------------

def _merge_hits(hits: list[_Hit], gap_s: float = _MERGE_GAP_S) -> list[_Hit]:
    """Merge same-category hits whose gap is < gap_s (already same category)."""
    merged: list[_Hit] = []
    for hit in sorted(hits, key=lambda h: (h.start, h.end)):
        if merged and hit.start - merged[-1].end < gap_s:
            last = merged[-1]
            last.end = max(last.end, hit.end)
            last.confidence = max(last.confidence, hit.confidence)
            for w in hit.warnings:
                if w not in last.warnings:
                    last.warnings.append(w)
        else:
            merged.append(_Hit(hit.start, hit.end, hit.confidence,
                               hit.preview, list(hit.warnings)))
    return merged


def _action_dict(target) -> dict:
    action = getattr(target, "action", None)
    if isinstance(action, dict):
        return {"type": action.get("type", "mute")}
    return {"type": getattr(action, "type", "mute")}


def _target_padding_s(target) -> tuple[float, float]:
    before = float(getattr(target, "padding_before_ms", 150)) / 1000.0
    after = float(getattr(target, "padding_after_ms", 250)) / 1000.0
    return before, after


def detect_pii(transcript, policy, settings=None) -> list[RedactionEvent]:
    """Detect spoken PII per the policy's audio targets.

    transcript: policycut.audio.transcribe.Transcript
    policy:     policycut.policy.schema.PolicySpec (audio_targets used)
    settings:   policycut.config.Settings (unused; kept for contract signature)
    """
    events: list[RedactionEvent] = []
    audio_targets = list(getattr(policy, "audio_targets", []) or [])
    segments = _coerce_segments(transcript)
    if not audio_targets or not segments:
        return events

    # Absent flag (e.g. plain-dict transcript) means "trust per-segment words".
    word_level_ok = bool(_field(transcript, "has_word_timestamps", default=True))

    for target in audio_targets:
        category = getattr(target, "category", None)
        if category not in ("phone", "email", "address"):
            logger.warning("skipping unknown audio category: %r", category)
            continue

        hits: list[_Hit] = []
        for segment in segments:
            words = segment.words
            if word_level_ok and words:
                tokens = [w.text for w in words]
                raw, rmap = join_raw(tokens)
                norm, nmap = normalize_spoken(tokens)
                if not raw:
                    continue
                if category == "phone":
                    hits.extend(_phone_hits(words, raw, rmap, norm, nmap))
                elif category == "email":
                    hits.extend(_email_hits(words, raw, rmap, norm, nmap))
                else:
                    hits.extend(_address_hits(words, raw, rmap, norm, nmap))
            else:
                hit = _segment_level_hit(segment, category)
                if hit is not None:
                    hits.append(hit)

        # pad per target, then merge close hits of the same category
        pad_before, pad_after = _target_padding_s(target)
        for hit in hits:
            hit.start = max(0.0, hit.start - pad_before)
            hit.end = hit.end + pad_after

        for hit in _merge_hits(hits):
            if hit.end <= hit.start:
                continue
            events.append(RedactionEvent(
                id=new_id("e"),
                kind="audio",
                category=category,
                status="pending",
                source="auto",
                start_s=round(hit.start, 3),
                end_s=round(hit.end, 3),
                action=_action_dict(target),
                confidence=hit.confidence,
                text_preview=hit.preview,
                warnings=list(hit.warnings),
            ))

    events.sort(key=lambda e: (e.start_s, e.end_s))
    logger.info("audio PII detection: %d events (%s)", len(events),
                ", ".join(sorted({e.category for e in events})) or "none")
    return events
