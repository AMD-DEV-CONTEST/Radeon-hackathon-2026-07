from __future__ import annotations

import hashlib
from typing import Any


_IGNORED_ASR_STATUSES = {
    "asr_failed",
    "speech_unrecognized",
    "tail_duplicate",
    "tail_unrecognized",
}


def align_asr_segments(
    *,
    turns: list[dict[str, Any]],
    asr_result: dict[str, Any] | None,
    ambiguity_margin: float = 0.15,
    minimum_overlap_ratio: float = 0.10,
) -> dict[str, Any]:
    """Align timestamped ASR evidence without inventing speaker attribution."""

    asr_result = dict(asr_result or {})
    asr_run_id = str(asr_result.get("asr_run_id") or "").strip()
    normalized_turns = [dict(item) for item in turns]
    turn_refs: dict[str, list[str]] = {
        str(item.get("turn_id") or ""): list(item.get("asr_segment_refs") or [])
        for item in normalized_turns
    }
    assignments: list[dict[str, Any]] = []
    transcript_by_speaker: dict[str, list[str]] = {}
    segments = [
        item
        for item in asr_result.get("segments") or []
        if isinstance(item, dict)
    ]
    for index, raw in enumerate(segments):
        assignment = _align_one(
            raw,
            index=index,
            asr_run_id=asr_run_id,
            turns=normalized_turns,
            ambiguity_margin=ambiguity_margin,
            minimum_overlap_ratio=minimum_overlap_ratio,
        )
        assignments.append(assignment)
        assigned_speaker = str(assignment.get("speaker_local_id") or "")
        if assignment["status"] != "assigned" or not assigned_speaker:
            continue
        segment_id = str(assignment["asr_segment_id"])
        for turn_id in assignment.get("turn_ids") or []:
            refs = turn_refs.setdefault(str(turn_id), [])
            if segment_id not in refs:
                refs.append(segment_id)
        text = str(assignment.get("text") or "").strip()
        if text and text not in transcript_by_speaker.setdefault(assigned_speaker, []):
            transcript_by_speaker[assigned_speaker].append(text)

    for turn in normalized_turns:
        turn["asr_segment_refs"] = turn_refs.get(str(turn.get("turn_id") or ""), [])

    accepted = [item for item in assignments if item["status"] == "assigned"]
    ambiguous = [
        item for item in assignments if item["status"] == "ambiguous_speaker"
    ]
    unknown = [
        item
        for item in assignments
        if item["status"].startswith("speaker_unknown")
    ]
    if not asr_run_id and not segments:
        status = "not_available"
    elif accepted and not ambiguous and not unknown:
        status = "completed"
    elif accepted:
        status = "partial"
    elif ambiguous:
        status = "ambiguous"
    elif unknown:
        status = "speaker_unknown"
    else:
        status = "no_assignable_transcript"
    return {
        "status": status,
        "asr_run_id": asr_run_id or None,
        "timing_precision": asr_result.get("timing_precision"),
        "assignments": assignments,
        "turns": normalized_turns,
        "transcript_by_speaker": {
            key: "\n".join(values) for key, values in transcript_by_speaker.items()
        },
        "assigned_count": len(accepted),
        "ambiguous_count": len(ambiguous),
        "unknown_count": len(unknown),
    }


def _align_one(
    raw: dict[str, Any],
    *,
    index: int,
    asr_run_id: str,
    turns: list[dict[str, Any]],
    ambiguity_margin: float,
    minimum_overlap_ratio: float,
) -> dict[str, Any]:
    text = str(raw.get("text") or "").strip()
    segment_id = _segment_id(raw, index=index, asr_run_id=asr_run_id)
    base = {
        "asr_segment_id": segment_id,
        "segment_index": index,
        "text": text,
        "purpose": raw.get("purpose"),
        "speaker_local_id": None,
        "voice_candidate_id": None,
        "turn_ids": [],
        "candidates": [],
    }
    status = str(raw.get("status") or "completed")
    if status in _IGNORED_ASR_STATUSES or not text:
        return {**base, "status": "ignored", "reason_codes": [status or "empty_text"]}
    if raw.get("start_ms") is None or raw.get("end_ms") is None:
        return {
            **base,
            "status": "speaker_unknown_no_timestamp",
            "reason_codes": ["asr_segment_has_no_timestamp"],
        }
    start_ms, end_ms = int(raw["start_ms"]), int(raw["end_ms"])
    if start_ms < 0 or end_ms <= start_ms:
        return {
            **base,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "status": "speaker_unknown_invalid_timestamp",
            "reason_codes": ["invalid_asr_timestamp"],
        }
    duration_ms = end_ms - start_ms
    by_speaker: dict[str, dict[str, Any]] = {}
    for turn in turns:
        overlap_ms = max(
            0,
            min(end_ms, int(turn["end_ms"])) - max(start_ms, int(turn["start_ms"])),
        )
        if not overlap_ms:
            continue
        speaker = str(turn.get("speaker_local_id") or "")
        if not speaker:
            continue
        item = by_speaker.setdefault(
            speaker,
            {
                "speaker_local_id": speaker,
                "voice_candidate_id": turn.get("voice_candidate_id"),
                "overlap_ms": 0,
                "turn_ids": [],
                "has_overlap_turn": False,
            },
        )
        item["overlap_ms"] += overlap_ms
        item["turn_ids"].append(turn.get("turn_id"))
        item["has_overlap_turn"] = item["has_overlap_turn"] or bool(turn.get("overlap"))
    ranked = sorted(by_speaker.values(), key=lambda item: item["overlap_ms"], reverse=True)
    candidates = [
        {
            **item,
            "coverage_ratio": round(min(1.0, item["overlap_ms"] / duration_ms), 6),
        }
        for item in ranked
    ]
    timed = {**base, "start_ms": start_ms, "end_ms": end_ms, "candidates": candidates}
    if not candidates or candidates[0]["coverage_ratio"] < minimum_overlap_ratio:
        return {
            **timed,
            "status": "speaker_unknown_no_overlap",
            "reason_codes": ["no_speaker_turn_overlap"],
        }
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    full_window_multi_speaker = raw.get("purpose") == "full_window" and second is not None
    close_coverage = bool(
        second
        and float(top["coverage_ratio"]) - float(second["coverage_ratio"])
        < max(0.0, float(ambiguity_margin))
    )
    uncertain_overlap = bool(top.get("has_overlap_turn"))
    if full_window_multi_speaker or close_coverage or uncertain_overlap:
        reasons = []
        if full_window_multi_speaker:
            reasons.append("full_window_contains_multiple_speakers")
        if close_coverage:
            reasons.append("speaker_coverage_too_close")
        if uncertain_overlap:
            reasons.append("overlap_speech")
        return {**timed, "status": "ambiguous_speaker", "reason_codes": reasons}
    return {
        **timed,
        "status": "assigned",
        "speaker_local_id": top["speaker_local_id"],
        "voice_candidate_id": top.get("voice_candidate_id"),
        "turn_ids": list(dict.fromkeys(top["turn_ids"])),
        "coverage_ratio": top["coverage_ratio"],
        "reason_codes": [],
    }


def _segment_id(raw: dict[str, Any], *, index: int, asr_run_id: str) -> str:
    explicit = str(raw.get("asr_segment_id") or raw.get("segment_id") or "").strip()
    if explicit:
        return explicit
    payload = "\n".join(
        (
            asr_run_id,
            str(index),
            str(raw.get("start_ms")),
            str(raw.get("end_ms")),
            str(raw.get("text") or ""),
        )
    )
    return "asr-segment:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
