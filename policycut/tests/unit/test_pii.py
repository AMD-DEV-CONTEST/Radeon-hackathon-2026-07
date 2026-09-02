"""Tests for audio PII detection (policycut/audio/pii.py).

Contract surface: detect_pii(transcript, policy) -> list of audio event
drafts with float-second spans. Behaviors under test (CONTRACTS.md section 10):
regex on raw + spoken-normalized text with char->word timestamp mapping,
merge of events with gap < 200 ms, padding 150 ms before / 250 ms after,
segment-level fallback (warnings=["segment_level_timestamps"], low confidence).
"""

from __future__ import annotations

import pytest

from policycut.audio.pii import detect_pii


# --- tolerant event accessors (drafts may be pydantic models or dicts) ------

def _get(obj, *names, default=None):
    for n in names:
        if isinstance(obj, dict):
            if n in obj:
                return obj[n]
        elif hasattr(obj, n):
            return getattr(obj, n)
    return default


def ev_start(e) -> float:
    v = _get(e, "start_s", "start")
    assert v is not None, f"event has no start: {e!r}"
    return float(v)


def ev_end(e) -> float:
    v = _get(e, "end_s", "end")
    assert v is not None, f"event has no end: {e!r}"
    return float(v)


def ev_cat(e) -> str:
    return str(_get(e, "category", default=""))


def ev_warnings(e) -> list:
    return list(_get(e, "warnings", default=[]) or [])


def ev_confidence(e) -> float:
    return float(_get(e, "confidence", default=1.0))


def by_cat(events, category):
    return [e for e in events if ev_cat(e) == category]


# --- word timing helper ------------------------------------------------------

def words_at(tokens: list[str], t0: float = 1.0, step: float = 0.5, dur: float = 0.4):
    """Lay tokens on a fixed grid: token i spans [t0+i*step, t0+i*step+dur]."""
    return [(w, t0 + i * step, t0 + i * step + dur) for i, w in enumerate(tokens)]


PAD_BEFORE = 0.150
PAD_AFTER = 0.250
TOL = 0.10


class TestPhone:
    def test_formatted_phone_with_padding(self, make_transcript, sample_policy):
        tokens = ["please", "call", "555-012-3456", "now"]
        ws = words_at(tokens)
        transcript = make_transcript([("please call 555-012-3456 now", 1.0, 3.0, ws)])
        events = detect_pii(transcript, sample_policy)
        phones = by_cat(events, "phone")
        assert len(phones) == 1, f"expected 1 phone event, got {events!r}"
        tok_start, tok_end = ws[2][1], ws[2][2]
        assert ev_start(phones[0]) == pytest.approx(tok_start - PAD_BEFORE, abs=TOL)
        assert ev_end(phones[0]) == pytest.approx(tok_end + PAD_AFTER, abs=TOL)

    def test_spoken_phone(self, make_transcript, sample_policy):
        tokens = "my phone number is five five five zero one two three four".split()
        ws = words_at(tokens)
        transcript = make_transcript([(" ".join(tokens), 1.0, 7.0, ws)])
        events = detect_pii(transcript, sample_policy)
        phones = by_cat(events, "phone")
        assert len(phones) >= 1, f"spoken phone not detected: {events!r}"
        first_digit_start = ws[4][1]   # first "five"
        last_digit_end = ws[-1][2]     # "four"
        e = phones[0]
        assert ev_start(e) <= first_digit_start + TOL
        assert ev_end(e) >= last_digit_end - TOL
        # not absurdly wide: should not start before the sentence
        assert ev_start(e) >= ws[0][1] - PAD_BEFORE - TOL


class TestEmail:
    def test_raw_email_token(self, make_transcript, sample_policy):
        tokens = ["contact", "john.doe@example.com", "today"]
        ws = words_at(tokens)
        transcript = make_transcript([("contact john.doe@example.com today", 1.0, 2.5, ws)])
        events = detect_pii(transcript, sample_policy)
        emails = by_cat(events, "email")
        assert len(emails) == 1
        assert ev_start(emails[0]) <= ws[1][1] + TOL
        assert ev_end(emails[0]) >= ws[1][2] - TOL

    def test_spoken_email(self, make_transcript, sample_policy):
        tokens = "my email is john dot doe at example dot com".split()
        ws = words_at(tokens)
        transcript = make_transcript([(" ".join(tokens), 1.0, 6.0, ws)])
        events = detect_pii(transcript, sample_policy)
        emails = by_cat(events, "email")
        assert len(emails) >= 1, f"spoken email not detected: {events!r}"
        e = emails[0]
        # spans at least from "john" to "com" (words 3..9)
        assert ev_start(e) <= ws[3][1] + TOL
        assert ev_end(e) >= ws[-1][2] - TOL


