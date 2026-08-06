from __future__ import annotations

from itertools import combinations
import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMCrossPlatformDedupLedgerV2"


class GTMCrossPlatformDedupError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"https?://\S+|www\.\S+|@[\w.-]+", " ", text)
    return " ".join(re.findall(r"[\w]+", text, flags=re.UNICODE))


def _shingles(text: str, width: int = 3) -> set[str]:
    tokens = text.split()
    if len(tokens) < width:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[index:index + width]) for index in range(len(tokens) - width + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    # Missing text on both sides is absence of evidence, never evidence of
    # identity.  Treating two empty feature sets as a perfect match creates
    # false duplicate decisions for unrelated records without transcripts.
    return len(left & right) / len(left | right) if left or right else 0.0


def _containment(left: set[str], right: set[str]) -> float:
    smaller = min(len(left), len(right))
    return len(left & right) / smaller if smaller else 0.0


def _simhash(text: str) -> int:
    features = _shingles(text, 2)
    vector = [0] * 64
    for feature in features:
        value = int.from_bytes(hashlib.sha256(feature.encode()).digest()[:8], "big")
        for index in range(64):
            vector[index] += 1 if value & (1 << index) else -1
    output = 0
    for index, score in enumerate(vector):
        if score >= 0:
            output |= 1 << index
    return output


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def compile_cross_platform_dedup(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    prepared = []
    ids: set[str] = set()
    for raw in records:
        record_id = str(raw.get("record_id") or "")
        platform = str(raw.get("platform") or "")
        source_url = str(raw.get("source_url") or "")
        if not record_id or record_id in ids or not platform or not source_url.startswith("https://"):
            raise GTMCrossPlatformDedupError("records require unique IDs, platform, and public HTTPS source")
        ids.add(record_id)
        normalized = normalize_text(raw.get("text"))
        transcript = normalize_text(raw.get("transcript"))
        verified_translation = normalize_text(raw.get("verified_translation_text"))
        translation_receipts = sorted({str(value) for value in raw.get("translation_receipt_sha256s", [])})
        if verified_translation and not translation_receipts:
            raise GTMCrossPlatformDedupError(f"{record_id} translation text lacks a verified receipt")
        frame_hashes = sorted({str(value) for value in raw.get("perceptual_frame_hashes", [])})
        audio_hashes = sorted({str(value) for value in raw.get("audio_landmark_hashes", [])})
        exact_payload_supplied = bool(raw.get("exact_payload_sha256"))
        fingerprint_evidence_present = bool(
            normalized or transcript or frame_hashes or audio_hashes or exact_payload_supplied
        )
        prepared.append({
            "record_id": record_id,
            "platform": platform,
            "source_url": source_url,
            "language": str(raw.get("language") or "und"),
            "normalized_text_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
            "normalized_transcript_sha256": hashlib.sha256(transcript.encode()).hexdigest(),
            "verified_translation_sha256": hashlib.sha256(verified_translation.encode()).hexdigest() if verified_translation else None,
            "translation_receipt_sha256s": translation_receipts,
            "text_tokens": sorted(set(normalized.split())),
            "text_shingles": sorted(_shingles(normalized)),
            "transcript_shingles": sorted(_shingles(transcript)),
            "text_simhash_64": f"{_simhash(normalized):016x}" if normalized else None,
            "perceptual_frame_hashes": frame_hashes,
            "audio_landmark_hashes": audio_hashes,
            "exact_payload_sha256": str(raw.get("exact_payload_sha256") or hashlib.sha256((normalized + "\n" + transcript + "\n" + "|".join(frame_hashes) + "\n" + "|".join(audio_hashes)).encode()).hexdigest()),
            "fingerprint_evidence_present": fingerprint_evidence_present,
            "quota_credit": 0,
        })

    decisions = []
    for left, right in combinations(prepared, 2):
        pair_material = f"{left['record_id']}|{right['record_id']}"
        text_jaccard = _jaccard(set(left["text_shingles"]), set(right["text_shingles"]))
        token_containment = _containment(set(left["text_tokens"]), set(right["text_tokens"]))
        transcript_jaccard = _jaccard(set(left["transcript_shingles"]), set(right["transcript_shingles"]))
        simhash_distance = (
            _hamming(int(left["text_simhash_64"], 16), int(right["text_simhash_64"], 16))
            if left["text_simhash_64"] and right["text_simhash_64"]
            else 64
        )
        frame_containment = _containment(set(left["perceptual_frame_hashes"]), set(right["perceptual_frame_hashes"]))
        audio_containment = _containment(set(left["audio_landmark_hashes"]), set(right["audio_landmark_hashes"]))
        same_translation = bool(
            left["verified_translation_sha256"] and left["verified_translation_sha256"] == right["verified_translation_sha256"]
        )
        if (
            left["fingerprint_evidence_present"]
            and right["fingerprint_evidence_present"]
            and left["exact_payload_sha256"] == right["exact_payload_sha256"]
        ):
            decision, reason = "exact_mirror", "Exact payload fingerprints match."
        elif same_translation and left["language"] != right["language"]:
            decision, reason = "translation_mirror", "Verified canonical translations match across languages."
        elif max(frame_containment, audio_containment) >= 0.8:
            decision, reason = "clip_or_light_media_edit", "Perceptual frame or audio landmark containment is at least 0.8."
        elif max(text_jaccard, transcript_jaccard, token_containment) >= 0.75 or simhash_distance <= 8:
            decision, reason = "light_rewrite_or_repost", "Lexical, transcript, or SimHash similarity crosses the duplicate-review threshold."
        elif max(text_jaccard, transcript_jaccard) >= 0.55 or simhash_distance <= 16:
            decision, reason = "ambiguous_manual_review", "Moderate semantic-form similarity requires a human decision."
        else:
            decision, reason = "distinct", "No deterministic duplicate threshold is met."
        decisions.append({
            "pair_id": f"pair:{hashlib.sha256(pair_material.encode()).hexdigest()[:24]}",
            "left_record_id": left["record_id"], "right_record_id": right["record_id"],
            "decision": decision, "reason": reason,
            "text_jaccard": round(text_jaccard, 6), "token_containment": round(token_containment, 6),
            "transcript_jaccard": round(transcript_jaccard, 6),
            "simhash_hamming_distance": simhash_distance, "frame_containment": round(frame_containment, 6),
            "audio_containment": round(audio_containment, 6), "same_verified_translation": same_translation,
            "automatic_episode_merge_allowed": decision == "exact_mirror",
            "quota_credit": 0,
        })

    decision_counts = {decision: sum(row["decision"] == decision for row in decisions) for decision in (
        "exact_mirror", "translation_mirror", "clip_or_light_media_edit", "light_rewrite_or_repost", "ambiguous_manual_review", "distinct"
    )}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "record_count": len(prepared), "pair_count": len(decisions),
        "records": sorted(prepared, key=lambda row: row["record_id"]),
        "pair_decisions": decisions, "decision_counts": decision_counts,
        "policy": {
            "exact_mirror_auto_merge_allowed": True,
            "translation_clip_or_rewrite_auto_merge_allowed": False,
            "ambiguous_pair_auto_merge_allowed": False,
            "dedup_ledger_grants_case_credit": False,
            "verified_translation_receipt_required": True,
        },
        "truth_boundary": "Deterministic fingerprints detect duplicate risk; non-exact pairs require review and this ledger never creates case quota credit.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_cross_platform_dedup(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMCrossPlatformDedupError("cross-platform dedup seal is invalid")
    records = payload.get("records"); pairs = payload.get("pair_decisions")
    if not isinstance(records, list) or payload.get("record_count") != len(records):
        raise GTMCrossPlatformDedupError("dedup record aggregate drifted")
    expected_pairs = len(records) * (len(records) - 1) // 2
    if not isinstance(pairs, list) or payload.get("pair_count") != len(pairs) or len(pairs) != expected_pairs:
        raise GTMCrossPlatformDedupError("dedup pair coverage is incomplete")
    if any(row.get("quota_credit") != 0 for row in records + pairs):
        raise GTMCrossPlatformDedupError("dedup analysis minted quota credit")
    if any(row.get("decision") != "exact_mirror" and row.get("automatic_episode_merge_allowed") is not False for row in pairs):
        raise GTMCrossPlatformDedupError("a non-exact pair can auto-merge")


__all__ = ["GTMCrossPlatformDedupError", "compile_cross_platform_dedup", "normalize_text", "verify_cross_platform_dedup"]
