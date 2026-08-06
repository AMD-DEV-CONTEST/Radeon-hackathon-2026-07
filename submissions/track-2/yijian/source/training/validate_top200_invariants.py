# -*- coding: utf-8 -*-
"""Fail-closed invariants for the licensed Top-200 candidate pipeline.

This validator never promotes machine artifacts to human gold.  It binds every
supplied stage to one pinned ranked catalog by checking the catalog selection
digest, the exact video-id set, source/authorization identity, and the hashes
that connect adjacent manifests.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CATALOG_SCHEMA = "licensed-video-catalog-v1"
DOWNLOAD_SCHEMA = "licensed-video-downloads-v1"
AUDIO_SCHEMA = "licensed-video-audio-v1"
WHISPER_SCHEMA = "licensed-video-transcripts-v1"
QWEN_SCHEMA = "licensed-video-qwen3-asr-comparison-v1"
CORRECTIONS_SCHEMA = "licensed-video-transcript-corrections-v1"
REPORT_SCHEMA = "top200-input-invariants-v1"
BV_ID_RE = re.compile(r"^BV[0-9A-Za-z]{10}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class InvariantError(RuntimeError):
    """A stage is not exactly bound to the selected licensed corpus."""


@dataclass(frozen=True)
class Snapshot:
    path: Path
    document: dict[str, Any]
    sha256: str


@dataclass(frozen=True)
class CatalogContext:
    snapshot: Snapshot
    source_id: str
    authorization_id: str
    creator_platform_id: str
    selection_sha256: str
    video_ids: tuple[str, ...]
    records: dict[str, dict[str, Any]]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_snapshot(path: Path) -> Snapshot:
    resolved = path.resolve()
    try:
        payload = resolved.read_bytes()
        document = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvariantError(f"无法读取固定 JSON {resolved}: {exc}") from exc
    if not isinstance(document, dict):
        raise InvariantError(f"JSON 根节点必须是对象：{resolved}")
    return Snapshot(
        path=resolved,
        document=document,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def require_sha256(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(normalized):
        raise InvariantError(f"{label} 缺少有效 SHA-256。")
    return normalized


def _record_index(
    document: dict[str, Any],
    *,
    label: str,
    schema: str,
    expected_ids: set[str],
    source_id: str,
    authorization_id: str,
) -> dict[str, dict[str, Any]]:
    if document.get("schemaVersion") != schema:
        raise InvariantError(f"{label} schema 不受支持。")
    if document.get("sourceId") != source_id:
        raise InvariantError(f"{label} sourceId 与 Top200 catalog 不一致。")
    if document.get("authorizationId") != authorization_id:
        raise InvariantError(f"{label} authorizationId 与 Top200 catalog 不一致。")
    records = document.get("records")
    if not isinstance(records, list):
        raise InvariantError(f"{label} records 必须是数组。")
    if document.get("recordCount") != len(records):
        raise InvariantError(f"{label} recordCount 与 records 数量不一致。")
    indexed: dict[str, dict[str, Any]] = {}
    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise InvariantError(f"{label} 第 {position} 条记录不是对象。")
        video_id = str(record.get("videoId") or "").strip()
        if not BV_ID_RE.fullmatch(video_id):
            raise InvariantError(f"{label} 第 {position} 条 videoId 无效：{video_id!r}")
        if video_id in indexed:
            raise InvariantError(f"{label} 包含重复 videoId：{video_id}")
        if record.get("sourceId") != source_id:
            raise InvariantError(f"{label} 记录 {video_id} sourceId 不一致。")
        if record.get("authorizationId") != authorization_id:
            raise InvariantError(f"{label} 记录 {video_id} authorizationId 不一致。")
        indexed[video_id] = record
    actual_ids = set(indexed)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise InvariantError(
            f"{label} videoId 集合不是 Top200 精确集合；"
            f"缺失={missing or '无'}，额外={extra or '无'}。"
        )
    return indexed


def validate_catalog(
    snapshot: Snapshot,
    *,
    expected_count: int,
    expected_catalog_sha256: str | None = None,
    expected_selection_sha256: str | None = None,
) -> CatalogContext:
    document = snapshot.document
    if document.get("schemaVersion") != CATALOG_SCHEMA:
        raise InvariantError("Top200 catalog schema 不受支持。")
    if expected_count < 1:
        raise InvariantError("expected-count 必须大于 0。")
    if expected_catalog_sha256 is not None and snapshot.sha256 != require_sha256(
        expected_catalog_sha256, "预期 catalog"
    ):
        raise InvariantError("Top200 catalog 文件 SHA-256 与固定值不一致。")
    source = document.get("source")
    if not isinstance(source, dict):
        raise InvariantError("Top200 catalog 缺少 source。")
    source_id = str(source.get("sourceId") or "").strip()
    authorization_id = str(source.get("authorizationId") or "").strip()
    creator_platform_id = str(source.get("creatorPlatformId") or "").strip()
    if not source_id or not authorization_id or not creator_platform_id:
        raise InvariantError("Top200 catalog 来源、授权或作者 UID 不完整。")
    policy = document.get("selectionPolicy")
    if not isinstance(policy, dict):
        raise InvariantError("Top200 catalog 缺少 selectionPolicy。")
    if policy.get("top") != expected_count:
        raise InvariantError("Top200 catalog selectionPolicy.top 与预期数量不一致。")
    if policy.get("split") != "whole-video-isolation":
        raise InvariantError("Top200 catalog 未固定为整视频隔离。")
    require_sha256(policy.get("inputCatalogSha256"), "Top200 输入 catalog")
    require_sha256(policy.get("metricsArtifactSha256"), "Top200 指标制品")
    records = document.get("records")
    if not isinstance(records, list):
        raise InvariantError("Top200 catalog records 必须是数组。")
    if document.get("recordCount") != expected_count or len(records) != expected_count:
        raise InvariantError(f"Top200 catalog 必须恰好包含 {expected_count} 条。")
    indexed: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise InvariantError(f"Top200 catalog 第 {position} 条不是对象。")
        video_id = str(record.get("videoId") or "").strip()
        if not BV_ID_RE.fullmatch(video_id):
            raise InvariantError(f"Top200 catalog videoId 无效：{video_id!r}")
        if video_id in indexed:
            raise InvariantError(f"Top200 catalog 包含重复 videoId：{video_id}")
        if record.get("sourceId") != source_id:
            raise InvariantError(f"Top200 catalog 记录 {video_id} sourceId 不一致。")
        if record.get("authorizationId") != authorization_id:
            raise InvariantError(
                f"Top200 catalog 记录 {video_id} authorizationId 不一致。"
            )
        if str(record.get("creatorPlatformId") or "") != creator_platform_id:
            raise InvariantError(f"Top200 catalog 记录 {video_id} 作者 UID 不一致。")
        if record.get("videoUrl") != f"https://www.bilibili.com/video/{video_id}":
            raise InvariantError(f"Top200 catalog 记录 {video_id} URL 不一致。")
        indexed[video_id] = record
        ordered_ids.append(video_id)
    declared_selection = require_sha256(
        document.get("selectionSha256"), "Top200 selection"
    )
    calculated_selection = canonical_sha256(
        {"selectionPolicy": policy, "records": records}
    )
    if declared_selection != calculated_selection:
        raise InvariantError("Top200 catalog selectionSha256 与选择内容不一致。")
    if expected_selection_sha256 is not None and declared_selection != require_sha256(
        expected_selection_sha256, "预期 selection"
    ):
        raise InvariantError("Top200 selectionSha256 与固定值不一致。")
    return CatalogContext(
        snapshot=snapshot,
        source_id=source_id,
        authorization_id=authorization_id,
        creator_platform_id=creator_platform_id,
        selection_sha256=declared_selection,
        video_ids=tuple(ordered_ids),
        records=indexed,
    )


def _validate_downloads(
    context: CatalogContext, snapshot: Snapshot
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    records = _record_index(
        snapshot.document,
        label="下载 manifest",
        schema=DOWNLOAD_SCHEMA,
        expected_ids=set(context.video_ids),
        source_id=context.source_id,
        authorization_id=context.authorization_id,
    )
    media_hashes: dict[str, str] = {}
    for video_id, record in records.items():
        if record.get("videoUrl") != context.records[video_id].get("videoUrl"):
            raise InvariantError(f"下载记录 {video_id} URL 与 catalog 不一致。")
        files = record.get("files")
        if not isinstance(files, list) or not files:
            raise InvariantError(f"下载记录 {video_id} 没有媒体文件。")
        paths: set[str] = set()
        for file_record in files:
            if not isinstance(file_record, dict):
                raise InvariantError(f"下载记录 {video_id} 文件项不是对象。")
            relative = str(file_record.get("path") or "").strip()
            if not relative or relative in paths:
                raise InvariantError(f"下载记录 {video_id} 文件路径无效或重复。")
            paths.add(relative)
            require_sha256(file_record.get("sha256"), f"下载记录 {video_id} 文件")
        media_hashes[video_id] = require_sha256(
            files[0].get("sha256"), f"下载记录 {video_id} 主媒体"
        )
    return records, media_hashes


def _validate_audio(
    context: CatalogContext,
    snapshot: Snapshot,
    *,
    media_hashes: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    records = _record_index(
        snapshot.document,
        label="音频 manifest",
        schema=AUDIO_SCHEMA,
        expected_ids=set(context.video_ids),
        source_id=context.source_id,
        authorization_id=context.authorization_id,
    )
    audio_hashes: dict[str, str] = {}
    for video_id, record in records.items():
        if record.get("videoUrl") != context.records[video_id].get("videoUrl"):
            raise InvariantError(f"音频记录 {video_id} URL 与 catalog 不一致。")
        source_media_sha = require_sha256(
            record.get("sourceMediaSha256"), f"音频记录 {video_id} 源媒体"
        )
        if source_media_sha != media_hashes[video_id]:
            raise InvariantError(f"音频记录 {video_id} 未绑定下载主媒体。")
        audio_hashes[video_id] = require_sha256(
            record.get("sha256"), f"音频记录 {video_id}"
        )
    return records, audio_hashes


def _validate_transcript_hash(record: dict[str, Any], label: str) -> str:
    segments = record.get("segments")
    if not isinstance(segments, list):
        raise InvariantError(f"{label} segments 必须是数组。")
    declared = require_sha256(record.get("transcriptSha256"), f"{label} transcript")
    if canonical_sha256(segments) != declared:
        raise InvariantError(f"{label} transcriptSha256 与 segments 不一致。")
    return declared


def _validate_whisper(
    context: CatalogContext,
    snapshot: Snapshot,
    *,
    audio_hashes: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    records = _record_index(
        snapshot.document,
        label="Whisper manifest",
        schema=WHISPER_SCHEMA,
        expected_ids=set(context.video_ids),
        source_id=context.source_id,
        authorization_id=context.authorization_id,
    )
    transcript_hashes: dict[str, str] = {}
    for video_id, record in records.items():
        if record.get("status") != "machine_draft":
            raise InvariantError(f"Whisper 记录 {video_id} 不是 machine_draft。")
        if require_sha256(record.get("audioSha256"), f"Whisper {video_id} 音频") != audio_hashes[video_id]:
            raise InvariantError(f"Whisper 记录 {video_id} 未绑定音频 manifest。")
        transcript_hashes[video_id] = _validate_transcript_hash(
            record, f"Whisper {video_id}"
        )
    return records, transcript_hashes


def _validate_qwen(
    context: CatalogContext,
    snapshot: Snapshot,
    *,
    audio_snapshot: Snapshot,
    whisper_snapshot: Snapshot,
    audio_hashes: dict[str, str],
    whisper_hashes: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    document = snapshot.document
    if document.get("status") != "machine_draft":
        raise InvariantError("Qwen3-ASR manifest 不是 machine_draft。")
    inputs = document.get("inputs")
    if not isinstance(inputs, dict):
        raise InvariantError("Qwen3-ASR manifest 缺少 inputs 来源链。")
    if inputs.get("audioManifestSha256") != audio_snapshot.sha256:
        raise InvariantError("Qwen3-ASR 未绑定当前音频 manifest 文件 SHA-256。")
    if inputs.get("whisperManifestSha256") != whisper_snapshot.sha256:
        raise InvariantError("Qwen3-ASR 未绑定当前 Whisper manifest 文件 SHA-256。")
    records = _record_index(
        document,
        label="Qwen3-ASR manifest",
        schema=QWEN_SCHEMA,
        expected_ids=set(context.video_ids),
        source_id=context.source_id,
        authorization_id=context.authorization_id,
    )
    transcript_hashes: dict[str, str] = {}
    for video_id, record in records.items():
        if record.get("status") != "machine_draft":
            raise InvariantError(f"Qwen3-ASR 记录 {video_id} 不是 machine_draft。")
        if require_sha256(record.get("audioSha256"), f"Qwen3-ASR {video_id} 音频") != audio_hashes[video_id]:
            raise InvariantError(f"Qwen3-ASR 记录 {video_id} 未绑定音频 manifest。")
        boundary = record.get("boundaryReference")
        if not isinstance(boundary, dict):
            raise InvariantError(f"Qwen3-ASR 记录 {video_id} 缺少 Whisper 边界来源。")
        if boundary.get("transcriptSha256") != whisper_hashes[video_id]:
            raise InvariantError(f"Qwen3-ASR 记录 {video_id} 未绑定当前 Whisper 转写。")
        transcript_hashes[video_id] = _validate_transcript_hash(
            record, f"Qwen3-ASR {video_id}"
        )
    return records, transcript_hashes


def _validate_corrections(
    context: CatalogContext,
    snapshot: Snapshot,
    *,
    qwen_snapshot: Snapshot,
    qwen_records: dict[str, dict[str, Any]],
    qwen_hashes: dict[str, str],
    whisper_hashes: dict[str, str],
) -> dict[str, dict[str, Any]]:
    document = snapshot.document
    if document.get("status") != "llm_corrected_candidate":
        raise InvariantError("纠错 manifest 不是 llm_corrected_candidate。")
    reference = document.get("referenceTranscripts")
    if not isinstance(reference, dict):
        raise InvariantError("纠错 manifest 缺少 Qwen3-ASR 来源链。")
    if reference.get("documentSha256") != canonical_sha256(qwen_snapshot.document):
        raise InvariantError("纠错 manifest 未绑定当前 Qwen3-ASR 文档。")
    records = _record_index(
        document,
        label="纠错 manifest",
        schema=CORRECTIONS_SCHEMA,
        expected_ids=set(context.video_ids),
        source_id=context.source_id,
        authorization_id=context.authorization_id,
    )
    for video_id, record in records.items():
        if record.get("status") != "llm_corrected_candidate":
            raise InvariantError(f"纠错记录 {video_id} 状态不受支持。")
        if record.get("originalTranscriptSha256") != whisper_hashes[video_id]:
            raise InvariantError(f"纠错记录 {video_id} 未绑定当前 Whisper 转写。")
        terminology = record.get("terminologyReference")
        if not isinstance(terminology, dict):
            raise InvariantError(f"纠错记录 {video_id} 缺少 Qwen3-ASR 术语来源。")
        if (
            terminology.get("videoId") != video_id
            or terminology.get("sourceId") != context.source_id
            or terminology.get("authorizationId") != context.authorization_id
        ):
            raise InvariantError(f"纠错记录 {video_id} 术语来源身份不一致。")
        if terminology.get("audioSha256") != qwen_records[video_id].get(
            "audioSha256"
        ):
            raise InvariantError(f"纠错记录 {video_id} 未绑定当前 Qwen3-ASR 音频。")
        if terminology.get("transcriptSha256") != qwen_hashes[video_id]:
            raise InvariantError(f"纠错记录 {video_id} 未绑定当前 Qwen3-ASR 转写。")
        if terminology.get("recordSha256") != canonical_sha256(qwen_records[video_id]):
            raise InvariantError(f"纠错记录 {video_id} 未绑定当前 Qwen3-ASR 记录。")
        declared_output = require_sha256(
            record.get("outputSha256"), f"纠错记录 {video_id} 输出"
        )
        hash_payload = dict(record)
        hash_payload.pop("outputSha256", None)
        if canonical_sha256(hash_payload) != declared_output:
            raise InvariantError(f"纠错记录 {video_id} outputSha256 无效。")
    return records


def validate_chain(
    *,
    catalog: Path,
    expected_count: int,
    expected_catalog_sha256: str | None = None,
    expected_selection_sha256: str | None = None,
    downloads: Path | None = None,
    audio: Path | None = None,
    whisper: Path | None = None,
    qwen_reference: Path | None = None,
    corrections: Path | None = None,
) -> dict[str, Any]:
    if audio is not None and downloads is None:
        raise InvariantError("校验音频必须同时提供下载 manifest。")
    if whisper is not None and audio is None:
        raise InvariantError("校验 Whisper 必须同时提供音频和下载 manifest。")
    if qwen_reference is not None and (audio is None or whisper is None):
        raise InvariantError("校验 Qwen3-ASR 必须提供下载、音频和 Whisper manifest。")
    if corrections is not None and (whisper is None or qwen_reference is None):
        raise InvariantError("校验纠错必须提供完整的前序 manifest。")

    catalog_snapshot = read_snapshot(catalog)
    context = validate_catalog(
        catalog_snapshot,
        expected_count=expected_count,
        expected_catalog_sha256=expected_catalog_sha256,
        expected_selection_sha256=expected_selection_sha256,
    )
    report: dict[str, Any] = {
        "schemaVersion": REPORT_SCHEMA,
        "validatedAt": utc_now(),
        "status": "verified",
        "trainingEligible": False,
        "requiresHumanReview": True,
        "catalog": {
            "path": str(catalog_snapshot.path),
            "sha256": catalog_snapshot.sha256,
            "selectionSha256": context.selection_sha256,
            "recordCount": len(context.video_ids),
            "videoIdsSha256": canonical_sha256(list(context.video_ids)),
            "sourceId": context.source_id,
            "authorizationId": context.authorization_id,
            "creatorPlatformId": context.creator_platform_id,
        },
        "stages": {},
    }
    media_hashes: dict[str, str] = {}
    audio_hashes: dict[str, str] = {}
    whisper_hashes: dict[str, str] = {}
    qwen_hashes: dict[str, str] = {}
    qwen_records: dict[str, dict[str, Any]] = {}
    audio_snapshot: Snapshot | None = None
    whisper_snapshot: Snapshot | None = None
    qwen_snapshot: Snapshot | None = None

    if downloads is not None:
        stage = read_snapshot(downloads)
        records, media_hashes = _validate_downloads(context, stage)
        report["stages"]["downloads"] = _stage_report(stage, len(records))
    if audio is not None:
        stage = read_snapshot(audio)
        records, audio_hashes = _validate_audio(
            context, stage, media_hashes=media_hashes
        )
        audio_snapshot = stage
        report["stages"]["audio"] = _stage_report(stage, len(records))
    if whisper is not None:
        stage = read_snapshot(whisper)
        records, whisper_hashes = _validate_whisper(
            context, stage, audio_hashes=audio_hashes
        )
        whisper_snapshot = stage
        report["stages"]["whisper"] = _stage_report(stage, len(records))
    if qwen_reference is not None:
        if audio_snapshot is None or whisper_snapshot is None:
            raise InvariantError("Qwen3-ASR 前序快照缺失。")
        stage = read_snapshot(qwen_reference)
        qwen_records, qwen_hashes = _validate_qwen(
            context,
            stage,
            audio_snapshot=audio_snapshot,
            whisper_snapshot=whisper_snapshot,
            audio_hashes=audio_hashes,
            whisper_hashes=whisper_hashes,
        )
        qwen_snapshot = stage
        report["stages"]["qwenReference"] = _stage_report(
            stage, len(qwen_records)
        )
    if corrections is not None:
        if qwen_snapshot is None:
            raise InvariantError("纠错前序 Qwen3-ASR 快照缺失。")
        stage = read_snapshot(corrections)
        records = _validate_corrections(
            context,
            stage,
            qwen_snapshot=qwen_snapshot,
            qwen_records=qwen_records,
            qwen_hashes=qwen_hashes,
            whisper_hashes=whisper_hashes,
        )
        report["stages"]["corrections"] = _stage_report(stage, len(records))
    return report


def _stage_report(snapshot: Snapshot, record_count: int) -> dict[str, Any]:
    return {
        "path": str(snapshot.path),
        "sha256": snapshot.sha256,
        "schemaVersion": snapshot.document.get("schemaVersion"),
        "recordCount": record_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=200)
    parser.add_argument("--expected-catalog-sha256")
    parser.add_argument("--expected-selection-sha256")
    parser.add_argument("--downloads", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--whisper", type=Path)
    parser.add_argument("--qwen-reference", type=Path)
    parser.add_argument("--corrections", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = validate_chain(
            catalog=args.catalog,
            expected_count=args.expected_count,
            expected_catalog_sha256=args.expected_catalog_sha256,
            expected_selection_sha256=args.expected_selection_sha256,
            downloads=args.downloads,
            audio=args.audio,
            whisper=args.whisper,
            qwen_reference=args.qwen_reference,
            corrections=args.corrections,
        )
        if args.output is not None:
            atomic_write_json(args.output.resolve(), report)
    except InvariantError as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