class TestAddress:
    def test_address_cue_and_suffix(self, make_transcript, sample_policy):
        tokens = "I live at 123 Main Street".split()
        ws = words_at(tokens)
        transcript = make_transcript([(" ".join(tokens), 1.0, 4.5, ws)])
        events = detect_pii(transcript, sample_policy)
        addrs = by_cat(events, "address")
        assert len(addrs) >= 1, f"address not detected: {events!r}"
        e = addrs[0]
        num_start = ws[3][1]      # "123"
        street_end = ws[5][2]     # "Street"
        assert ev_start(e) <= num_start + TOL
        assert ev_end(e) >= street_end - TOL


class TestMergeAndPadding:
    def test_close_matches_merge(self, make_transcript, sample_policy):
        # Two formatted phones whose padded spans are < 200 ms apart -> 1 event.
        ws = [
            ("call", 1.0, 1.3),
            ("555-111-2222", 1.5, 2.4),
            ("or", 2.45, 2.5),
            ("555-333-4444", 2.55, 3.4),
        ]
        transcript = make_transcript([("call 555-111-2222 or 555-333-4444", 1.0, 3.5, ws)])
        events = detect_pii(transcript, sample_policy)
        phones = by_cat(events, "phone")
        assert len(phones) == 1, f"close phone hits must merge, got {len(phones)}"
        assert ev_start(phones[0]) <= 1.5 - PAD_BEFORE + TOL
        assert ev_end(phones[0]) >= 3.4 + PAD_AFTER - TOL

    def test_distant_matches_stay_separate(self, make_transcript, sample_policy):
        ws = [
            ("call", 1.0, 1.3),
            ("555-111-2222", 1.5, 2.4),
            ("later", 2.5, 2.9),
            ("or", 5.5, 5.7),
            ("555-333-4444", 6.0, 6.9),
        ]
        transcript = make_transcript([("call 555-111-2222 later or 555-333-4444", 1.0, 7.0, ws)])
        events = detect_pii(transcript, sample_policy)
        phones = by_cat(events, "phone")
        assert len(phones) == 2, f"distant phone hits must not merge, got {len(phones)}"

    def test_padding_never_negative(self, make_transcript, sample_policy):
        # Token at the very beginning: padded start must clamp at >= 0.
        ws = [("555-012-3456", 0.05, 0.9), ("bye", 1.0, 1.2)]
        transcript = make_transcript([("555-012-3456 bye", 0.05, 1.3, ws)])
        events = detect_pii(transcript, sample_policy)
        phones = by_cat(events, "phone")
        assert len(phones) == 1
        assert ev_start(phones[0]) >= 0.0


class TestPolicyFiltering:
    def test_only_policy_categories_detected(self, make_transcript):
        from policycut.policy.schema import AudioAction, AudioTarget, PolicySpec

        email_only = PolicySpec(
            visual_targets=[],
            audio_targets=[AudioTarget(category="email", action=AudioAction(type="mute"))],
        )
        tokens = ["call", "555-012-3456", "now"]
        ws = words_at(tokens)
        transcript = make_transcript([("call 555-012-3456 now", 1.0, 2.5, ws)])
        events = detect_pii(transcript, email_only)
        assert by_cat(events, "phone") == [], "phone must be ignored when not in policy"


class TestSegmentFallback:
    def test_segment_level_timestamps_warning(self, make_transcript, sample_policy):
        # No word timestamps at all -> whole-segment event + warning + low confidence.
        transcript = make_transcript([("you can call 555-012-3456 anytime", 3.0, 6.0, [])])
        events = detect_pii(transcript, sample_policy)
        phones = by_cat(events, "phone")
        assert len(phones) == 1, f"segment-level fallback must still detect: {events!r}"
        e = phones[0]
        assert "segment_level_timestamps" in ev_warnings(e)
        assert ev_confidence(e) <= 0.5
        # spans (at least) the whole segment
        assert ev_start(e) <= 3.0 + TOL
        assert ev_end(e) >= 6.0 - TOL
