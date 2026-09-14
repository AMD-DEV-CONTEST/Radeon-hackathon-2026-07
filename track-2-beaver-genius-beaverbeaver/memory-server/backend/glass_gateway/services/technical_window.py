from __future__ import annotations

from typing import Any

from glass_gateway.domain.meeting import StoredEvidence


TECHNICAL_WINDOW_CONTRACT_VERSION = 1


def build_technical_window_contract(
    *,
    window_id: str,
    boot_session_key: str,
    start_ms: int,
    end_ms: int,
    audio_chunks: list[StoredEvidence],
    images: list[StoredEvidence],
    cross_window_images: list[StoredEvidence],
    sample_rate: int,
    image_width: int,
    image_height: int,
    audio_gaps: list[dict[str, int]],
    speech_activity: list[dict[str, Any]],
    speech_active_at_start: bool,
    speech_active_at_end: bool,
    close_reason: str,
    clock: dict[str, Any],
) -> dict[str, Any]:
    """Build the immutable bridge contract for one transport-sized window.

    A technical window is deliberately not a semantic event. It only freezes
    aligned evidence into a bounded unit that downstream processors can retry
    independently.
    """

    missing_chunk_count = sum(
        max(0, int(item["to_index"]) - int(item["from_index"]) + 1)
        for item in audio_gaps
    )
    missing_modalities = [] if images else ["image"]
    return {
        "contract_version": TECHNICAL_WINDOW_CONTRACT_VERSION,
        "kind": "multimodal_technical_window",
        "semantic_event_boundary": False,
        "window_id": window_id,
        "boot_session_key": boot_session_key,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": max(0, end_ms - start_ms),
        # Compatibility names retained for the time/audit layer introduced by MVP-04.
        "window_started_at_ms": start_ms,
        "window_ended_at_ms": end_ms,
        "audio_chunks": [
            {
                "evidence_id": item.evidence_id,
                "device_id": item.device_id,
                "boot_id": item.boot_id,
                "stream_id": item.stream_id,
                "sequence": item.sequence,
                "captured_at_ms": item.captured_at_ms,
                "captured_at_device_ms": item.captured_at_device_ms,
                "clock_synced": item.clock_synced,
                "duration_ms": item.duration_ms,
                "clock_anomaly": item.clock_anomaly,
                "clock_deviation_ms": item.clock_deviation_ms,
                "bytes": item.bytes,
            }
            for item in audio_chunks
        ],
        "audio_chunk_refs": [item.evidence_id for item in audio_chunks],
        "image_refs": [item.evidence_id for item in images],
        "images": [
            {
                "evidence_id": item.evidence_id,
                "device_id": item.device_id,
                "boot_id": item.boot_id,
                "stream_id": item.stream_id,
                "sequence": item.sequence,
                "captured_at_ms": item.captured_at_ms,
                "captured_at_device_ms": item.captured_at_device_ms,
                "clock_synced": item.clock_synced,
                "clock_anomaly": item.clock_anomaly,
                "clock_deviation_ms": item.clock_deviation_ms,
            }
            for item in images
        ],
        "cross_window_refs": [
            {
                "evidence_id": item.evidence_id,
                "captured_at_ms": item.captured_at_ms,
                "reason": "arrived_after_source_window_closed",
            }
            for item in cross_window_images
        ],
        "sample_rate": sample_rate,
        "image_size": {
            "width": image_width or None,
            "height": image_height or None,
        },
        "gap_summary": {
            "missing_audio_ranges": list(audio_gaps),
            "missing_audio_chunk_count": missing_chunk_count,
        },
        "speech_activity": {
            "active_at_start": speech_active_at_start,
            "active_at_end": speech_active_at_end,
            "markers": list(speech_activity),
            "closes_window": False,
        },
        "evidence_status": {
            "audio": "present",
            "image": "present" if images else "missing",
            "missing_modalities": missing_modalities,
            "raw_audio_chunk_count": len(audio_chunks),
            "raw_image_count": len(images),
            "cross_window_reference_count": len(cross_window_images),
        },
        "close_reason": close_reason,
        "closure_policy": "fixed_duration_or_explicit_stream_end",
        "time_basis": clock["time_basis"],
        "timezone_name": clock["timezone_name"],
        "server_anchor_ms": clock["server_anchor_ms"],
        "device_monotonic_anchor_ms": clock["device_monotonic_anchor_ms"],
    }
