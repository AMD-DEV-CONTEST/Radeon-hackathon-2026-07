# -*- coding: utf-8 -*-
"""训练金标的受信来源链与独立人工审批制品。

本模块故意不读取 teaching unit 内联的 ``review`` 字段。训练资格只能由：

1. 以 SHA-256 固定的来源链 registry；
2. 以 SHA-256 固定的审核人 allowlist；
3. 以 SHA-256 固定的独立 approval JSONL；

共同授予。任一输入缺失或内容不一致都默认拒绝。
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


SOURCE_CHAIN_REGISTRY_SCHEMA = "trusted-source-chain-registry-v1"
SOURCE_CHAIN_BINDING_SCHEMA = "trusted-source-chain-binding-v1"
REVIEWER_REGISTRY_SCHEMA = "human-reviewer-registry-v1"
REVIEW_APPROVAL_SCHEMA = "human-review-approval-v1"
REQUIRED_REVIEW_SCOPES = frozenset(
    {"transcript", "board", "semantics", "source_chain"}
)
MANIFEST_SCHEMAS = {
    "catalog": "licensed-video-catalog-v1",
    "downloads": "licensed-video-downloads-v1",
    "audio": "licensed-video-audio-v1",
    "transcripts": "licensed-video-transcripts-v1",
    "frames": "licensed-video-frame-evidence-v1",
}
MANIFEST_KEYS = tuple(MANIFEST_SCHEMAS)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VIDEO_ID_RE = re.compile(r"^BV[0-9A-Za-z]{10}$")
STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".flv"}


class TrustError(ValueError):
    """来源链或审核制品不是受信输入。"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TrustError(message)


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise TrustError(f"制品无法规范化为JSON：{exc}") from exc


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sha256(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower()
    require(bool(SHA256_RE.fullmatch(normalized)), f"{label}缺少有效SHA-256")
    return normalized


def _read_pinned_bytes(path: Path, expected_sha256: str, label: str) -> bytes:
    """只读取一次：同一份字节既用于固定哈希，也用于后续解析。"""
    expected = validate_sha256(expected_sha256, f"{label}固定值")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise TrustError(f"无法读取{label}：{path}: {exc}") from exc
    actual = hashlib.sha256(payload).hexdigest()
    require(actual == expected, f"{label}SHA-256与受信固定值不一致")
    return payload


def _read_pinned_json(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    payload = _read_pinned_bytes(path, expected_sha256, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrustError(f"无法读取{label}：{path}: {exc}") from exc
    require(isinstance(value, dict), f"{label}根节点必须是对象")
    return value


def _safe_relative_path(root: Path, value: Any, label: str) -> Path:
    text = str(value or "").strip()
    require(bool(text), f"{label}缺少路径")
    relative = Path(text)
    require(not relative.is_absolute(), f"{label}必须使用registry相对路径")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    require(
        resolved == resolved_root or resolved_root in resolved.parents,
        f"{label}路径逃逸出registry目录",
    )
    return resolved


def _records_by_video(manifest: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    records = manifest.get("records")
    require(isinstance(records, list), f"{label} records必须是数组")
    declared = manifest.get("recordCount")
    require(declared in (None, len(records)), f"{label} recordCount不一致")
    indexed: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records, 1):
        require(isinstance(record, dict), f"{label}第{index}条记录必须是对象")
        video_id = str(record.get("videoId") or "").strip()
        require(bool(VIDEO_ID_RE.fullmatch(video_id)), f"{label}第{index}条videoId无效")
        require(video_id not in indexed, f"{label}含重复videoId：{video_id}")
        indexed[video_id] = record
    return indexed


def _validate_record_identity(
    record: dict[str, Any],
    *,
    source_id: str,
    authorization_id: str,
    video_id: str,
    label: str,
    require_url: bool = True,
) -> None:
    require(record.get("sourceId") == source_id, f"{label} sourceId不一致")
    require(
        record.get("authorizationId") == authorization_id,
        f"{label} authorizationId不一致",
    )
    require(record.get("videoId") == video_id, f"{label} videoId不一致")
    if require_url:
        require(
            record.get("videoUrl") == f"https://www.bilibili.com/video/{video_id}",
            f"{label} videoUrl与videoId不一致",
        )


def _validate_manifest_identity(
    manifest: dict[str, Any],
    kind: str,
    source_id: str,
    authorization_id: str,
) -> None:
    require(
        manifest.get("schemaVersion") == MANIFEST_SCHEMAS[kind],
        f"{kind} manifest schema不受支持",
    )
    if kind == "catalog":
        source = manifest.get("source") or {}
        require(source.get("sourceId") == source_id, "catalog sourceId不一致")
        require(
            source.get("authorizationId") == authorization_id,
            "catalog authorizationId不一致",
        )
    else:
        require(manifest.get("sourceId") == source_id, f"{kind} sourceId不一致")
        require(
            manifest.get("authorizationId") == authorization_id,
            f"{kind} authorizationId不一致",
        )


def _optional_rehash(root: Path, path_value: Any, expected_sha: str, label: str) -> None:
    """文件仍在私有工作区时重算；不在时由已固定 manifest 哈希担保。"""
    path = _safe_relative_path(root, path_value, label)
    if path.exists():
        require(path.is_file(), f"{label}不是文件")
        require(sha256_file(path) == expected_sha, f"{label}文件SHA-256不一致")


class SourceChainRegistry:
    """已固定哈希的 catalog→download→audio→transcript→frame 来源链。"""

    def __init__(
        self,
        path: Path,
        registry_sha256: str,
        bindings: dict[str, Any],
    ) -> None:
        self.path = path
        self.registry_sha256 = registry_sha256
        self._bindings = bindings

    @classmethod
    def load(cls, path: Path, expected_sha256: str) -> "SourceChainRegistry":
        path = Path(path).resolve()
        registry_sha = validate_sha256(expected_sha256, "来源链registry固定值")
        document = _read_pinned_json(path, registry_sha, "来源链registry")
        if document.get("schemaVersion") == "trusted-source-chain-registry-bundle-v1":
            snapshots = document.get("snapshots")
            require(isinstance(snapshots, list) and snapshots, "来源链registry bundle为空")
            bindings: dict[str, Any] = {}
            for index, snapshot in enumerate(snapshots, 1):
                require(isinstance(snapshot, dict), f"来源链bundle第{index}条无效")
                child_path = _safe_relative_path(
                    path.parent, snapshot.get("path"), f"来源链bundle第{index}条"
                )
                child = cls.load(child_path, snapshot.get("sha256"))
                for chain_id, binding_value in child._bindings.items():
                    child_bindings = (
                        binding_value if isinstance(binding_value, list) else [binding_value]
                    )
                    if chain_id not in bindings:
                        bindings[chain_id] = copy.deepcopy(child_bindings[0])
                        child_bindings = child_bindings[1:]
                    for binding in child_bindings:
                        existing = bindings[chain_id]
                        versions = existing if isinstance(existing, list) else [existing]
                        binding_hash = canonical_json_sha256(binding)
                        if any(canonical_json_sha256(row) == binding_hash for row in versions):
                            continue
                        bindings[chain_id] = [*versions, copy.deepcopy(binding)]
            return cls(path, registry_sha, bindings)
        require(
            document.get("schemaVersion") == SOURCE_CHAIN_REGISTRY_SCHEMA,
            "来源链registry schema不受支持",
        )
        entries = document.get("entries")
        require(isinstance(entries, list) and bool(entries), "来源链registry entries为空")
        bindings: dict[str, dict[str, Any]] = {}
        for index, entry in enumerate(entries, 1):
            require(isinstance(entry, dict), f"来源链第{index}条必须是对象")
            chain_id = str(entry.get("chainId") or "").strip()
            require(bool(STABLE_ID_RE.fullmatch(chain_id)), f"来源链第{index}条chainId无效")
            require(chain_id not in bindings, f"来源链chainId重复：{chain_id}")
            binding = cls._load_entry(path.parent, entry)
            binding["registrySha256"] = registry_sha
            bindings[chain_id] = binding
        return cls(path, registry_sha, bindings)

    @staticmethod
    def _load_entry(registry_root: Path, entry: dict[str, Any]) -> dict[str, Any]:
        chain_id = str(entry["chainId"])
        source_id = str(entry.get("sourceId") or "").strip()
        authorization_id = str(entry.get("authorizationId") or "").strip()
        video_id = str(entry.get("videoId") or "").strip()
        require(bool(source_id), f"来源链 {chain_id} 缺少sourceId")
        require(bool(authorization_id), f"来源链 {chain_id} 缺少authorizationId")
        require(bool(VIDEO_ID_RE.fullmatch(video_id)), f"来源链 {chain_id} videoId无效")
        manifests_meta = entry.get("manifests")
        require(isinstance(manifests_meta, dict), f"来源链 {chain_id} 缺少manifests")
        require(
            set(manifests_meta) == set(MANIFEST_KEYS),
            f"来源链 {chain_id} 必须固定catalog/download/audio/transcript/frame manifests",
        )
        workspace_root = _safe_relative_path(
            registry_root,
            entry.get("workspaceRoot", "."),
            f"来源链 {chain_id} workspaceRoot",
        )
        documents: dict[str, dict[str, Any]] = {}
        manifest_hashes: dict[str, str] = {}
        for kind in MANIFEST_KEYS:
            meta = manifests_meta[kind]
            require(isinstance(meta, dict), f"来源链 {chain_id} {kind}描述必须是对象")
            manifest_path = _safe_relative_path(
                registry_root, meta.get("path"), f"来源链 {chain_id} {kind}"
            )
            manifest_hash = validate_sha256(
                meta.get("sha256"), f"来源链 {chain_id} {kind}"
            )
            documents[kind] = _read_pinned_json(
                manifest_path, manifest_hash, f"来源链 {chain_id} {kind} manifest"
            )
            manifest_hashes[kind] = manifest_hash
            _validate_manifest_identity(
                documents[kind], kind, source_id, authorization_id
            )

        records = {
            kind: _records_by_video(document, f"来源链 {chain_id} {kind}")
            for kind, document in documents.items()
        }
        for kind, indexed in records.items():
            require(video_id in indexed, f"来源链 {chain_id} {kind}缺少videoId {video_id}")
        catalog_record = records["catalog"][video_id]
        download_record = records["downloads"][video_id]
        audio_record = records["audio"][video_id]
        transcript_record = records["transcripts"][video_id]
        frame_record = records["frames"][video_id]
        for kind, record in (
            ("catalog", catalog_record),
            ("downloads", download_record),
            ("audio", audio_record),
            ("transcripts", transcript_record),
            ("frames", frame_record),
        ):
            _validate_record_identity(
                record,
                source_id=source_id,
                authorization_id=authorization_id,
                video_id=video_id,
                label=f"来源链 {chain_id} {kind}记录",
                require_url=kind not in {"transcripts"},
            )

        catalog_source = documents["catalog"].get("source") or {}
        creator = str(catalog_source.get("creator") or "").strip()
        creator_platform_id = str(
            catalog_source.get("creatorPlatformId") or ""
        ).strip()
        require(bool(creator), f"来源链 {chain_id} catalog缺少作者")
        require(bool(creator_platform_id), f"来源链 {chain_id} catalog缺少作者UID")
        require(
            str(catalog_record.get("creatorPlatformId") or "")
            == creator_platform_id,
            f"来源链 {chain_id} catalog记录作者UID不一致",
        )
        require(catalog_record.get("availability") == "public", f"来源链 {chain_id} 不是公开视频")
        files = download_record.get("files")
        require(isinstance(files, list) and bool(files), f"来源链 {chain_id} 下载记录缺少文件")
        audio_parent_sha = validate_sha256(
            audio_record.get("sourceMediaSha256"), f"来源链 {chain_id} 音频父媒体"
        )
        media_candidates = [
            item
            for item in files
            if isinstance(item, dict)
            and Path(str(item.get("path") or "")).suffix.lower() in VIDEO_SUFFIXES
            and str(item.get("sha256") or "").lower() == audio_parent_sha
        ]
        require(
            len(media_candidates) == 1,
            f"来源链 {chain_id} 下载媒体与音频sourceMediaSha256不能唯一匹配",
        )
        media_record = media_candidates[0]
        media_sha = validate_sha256(media_record.get("sha256"), f"来源链 {chain_id} 媒体")
        audio_sha = validate_sha256(audio_record.get("sha256"), f"来源链 {chain_id} 音频")
        _optional_rehash(
            workspace_root, media_record.get("path"), media_sha, f"来源链 {chain_id} 媒体"
        )
        _optional_rehash(
            workspace_root, audio_record.get("audioPath"), audio_sha, f"来源链 {chain_id} 音频"
        )
        require(
            transcript_record.get("status") in {"machine_draft", "llm_corrected_candidate"},
            f"来源链 {chain_id} 转写必须保持候选状态",
        )
        require(
            validate_sha256(
                transcript_record.get("audioSha256"), f"来源链 {chain_id} 转写音频"
            ) == audio_sha,
            f"来源链 {chain_id} 转写audioSha256不一致",
        )
        transcript_segments = transcript_record.get("segments")
        require(isinstance(transcript_segments, list), f"来源链 {chain_id} 转写segments无效")
        machine_transcript_sha = validate_sha256(
            transcript_record.get("transcriptSha256"), f"来源链 {chain_id} 转写"
        )
        require(
            canonical_json_sha256(transcript_segments) == machine_transcript_sha,
            f"来源链 {chain_id} 转写segments哈希不一致",
        )

        frame_manifest = documents["frames"]
        inputs = frame_manifest.get("inputs") or {}
        for kind in ("downloads", "audio", "transcripts"):
            require(isinstance(inputs.get(kind), dict), f"来源链 {chain_id} 帧清单缺少{kind}输入")
            require(
                validate_sha256(
                    inputs[kind].get("sha256"), f"来源链 {chain_id} 帧清单{kind}输入"
                ) == manifest_hashes[kind],
                f"来源链 {chain_id} 帧清单{kind}输入哈希不一致",
            )
        require(frame_manifest.get("status") == "machine_candidate", f"来源链 {chain_id} 帧清单状态错误")
        require(frame_record.get("status") == "machine_candidate", f"来源链 {chain_id} 帧记录状态错误")
        video = frame_record.get("video") or {}
        frame_audio = frame_record.get("audio") or {}
        require(
            validate_sha256(video.get("sha256"), f"来源链 {chain_id} 帧视频") == media_sha,
            f"来源链 {chain_id} 帧视频哈希不一致",
        )
        require(
            validate_sha256(frame_audio.get("sha256"), f"来源链 {chain_id} 帧音频") == audio_sha,
            f"来源链 {chain_id} 帧音频哈希不一致",
        )
        require(
            validate_sha256(
                frame_audio.get("sourceMediaSha256"), f"来源链 {chain_id} 帧音频父媒体"
            ) == media_sha,
            f"来源链 {chain_id} 帧音频父媒体哈希不一致",
        )
        require(
            validate_sha256(
                frame_record.get("transcriptSha256"), f"来源链 {chain_id} 帧转写"
            ) == machine_transcript_sha,
            f"来源链 {chain_id} 帧转写哈希不一致",
        )
        duration = (video.get("probe") or {}).get("durationSeconds")
        require(
            isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and math.isfinite(float(duration))
            and float(duration) > 0,
            f"来源链 {chain_id} 媒体时长无效",
        )
        duration_ms = max(1, math.ceil(float(duration) * 1000))
        extractor = frame_manifest.get("extractor")
        require(isinstance(extractor, dict), f"来源链 {chain_id} 帧清单缺少extractor")
        fallback_policy = extractor.get("tailFallbackPolicy")
        require(isinstance(fallback_policy, dict), f"来源链 {chain_id} 帧清单缺少尾帧回退策略")
        fallback_window_ms = fallback_policy.get("windowMs")
        fallback_offsets_ms = fallback_policy.get("backwardOffsetsMs")
        require(
            isinstance(fallback_window_ms, int)
            and not isinstance(fallback_window_ms, bool)
            and fallback_window_ms >= 0,
            f"来源链 {chain_id} 尾帧回退窗口无效",
        )
        require(
            isinstance(fallback_offsets_ms, list)
            and bool(fallback_offsets_ms)
            and all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and value > 0
                for value in fallback_offsets_ms
            )
            and len(set(fallback_offsets_ms)) == len(fallback_offsets_ms),
            f"来源链 {chain_id} 尾帧回退偏移无效",
        )
        require(
            fallback_policy.get("recordsEveryExtractionRequest") is True,
            f"来源链 {chain_id} 尾帧回退必须记录每次实际请求",
        )
        frames = frame_record.get("frames")
        require(isinstance(frames, list) and bool(frames), f"来源链 {chain_id} 缺少帧记录")
        declared_frame_count = frame_record.get("frameCount")
        require(declared_frame_count in (None, len(frames)), f"来源链 {chain_id} frameCount不一致")
        frame_index: dict[tuple[int, str], dict[str, Any]] = {}
        for frame_index_number, frame in enumerate(frames, 1):
            require(isinstance(frame, dict), f"来源链 {chain_id} 第{frame_index_number}帧无效")
            requested_timestamp = frame.get("requestedTimestampMs")
            planned_timestamp = frame.get("plannedRequestedTimestampMs")
            extraction_timestamp = frame.get("extractionRequestedTimestampMs")
            for timestamp_label, timestamp in (
                ("requestedTimestampMs", requested_timestamp),
                ("plannedRequestedTimestampMs", planned_timestamp),
                ("extractionRequestedTimestampMs", extraction_timestamp),
            ):
                require(
                    isinstance(timestamp, int)
                    and not isinstance(timestamp, bool)
                    and 0 <= timestamp < duration_ms,
                    f"来源链 {chain_id} 第{frame_index_number}帧{timestamp_label}超出媒体时长",
                )
            require(
                planned_timestamp == requested_timestamp,
                f"来源链 {chain_id} 第{frame_index_number}帧计划与请求时间不一致",
            )
            adjustment_ms = frame.get("extractionTimestampAdjustmentMs")
            require(
                isinstance(adjustment_ms, int)
                and not isinstance(adjustment_ms, bool)
                and adjustment_ms == extraction_timestamp - planned_timestamp,
                f"来源链 {chain_id} 第{frame_index_number}帧实际抽帧偏移不一致",
            )
            fallback_applied = frame.get("tailFallbackApplied")
            require(
                isinstance(fallback_applied, bool)
                and fallback_applied == (extraction_timestamp != planned_timestamp),
                f"来源链 {chain_id} 第{frame_index_number}帧回退标记不一致",
            )
            if fallback_applied:
                require(
                    extraction_timestamp < planned_timestamp
                    and -adjustment_ms in fallback_offsets_ms,
                    f"来源链 {chain_id} 第{frame_index_number}帧实际抽帧时间不符合回退策略",
                )

            attempts = frame.get("extractionAttempts")
            require(
                isinstance(attempts, list) and bool(attempts),
                f"来源链 {chain_id} 第{frame_index_number}帧缺少实际抽帧请求链",
            )
            normalized_attempts = []
            for attempt_index, attempt in enumerate(attempts, 1):
                require(
                    isinstance(attempt, dict),
                    f"来源链 {chain_id} 第{frame_index_number}帧第{attempt_index}次抽帧请求无效",
                )
                attempt_timestamp = attempt.get("requestedTimestampMs")
                result = attempt.get("result")
                require(
                    isinstance(attempt_timestamp, int)
                    and not isinstance(attempt_timestamp, bool)
                    and 0 <= attempt_timestamp < duration_ms,
                    f"来源链 {chain_id} 第{frame_index_number}帧抽帧请求时间无效",
                )
                require(
                    result in {"ffmpeg_failed", "no_frame_output", "frame_written"},
                    f"来源链 {chain_id} 第{frame_index_number}帧抽帧请求结果无效",
                )
                normalized_attempts.append(
                    {"requestedTimestampMs": attempt_timestamp, "result": result}
                )
            allowed_requests = [planned_timestamp]
            for offset_ms in fallback_offsets_ms:
                candidate_timestamp = max(0, planned_timestamp - offset_ms)
                if candidate_timestamp not in allowed_requests:
                    allowed_requests.append(candidate_timestamp)
            require(
                [row["requestedTimestampMs"] for row in normalized_attempts]
                == allowed_requests[: len(normalized_attempts)],
                f"来源链 {chain_id} 第{frame_index_number}帧抽帧请求链不符合回退策略",
            )
            require(
                normalized_attempts[-1]
                == {
                    "requestedTimestampMs": extraction_timestamp,
                    "result": "frame_written",
                }
                and all(row["result"] != "frame_written" for row in normalized_attempts[:-1]),
                f"来源链 {chain_id} 第{frame_index_number}帧实际成功请求与记录不一致",
            )
            frame_sha = validate_sha256(
                frame.get("frameSha256"), f"来源链 {chain_id} 第{frame_index_number}帧"
            )
            key = (requested_timestamp, frame_sha)
            require(key not in frame_index, f"来源链 {chain_id} 帧记录重复")
            frame_index[key] = {
                "timestampMs": requested_timestamp,
                "requestedTimestampMs": requested_timestamp,
                "plannedRequestedTimestampMs": planned_timestamp,
                "extractionRequestedTimestampMs": extraction_timestamp,
                "extractionTimestampAdjustmentMs": adjustment_ms,
                "tailFallbackApplied": fallback_applied,
                "extractionAttempts": normalized_attempts,
                "frameSha256": frame_sha,
            }
            _optional_rehash(
                workspace_root,
                frame.get("framePath"),
                frame_sha,
                f"来源链 {chain_id} 第{frame_index_number}帧",
            )

        binding = {
            "schemaVersion": SOURCE_CHAIN_BINDING_SCHEMA,
            "chainId": chain_id,
            "sourceId": source_id,
            "authorizationId": authorization_id,
            "videoId": video_id,
            "videoUrl": f"https://www.bilibili.com/video/{video_id}",
            "creator": creator,
            "creatorPlatformId": creator_platform_id,
            "manifestSha256": manifest_hashes,
            "sourceMediaSha256": media_sha,
            "audioSha256": audio_sha,
            "machineTranscriptSha256": machine_transcript_sha,
            "mediaDurationMs": duration_ms,
            "frames": [
                frame_index[key] for key in sorted(frame_index)
            ],
        }
        return binding

    def binding_for(
        self,
        chain_id: str,
        source_id: str,
        authorization_id: str,
        video_id: str,
    ) -> dict[str, Any]:
        require(chain_id in self._bindings, f"来源链缺少chainId：{chain_id}")
        binding_value = self._bindings[chain_id]
        require(
            not isinstance(binding_value, list),
            f"来源链存在多个已固定版本，请使用带bindingSha256的单元引用：{chain_id}",
        )
        binding = binding_value
        require(binding["sourceId"] == source_id, "来源链sourceId不一致")
        require(binding["authorizationId"] == authorization_id, "来源链authorizationId不一致")
        require(binding["videoId"] == video_id, "来源链videoId不一致")
        return copy.deepcopy(binding)

    def binding_for_unit(self, source_meta: dict[str, Any]) -> dict[str, Any]:
        reference = source_meta.get("sourceChain")
        require(isinstance(reference, dict), "来源链引用缺失")
        chain_id = str(reference.get("chainId") or "")
        require(chain_id in self._bindings, f"来源链缺少chainId：{chain_id}")
        binding_value = self._bindings[chain_id]
        candidates = binding_value if isinstance(binding_value, list) else [binding_value]
        expected_binding_hash = str(reference.get("bindingSha256") or "").lower()
        if len(candidates) == 1:
            binding = copy.deepcopy(candidates[0])
            require(binding["sourceId"] == source_meta.get("sourceId"), "来源链sourceId不一致")
            require(
                binding["authorizationId"] == source_meta.get("authorizationId"),
                "来源链authorizationId不一致",
            )
            require(binding["videoId"] == source_meta.get("videoId"), "来源链videoId不一致")
        else:
            matches = [
                binding
                for binding in candidates
                if binding["sourceId"] == str(source_meta.get("sourceId") or "")
                and binding["authorizationId"]
                == str(source_meta.get("authorizationId") or "")
                and binding["videoId"] == str(source_meta.get("videoId") or "")
                and canonical_json_sha256(binding) == expected_binding_hash
            ]
            require(
                len(matches) == 1,
                f"来源链bindingSha256不能唯一匹配已固定版本：{chain_id}",
            )
            binding = copy.deepcopy(matches[0])
        binding_hash = canonical_json_sha256(binding)
        require(
            str(reference.get("bindingSha256") or "").lower() == binding_hash,
            "来源链bindingSha256不一致",
        )
        start_ms = source_meta.get("startMs")
        end_ms = source_meta.get("endMs")
        require(
            isinstance(start_ms, int)
            and not isinstance(start_ms, bool)
            and isinstance(end_ms, int)
            and not isinstance(end_ms, bool)
            and 0 <= start_ms < end_ms,
            "来源片段时间无效",
        )
        require(end_ms <= binding["mediaDurationMs"], "来源片段超出已登记媒体时长")
        frame_timestamp = reference.get("frameTimestampMs")
        frame_sha = str(reference.get("frameSha256") or "").lower()
        require(
            isinstance(frame_timestamp, int) and not isinstance(frame_timestamp, bool),
            "来源链帧时间缺失",
        )
        require(start_ms <= frame_timestamp < end_ms, "来源链帧不在教学片段时间内")
        requested_timestamp = reference.get("frameRequestedTimestampMs")
        planned_timestamp = reference.get("framePlannedRequestedTimestampMs")
        extraction_timestamp = reference.get("frameExtractionRequestedTimestampMs")
        require(
            all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in (
                    requested_timestamp,
                    planned_timestamp,
                    extraction_timestamp,
                )
            ),
            "来源链帧缺少计划/请求/实际抽帧时间",
        )
        require(
            all(
                start_ms <= value < end_ms
                for value in (
                    requested_timestamp,
                    planned_timestamp,
                    extraction_timestamp,
                )
            ),
            "来源链计划/请求/实际抽帧时间不在教学片段内",
        )
        require(frame_timestamp == requested_timestamp, "来源链兼容帧时间与请求时间不一致")
        matching_frames = [
            frame
            for frame in binding["frames"]
            if frame["requestedTimestampMs"] == requested_timestamp
            and frame["plannedRequestedTimestampMs"] == planned_timestamp
            and frame["extractionRequestedTimestampMs"] == extraction_timestamp
            and frame["frameSha256"] == frame_sha
        ]
        require(
            len(matching_frames) == 1,
            "来源链帧未登记或frameSha256不一致",
        )
        return binding


def review_input_hashes(
    unit: dict[str, Any], source_chain_binding: dict[str, Any]
) -> dict[str, str]:
    """计算审批必须逐项固定的规范输入哈希；忽略内联 ``review``。"""
    source_binding_sha = canonical_json_sha256(source_chain_binding)
    source_reference = (unit.get("source") or {}).get("sourceChain") or {}
    require(
        source_reference.get("bindingSha256") == source_binding_sha,
        "审批输入的来源链bindingSha256不一致",
    )
    transcript_sha = validate_sha256(
        (unit.get("source") or {}).get("transcriptSha256"), "审批转写制品"
    )
    board = unit.get("board")
    evidence = unit.get("evidence")
    pedagogy = unit.get("pedagogy")
    require(isinstance(board, dict), "审批输入缺少board")
    require(isinstance(evidence, dict), "审批输入缺少evidence")
    require(isinstance(pedagogy, dict), "审批输入缺少pedagogy")
    unit_projection = {
        key: value
        for key, value in unit.items()
        if key != "review"
    }
    evidence_inputs = {
        "sourceChainBindingSha256": source_binding_sha,
        "evidence": evidence,
        "pedagogy": pedagogy,
    }
    return {
        "unitContentSha256": canonical_json_sha256(unit_projection),
        "transcriptArtifactSha256": transcript_sha,
        "boardArtifactSha256": canonical_json_sha256(board),
        "evidenceInputSha256": canonical_json_sha256(evidence_inputs),
        "sourceChainBindingSha256": source_binding_sha,
    }


def _parse_reviewed_at(value: Any, approval_id: str) -> str:
    text = str(value or "").strip()
    require(bool(text), f"审批 {approval_id} 缺少reviewedAt")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrustError(f"审批 {approval_id} reviewedAt不是ISO-8601") from exc
    require(parsed.tzinfo is not None, f"审批 {approval_id} reviewedAt必须包含时区")
    return text


class HumanReviewRegistry:
    """受信审核人 allowlist 与独立审批 JSONL。"""

    def __init__(
        self,
        reviewers: dict[str, dict[str, Any]],
        approvals: dict[str, dict[str, Any]],
        reviewer_registry_sha256: str,
        approvals_sha256: str,
    ) -> None:
        self._reviewers = reviewers
        self._approvals = approvals
        self.reviewer_registry_sha256 = reviewer_registry_sha256
        self.approvals_sha256 = approvals_sha256

    @classmethod
    def load(
        cls,
        reviewers_path: Path,
        approvals_path: Path,
        reviewers_sha256: str,
        approvals_sha256: str,
    ) -> "HumanReviewRegistry":
        reviewers_sha = validate_sha256(reviewers_sha256, "审核人allowlist固定值")
        reviewers_document = _read_pinned_json(
            Path(reviewers_path).resolve(), reviewers_sha, "审核人allowlist"
        )
        require(
            reviewers_document.get("schemaVersion") == REVIEWER_REGISTRY_SCHEMA,
            "审核人allowlist schema不受支持",
        )
        reviewer_rows = reviewers_document.get("reviewers")
        require(isinstance(reviewer_rows, list), "审核人allowlist reviewers必须是数组")
        reviewers: dict[str, dict[str, Any]] = {}
        for index, reviewer in enumerate(reviewer_rows, 1):
            require(isinstance(reviewer, dict), f"第{index}个审核人必须是对象")
            reviewer_id = str(reviewer.get("reviewerId") or "").strip()
            require(bool(STABLE_ID_RE.fullmatch(reviewer_id)), f"第{index}个reviewerId无效")
            require(reviewer_id not in reviewers, f"审核人ID重复：{reviewer_id}")
            scopes = reviewer.get("scopes")
            require(isinstance(scopes, list), f"审核人 {reviewer_id} scopes必须是数组")
            reviewers[reviewer_id] = {
                "reviewerId": reviewer_id,
                "status": reviewer.get("status"),
                "scopes": sorted({str(scope) for scope in scopes}),
            }

        approvals_path = Path(approvals_path).resolve()
        expected_approvals_sha = validate_sha256(
            approvals_sha256, "审批JSONL固定值"
        )
        approvals_payload = _read_pinned_bytes(
            approvals_path, expected_approvals_sha, "审批JSONL"
        )
        try:
            approvals_text = approvals_payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TrustError(f"无法读取审批JSONL：{approvals_path}: {exc}") from exc
        approvals: dict[str, dict[str, Any]] = {}
        seen_approval_ids: set[str] = set()
        for line_number, line in enumerate(approvals_text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                approval = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrustError(
                    f"审批JSONL第{line_number}行JSON错误：{exc}"
                ) from exc
            require(isinstance(approval, dict), f"审批JSONL第{line_number}行必须是对象")
            require(
                approval.get("schemaVersion") == REVIEW_APPROVAL_SCHEMA,
                f"审批JSONL第{line_number}行schema不受支持",
            )
            approval_id = str(approval.get("approvalId") or "").strip()
            unit_id = str(approval.get("unitId") or "").strip()
            require(bool(STABLE_ID_RE.fullmatch(approval_id)), f"审批第{line_number}行approvalId无效")
            require(bool(unit_id), f"审批 {approval_id} 缺少unitId")
            require(approval_id not in seen_approval_ids, f"审批ID重复：{approval_id}")
            require(unit_id not in approvals, f"同一unit存在重复审批：{unit_id}")
            seen_approval_ids.add(approval_id)
            _parse_reviewed_at(approval.get("reviewedAt"), approval_id)
            approvals[unit_id] = approval
        return cls(reviewers, approvals, reviewers_sha, expected_approvals_sha)

    def verify(
        self,
        unit: dict[str, Any],
        source_chain_binding: dict[str, Any],
    ) -> dict[str, Any]:
        unit_id = str(unit.get("id") or "").strip()
        require(unit_id in self._approvals, f"独立人工审批缺失：{unit_id}")
        approval = self._approvals[unit_id]
        approval_id = str(approval["approvalId"])
        require(approval.get("decision") == "approved", f"审批 {approval_id} 未批准")
        reviewer_id = str(approval.get("reviewerId") or "").strip()
        require(reviewer_id in self._reviewers, f"审核人不在allowlist：{reviewer_id}")
        reviewer = self._reviewers[reviewer_id]
        require(reviewer.get("status") == "active", f"审核人不是active：{reviewer_id}")
        reviewer_scopes = set(reviewer.get("scopes") or [])
        approval_scopes = set(approval.get("scopes") or [])
        require(
            REQUIRED_REVIEW_SCOPES <= reviewer_scopes,
            f"审核人 {reviewer_id} 缺少所需审核scope",
        )
        require(
            REQUIRED_REVIEW_SCOPES <= approval_scopes,
            f"审批 {approval_id} 未覆盖全部审核scope",
        )
        expected_hashes = review_input_hashes(unit, source_chain_binding)
        actual_hashes = approval.get("hashes")
        require(isinstance(actual_hashes, dict), f"审批 {approval_id} 缺少hashes")
        require(set(actual_hashes) == set(expected_hashes), f"审批 {approval_id} hashes字段不完整")
        for label, expected in expected_hashes.items():
            actual = validate_sha256(actual_hashes.get(label), f"审批 {approval_id} {label}")
            require(actual == expected, f"审批 {approval_id} {label}不一致")
        return {
            "approvalId": approval_id,
            "reviewerId": reviewer_id,
            "reviewedAt": _parse_reviewed_at(approval.get("reviewedAt"), approval_id),
            "hashes": expected_hashes,
            "reviewerRegistrySha256": self.reviewer_registry_sha256,
            "reviewApprovalsSha256": self.approvals_sha256,
        }
