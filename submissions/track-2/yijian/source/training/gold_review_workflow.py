# -*- coding: utf-8 -*-
"""Deterministic creator-gold selection, offline review, and trusted finalization.

The workflow deliberately keeps three states separate:

1. ``yijian-gold-selection-v1`` is a machine-generated shortlist.
2. ``human-gold-review-drafts-v1`` is an explicit reviewer export, but is not
   trusted on its own.
3. Finalized ``authorized-video-teaching-unit-v3`` rows are emitted only after
   the reviewer allowlist, source chain, KataGo registry, and every canonical
   approval hash have been verified together.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


TRAINING_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = TRAINING_ROOT.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import expert_corpus  # noqa: E402
import trusted_source_chain as source_trust  # noqa: E402
import trusted_katago_artifacts as katago_trust  # noqa: E402


SELECTION_SCHEMA = "yijian-gold-selection-v1"
REVIEW_PACK_SCHEMA = "yijian-gold-review-pack-v1"
REVIEW_DRAFT_SCHEMA = "human-gold-review-drafts-v1"
SIGNING_INTENT_SCHEMA = "human-gold-signing-intent-v1"
FRAME_RECOVERY_SCHEMA = "yijian-gold-frame-recovery-v1"
HASH_BUNDLE_SCHEMA = "yijian-gold-finalization-v1"
EVIDENCE_AUDIT_SCHEMA = "gold-evidence-audit-v1"
REVISION_MANIFEST_SCHEMA = "gold-revision-manifest-v1"
CORPUS_RELEASE_SCHEMA = "gold-corpus-release-v1"
REQUIRED_SCOPES = ("transcript", "board", "semantics", "source_chain")
SOURCE_ID = "bilibili-mingyue-tanqi-473325357"
AUTHORIZATION_ID = "auth-mingyue-tanqi-20260801"

GO_TERMS = (
    "实战", "黑棋", "白棋", "先手", "后手", "厚", "薄", "急所", "打入",
    "侵消", "联络", "切断", "弃子", "取舍", "外势", "实地", "劫", "劫材",
    "定式", "死活", "对杀", "气", "官子", "手筋", "提吃", "做活", "棋筋",
)
THEMES = {
    "opening_value": ("开局", "布局", "大场"),
    "vital_point": ("急所", "要点", "手筋"),
    "thickness": ("厚", "薄", "弱棋"),
    "sente": ("先手", "后手", "脱先"),
    "attack_target": ("攻击", "追杀", "攻防对象"),
    "sacrifice_tradeoff": ("弃子", "取舍", "转换"),
    "territory_influence": ("实地", "外势", "势力"),
    "ko": ("劫", "劫材"),
    "joseki": ("定式", "变化图"),
    "life_death": ("死活", "做活", "眼位"),
    "liberty_race": ("对杀", "气紧", "收气"),
    "endgame": ("官子", "目数", "收官"),
}


class WorkflowError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WorkflowError(message)


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
        raise WorkflowError(f"无法规范化JSON：{exc}") from exc


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取JSON {path}：{exc}") from exc
    require(isinstance(value, dict), f"{path} 顶层必须是对象")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise WorkflowError(f"无法读取JSONL {path}：{exc}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"{path}:{line_number} JSON错误：{exc}") from exc
        require(isinstance(row, dict), f"{path}:{line_number} 必须是对象")
        rows.append(row)
    return rows


def atomic_write_text(path: Path, value: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(canonical_json(row) + "\n" for row in rows))


def _safe_snapshot_relative(value: Any, label: str) -> Path:
    relative = Path(str(value or ""))
    require(
        bool(str(value or "").strip())
        and not relative.is_absolute()
        and ".." not in relative.parts,
        f"{label} contains an unsafe relative path",
    )
    return relative


def _copy_pinned_file(source: Path, destination: Path, expected_sha: str, label: str) -> None:
    require(source.is_file(), f"{label} is missing: {source}")
    require(file_hash(source) == str(expected_sha or "").lower(), f"{label} SHA-256 mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        require(destination.is_file(), f"{label} destination is not a file")
        require(file_hash(destination) == file_hash(source), f"{label} destination collision")
        return
    shutil.copyfile(source, destination)


def copy_source_registry_snapshot(source: Path, destination: Path) -> dict[str, str]:
    """Copy a source registry and every pinned child needed for offline audit."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    copied: dict[str, str] = {}

    def visit(current_source: Path, current_destination: Path) -> None:
        document = read_json(current_source)
        current_destination.parent.mkdir(parents=True, exist_ok=True)
        if current_destination.exists():
            require(
                current_destination.is_file()
                and file_hash(current_destination) == file_hash(current_source),
                f"source registry destination collision: {current_destination}",
            )
        else:
            shutil.copyfile(current_source, current_destination)
        copied[current_destination.relative_to(destination.parent).as_posix()] = file_hash(
            current_destination
        )
        if document.get("schemaVersion") == "trusted-source-chain-registry-bundle-v1":
            snapshots = document.get("snapshots")
            require(isinstance(snapshots, list) and snapshots, "source registry bundle is empty")
            for index, snapshot in enumerate(snapshots, 1):
                require(isinstance(snapshot, dict), f"source bundle snapshot {index} is invalid")
                relative = _safe_snapshot_relative(snapshot.get("path"), f"source bundle snapshot {index}")
                child_source = current_source.parent / relative
                expected = str(snapshot.get("sha256") or "").lower()
                require(
                    child_source.is_file() and file_hash(child_source) == expected,
                    f"source bundle snapshot {index} SHA-256 mismatch",
                )
                visit(child_source, current_destination.parent / relative)
            return
        require(
            document.get("schemaVersion") == "trusted-source-chain-registry-v1",
            "unsupported source registry schema",
        )
        entries = document.get("entries")
        require(isinstance(entries, list) and entries, "source registry entries are empty")
        for entry_index, entry in enumerate(entries, 1):
            require(isinstance(entry, dict), f"source registry entry {entry_index} is invalid")
            manifests = entry.get("manifests")
            require(isinstance(manifests, dict), f"source registry entry {entry_index} lacks manifests")
            for kind, meta in manifests.items():
                require(isinstance(meta, dict), f"source registry {kind} manifest is invalid")
                relative = _safe_snapshot_relative(meta.get("path"), f"source registry {kind} manifest")
                child_source = current_source.parent / relative
                child_destination = current_destination.parent / relative
                _copy_pinned_file(
                    child_source,
                    child_destination,
                    str(meta.get("sha256") or "").lower(),
                    f"source registry {kind} manifest",
                )
                copied[child_destination.relative_to(destination.parent).as_posix()] = file_hash(
                    child_destination
                )

    visit(source, destination)
    source_trust.SourceChainRegistry.load(destination, file_hash(destination))
    return dict(sorted(copied.items()))


def copy_katago_registry_snapshot(source: Path, destination: Path) -> dict[str, str]:
    """Copy a KataGo registry snapshot and pinned children, preserving layout."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    copied = {destination.name: file_hash(destination)}
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        document = None
    if isinstance(document, dict) and document.get("schemaVersion") == "gomentor-trusted-katago-registry-bundle-v1":
        snapshots = document.get("snapshots")
        require(isinstance(snapshots, list) and snapshots, "KataGo registry bundle is empty")
        for index, snapshot in enumerate(snapshots, 1):
            require(isinstance(snapshot, dict), f"KataGo bundle snapshot {index} is invalid")
            relative = _safe_snapshot_relative(snapshot.get("path"), f"KataGo bundle snapshot {index}")
            child_source = source.parent / relative
            child_destination = destination.parent / relative
            _copy_pinned_file(
                child_source,
                child_destination,
                str(snapshot.get("sha256") or "").lower(),
                f"KataGo bundle snapshot {index}",
            )
            copied[child_destination.relative_to(destination.parent).as_posix()] = file_hash(
                child_destination
            )
    katago_trust.load_registry_snapshot(destination, expected_sha256=file_hash(destination))
    return dict(sorted(copied.items()))


def _records(document: dict[str, Any], label: str) -> list[dict[str, Any]]:
    rows = document.get("records")
    require(isinstance(rows, list), f"{label} records必须是数组")
    return [row for row in rows if isinstance(row, dict)]


def _windows(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine ASR fragments into reviewable 20–90 second teaching windows."""
    valid = []
    for segment in segments:
        start = segment.get("startMs")
        end = segment.get("endMs")
        text = str(segment.get("text") or "").strip()
        if (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and 0 <= start < end
            and text
        ):
            valid.append({"startMs": start, "endMs": end, "text": text})
    valid.sort(key=lambda row: (row["startMs"], row["endMs"]))
    windows = []
    index = 0
    while index < len(valid):
        chosen = []
        chars = 0
        start = valid[index]["startMs"]
        cursor = index
        while cursor < len(valid) and len(chosen) < 18:
            row = valid[cursor]
            if chosen and row["startMs"] - chosen[-1]["endMs"] > 4000:
                break
            if row["endMs"] - start > 90000:
                break
            chosen.append(row)
            chars += len(row["text"])
            cursor += 1
            if chars >= 180 and row["endMs"] - start >= 18000:
                break
        if chosen:
            text = "".join(row["text"] for row in chosen)
            windows.append({
                "startMs": chosen[0]["startMs"],
                "endMs": chosen[-1]["endMs"],
                "text": text,
                "segments": chosen,
            })
        index = max(index + 1, cursor)
    return windows


def _theme(text: str) -> str:
    scored = [
        (sum(term in text for term in terms), name)
        for name, terms in THEMES.items()
    ]
    score, name = max(scored, key=lambda item: (item[0], item[1]))
    return name if score else "vital_point"


def _target_kind(text: str) -> str:
    if "比较" in text or ("实战" in text and any(term in text for term in ("首选", "AI", "推荐"))):
        return "comparison"
    if any(term in text for term in ("首选", "最佳", "推荐手", "正解")):
        return "best"
    return "actual"


def _score(text: str, duration_ms: int) -> int:
    term_score = sum(min(3, text.count(term)) for term in GO_TERMS)
    question_score = 5 if any(term in text for term in ("为什么", "应该", "问题", "正解")) else 0
    concrete_score = 4 if any(term in text for term in ("实战", "下一手", "这手棋", "此手")) else 0
    duration_score = 3 if 20000 <= duration_ms <= 75000 else 0
    return term_score + question_score + concrete_score + duration_score


def _frame_for_window(frames: list[dict[str, Any]], start: int, end: int) -> dict[str, Any] | None:
    inside = [
        frame for frame in frames
        if isinstance(frame.get("requestedTimestampMs"), int)
        and start <= frame["requestedTimestampMs"] < end
        and len(str(frame.get("frameSha256") or "")) == 64
    ]
    if not inside:
        return None
    midpoint = (start + end) // 2
    return min(
        inside,
        key=lambda frame: (
            abs(frame["requestedTimestampMs"] - midpoint),
            frame["requestedTimestampMs"],
        ),
    )


def build_selection(
    transcripts_path: Path,
    frames_path: Path,
    *,
    limit: int = 8,
    per_video: int = 4,
) -> dict[str, Any]:
    require(limit > 0, "limit必须大于0")
    require(per_video > 0, "per-video必须大于0")
    transcripts = read_json(transcripts_path)
    frames = read_json(frames_path)
    transcript_rows = {str(row.get("videoId") or ""): row for row in _records(transcripts, "转写")}
    frame_rows = {str(row.get("videoId") or ""): row for row in _records(frames, "帧证据")}
    common = sorted(set(transcript_rows) & set(frame_rows))
    require(common, "转写与帧证据没有共同videoId")

    candidates: dict[str, list[dict[str, Any]]] = {}
    rejected: list[dict[str, Any]] = []
    for video_id in common:
        transcript = transcript_rows[video_id]
        frame_record = frame_rows[video_id]
        video_candidates = []
        for window_index, window in enumerate(_windows(transcript.get("segments") or [])):
            text = window["text"]
            score = _score(text, window["endMs"] - window["startMs"])
            frame = _frame_for_window(
                frame_record.get("frames") or [], window["startMs"], window["endMs"]
            )
            reasons = []
            if score < 10:
                reasons.append("棋理密度不足")
            if frame is None:
                reasons.append("时间段内没有受登记帧")
            if any(term in text for term in ("感谢大家关注", "点赞", "订阅", "转发", "打赏", "一键三连")):
                reasons.append("片段包含片尾或互动内容")
            candidate_id = f"gold-pilot-{video_id.lower()}-{window['startMs']:012d}"
            if reasons:
                rejected.append({
                    "candidateId": candidate_id,
                    "videoId": video_id,
                    "startMs": window["startMs"],
                    "endMs": window["endMs"],
                    "reasons": reasons,
                })
                continue
            video_candidates.append({
                "candidateId": candidate_id,
                "videoId": video_id,
                "videoUrl": f"https://www.bilibili.com/video/{video_id}",
                "startMs": window["startMs"],
                "endMs": window["endMs"],
                "transcript": text,
                "transcriptSegments": window["segments"],
                "transcriptWindowSha256": canonical_hash(window["segments"]),
                "frame": {
                    key: frame.get(key)
                    for key in (
                        "frameId", "framePath", "requestedTimestampMs",
                        "plannedRequestedTimestampMs", "extractionRequestedTimestampMs",
                        "frameSha256", "extractionAttempts", "tailFallbackApplied",
                    )
                },
                "theme": _theme(text),
                "targetKind": _target_kind(text),
                "score": score,
                "selectionReason": "棋理密度、具体着手线索与已登记证据帧同时满足",
                "evidenceReadiness": {
                    "frameRegistered": True,
                    "boardHumanVerified": False,
                    "ruleArtifactVerified": False,
                    "katagoArtifactVerified": False,
                    "teacherAnswerVerified": False,
                },
                "status": "machine_candidate",
                "trainingEligible": False,
            })
        candidates[video_id] = sorted(
            video_candidates,
            key=lambda row: (-row["score"], row["startMs"], row["candidateId"]),
        )

    selected: list[dict[str, Any]] = []
    counts = {video_id: 0 for video_id in common}
    last_times: dict[str, list[int]] = {video_id: [] for video_id in common}
    while len(selected) < limit:
        progressed = False
        for video_id in common:
            if counts[video_id] >= per_video:
                continue
            remaining = candidates[video_id]
            picked_index = next((
                index for index, row in enumerate(remaining)
                if all(abs(row["startMs"] - prior) >= 45000 for prior in last_times[video_id])
            ), None)
            if picked_index is None:
                continue
            row = remaining.pop(picked_index)
            selected.append(row)
            counts[video_id] += 1
            last_times[video_id].append(row["startMs"])
            progressed = True
            if len(selected) == limit:
                break
        if not progressed:
            break
    require(len(selected) == limit, f"只能选出{len(selected)}个合格候选，目标为{limit}")
    return {
        "schemaVersion": SELECTION_SCHEMA,
        "status": "machine_candidate",
        "trainingEligible": False,
        "requiresHumanReview": True,
        "sourceId": SOURCE_ID,
        "authorizationId": AUTHORIZATION_ID,
        "policy": {
            "requested": limit,
            "maxPerVideo": per_video,
            "minimumGapMsWithinVideo": 45000,
            "selectionOrder": "round-robin-by-video-then-score",
        },
        "inputs": {
            "transcripts": {"path": str(transcripts_path), "sha256": file_hash(transcripts_path)},
            "frames": {"path": str(frames_path), "sha256": file_hash(frames_path)},
        },
        "selectedCount": len(selected),
        "selected": selected,
        "rejectedCount": len(rejected),
        "rejected": rejected,
    }


def build_source_registry(
    *,
    catalog: Path,
    downloads: Path,
    audio: Path,
    transcripts: Path,
    frames: Path,
    output: Path,
) -> dict[str, Any]:
    manifests = {
        "catalog": catalog.resolve(),
        "downloads": downloads.resolve(),
        "audio": audio.resolve(),
        "transcripts": transcripts.resolve(),
        "frames": frames.resolve(),
    }
    documents = {name: read_json(path) for name, path in manifests.items()}
    video_sets = []
    for name, document in documents.items():
        ids = {str(row.get("videoId") or "") for row in _records(document, name)}
        video_sets.append(ids)
    video_ids = sorted(set.intersection(*video_sets))
    require(video_ids, "五类manifest没有共同视频")
    output_root = output.resolve().parent
    entries = []
    for video_id in video_ids:
        entries.append({
            "chainId": f"creator:{video_id}:pilot-v1",
            "sourceId": SOURCE_ID,
            "authorizationId": AUTHORIZATION_ID,
            "videoId": video_id,
            "workspaceRoot": ".",
            "manifests": {
                name: {
                    "path": os.path.relpath(path, output_root).replace("\\", "/"),
                    "sha256": file_hash(path),
                }
                for name, path in manifests.items()
            },
        })
    document = {"schemaVersion": "trusted-source-chain-registry-v1", "entries": entries}
    write_json(output, document)
    registry_sha = file_hash(output)
    # Loading performs the complete catalog→frame consistency audit.
    source_trust.SourceChainRegistry.load(output, registry_sha)
    return {"registry": str(output), "sha256": registry_sha, "videos": video_ids}


def rebind_frame_manifest(
    *,
    original_frames: Path,
    downloads: Path,
    audio: Path,
    transcripts: Path,
    output: Path,
) -> dict[str, Any]:
    """Re-pin changed manifest bytes only after semantic lineage still matches.

    The original frame document is never modified.  Every video must still bind
    to exactly the same media, audio, and canonical transcript hashes declared
    when its frames were extracted.
    """
    frame_document = read_json(original_frames)
    downloads_document = read_json(downloads)
    audio_document = read_json(audio)
    transcripts_document = read_json(transcripts)
    indexed = {
        "downloads": {str(row.get("videoId") or ""): row for row in _records(downloads_document, "downloads")},
        "audio": {str(row.get("videoId") or ""): row for row in _records(audio_document, "audio")},
        "transcripts": {str(row.get("videoId") or ""): row for row in _records(transcripts_document, "transcripts")},
    }
    for frame_row in _records(frame_document, "frames"):
        video_id = str(frame_row.get("videoId") or "")
        require(all(video_id in records for records in indexed.values()), f"{video_id}: 新输入缺少对应记录")
        download_row = indexed["downloads"][video_id]
        audio_row = indexed["audio"][video_id]
        transcript_row = indexed["transcripts"][video_id]
        audio_sha = str(audio_row.get("sha256") or "").lower()
        media_sha = str(audio_row.get("sourceMediaSha256") or "").lower()
        transcript_sha = str(transcript_row.get("transcriptSha256") or "").lower()
        require(len({len(audio_sha), len(media_sha), len(transcript_sha)}) == 1 and len(audio_sha) == 64, f"{video_id}: 新输入缺少固定SHA-256")
        media_matches = [
            item for item in download_row.get("files") or []
            if isinstance(item, dict) and str(item.get("sha256") or "").lower() == media_sha
        ]
        require(len(media_matches) == 1, f"{video_id}: 下载媒体与音频父SHA不能唯一匹配")
        require(str(transcript_row.get("audioSha256") or "").lower() == audio_sha, f"{video_id}: 转写音频SHA变化")
        require(str((frame_row.get("video") or {}).get("sha256") or "").lower() == media_sha, f"{video_id}: 帧视频SHA变化")
        require(str((frame_row.get("audio") or {}).get("sha256") or "").lower() == audio_sha, f"{video_id}: 帧音频SHA变化")
        require(str((frame_row.get("audio") or {}).get("sourceMediaSha256") or "").lower() == media_sha, f"{video_id}: 帧音频父SHA变化")
        require(str(frame_row.get("transcriptSha256") or "").lower() == transcript_sha, f"{video_id}: 帧转写SHA变化")
    rebound = copy.deepcopy(frame_document)
    old_inputs = copy.deepcopy(rebound.get("inputs") or {})
    new_paths = {"downloads": downloads, "audio": audio, "transcripts": transcripts}
    rebound["inputs"] = {
        name: {"fileName": path.name, "sha256": file_hash(path)}
        for name, path in new_paths.items()
    }
    rebound["lineageRebind"] = {
        "schemaVersion": "licensed-video-frame-lineage-rebind-v1",
        "reason": "manifest bytes changed; media/audio/transcript semantic hashes reverified",
        "originalFrameManifestSha256": file_hash(original_frames),
        "previousInputs": old_inputs,
        "newInputs": copy.deepcopy(rebound["inputs"]),
    }
    write_json(output, rebound)
    return {
        "output": str(output),
        "sha256": file_hash(output),
        "videos": len(_records(rebound, "frames")),
        "lineageRebound": True,
    }


def _review_projection(unit: dict[str, Any]) -> dict[str, Any]:
    """Project a review-ready draft into the exact bytes the reviewer signs.

    ``review_ready`` is deliberately not training eligible.  The only place it
    becomes ``human_verified`` is this deterministic projection, and finalize
    will only persist the projection when the independent browser draft pins
    its canonical content hash and all four scopes are approved.
    """
    projection = copy.deepcopy(unit)
    projection["trainingEligible"] = True
    projection.pop("review", None)
    transcript = projection.get("transcript") or {}
    if transcript.get("status") == "review_ready":
        transcript["status"] = "human_verified"
    for segment in transcript.get("segments") or []:
        if isinstance(segment, dict) and segment.get("status") == "review_ready":
            segment["status"] = "human_verified"
    board = projection.get("board") or {}
    if board.get("status") == "review_ready":
        board["status"] = "human_verified"
    if board.get("moveSequenceStatus") == "review_ready":
        board["moveSequenceStatus"] = "human_verified"
    frame = board.get("frameEvidence") or {}
    if frame.get("status") == "review_ready":
        frame["status"] = "human_verified"
    return projection


def _ready_for_review(
    unit: dict[str, Any] | None,
    source_registry: source_trust.SourceChainRegistry | None = None,
    katago_registry: Any | None = None,
) -> bool:
    if not isinstance(unit, dict):
        return False
    statuses = list(expert_corpus._status_values(unit))  # trusted compiler semantics
    if any("machine" in value.lower() or "candidate" in value.lower() for value in statuses):
        return False
    source = unit.get("source") or {}
    katago = ((unit.get("evidence") or {}).get("katagoFacts") or {})
    board = unit.get("board") or {}
    frame = board.get("frameEvidence") or {}
    structurally_ready = (
        unit.get("schemaVersion") == "authorized-video-teaching-unit-v3"
        and unit.get("trainingEligible") is False
        and (unit.get("transcript") or {}).get("status") == "review_ready"
        and all(
            isinstance(segment, dict) and segment.get("status") == "review_ready"
            for segment in (unit.get("transcript") or {}).get("segments") or []
        )
        and board.get("status") == "review_ready"
        and board.get("moveSequenceStatus") == "review_ready"
        and frame.get("status") == "review_ready"
        and isinstance(source.get("sourceChain"), dict)
        and isinstance(katago.get("trustedArtifactRef"), dict)
    )
    if not structurally_ready or source_registry is None or katago_registry is None:
        return False
    try:
        projection = _review_projection(unit)
        expert_corpus.verified_transcript_artifact(projection)
        rebuilt = expert_corpus.reconstruct_board_facts(projection)
        katago_facts = expert_corpus.verified_katago_facts(
            projection, rebuilt, katago_registry
        )
        expert_corpus.verified_rule_facts(projection, rebuilt)
        expert_corpus.validate_gold_answer(projection, rebuilt, katago_facts)
        binding = source_registry.binding_for_unit(projection["source"])
        if binding.get("creator") != projection["source"].get("creator"):
            return False
    except (KeyError, TypeError, ValueError, expert_corpus.CorpusError):
        return False
    return True


def _selected_candidates(selection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = selection.get("selected")
    require(isinstance(rows, list) and rows, "候选清单缺少selected")
    selected: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, 1):
        require(isinstance(row, dict), f"候选清单第{index}条不是对象")
        candidate_id = str(row.get("candidateId") or "").strip()
        require(candidate_id, f"候选清单第{index}条缺少candidateId")
        require(candidate_id not in selected, f"候选清单重复candidateId：{candidate_id}")
        selected[candidate_id] = row
    return selected


def _validate_selection_unit_binding(
    unit: dict[str, Any], candidate: dict[str, Any], unit_id: str,
) -> None:
    """Bind the signed unit to the immutable shortlist fields when present."""
    source = unit.get("source") or {}
    board = unit.get("board") or {}
    frame = board.get("frameEvidence") or {}
    checks = (
        ("videoId", source.get("videoId"), candidate.get("videoId")),
        ("startMs", source.get("startMs"), candidate.get("startMs")),
        ("endMs", source.get("endMs"), candidate.get("endMs")),
        ("targetKind", board.get("targetKind"), candidate.get("targetKind")),
    )
    for name, actual, expected in checks:
        if expected is not None:
            require(actual == expected, f"{unit_id}: 与候选清单{name}不一致")
    candidate_frame = candidate.get("frame") or {}
    expected_frame_sha = candidate_frame.get("frameSha256")
    if expected_frame_sha:
        require(
            frame.get("frameSha256") == expected_frame_sha,
            f"{unit_id}: 与候选清单证据帧SHA-256不一致",
        )


def build_evidence_audit(
    *,
    selection_path: Path,
    units_path: Path,
    source_registry: source_trust.SourceChainRegistry,
    katago_registry: Any,
) -> dict[str, Any]:
    """Create a non-authorizing, hash-bound pre-review evidence audit."""
    selection = read_json(selection_path)
    require(selection.get("schemaVersion") == SELECTION_SCHEMA, "候选清单schema错误")
    selected = _selected_candidates(selection)
    units = read_jsonl(units_path)
    by_id = {str(unit.get("id") or ""): unit for unit in units}
    require(len(by_id) == len(units), "待审单元ID重复")
    rows: list[dict[str, Any]] = []
    for unit_id, candidate in selected.items():
        unit = by_id.get(unit_id)
        checks = {
            "selectionBinding": False,
            "transcript": False,
            "boardAndRules": False,
            "katago": False,
            "teacherAnswer": False,
            "sourceChain": False,
        }
        errors: list[str] = []
        if not isinstance(unit, dict):
            errors.append("缺少对应待审单元")
        else:
            projection = _review_projection(unit)
            try:
                _validate_selection_unit_binding(unit, candidate, unit_id)
                checks["selectionBinding"] = True
            except WorkflowError as exc:
                errors.append(str(exc))
            rebuilt: dict[str, Any] | None = None
            katago_facts: dict[str, Any] | None = None
            try:
                expert_corpus.verified_transcript_artifact(projection)
                checks["transcript"] = True
            except (KeyError, TypeError, ValueError, expert_corpus.CorpusError) as exc:
                errors.append(f"转写：{exc}")
            try:
                rebuilt = expert_corpus.reconstruct_board_facts(projection)
                expert_corpus.verified_rule_facts(projection, rebuilt)
                checks["boardAndRules"] = True
            except (KeyError, TypeError, ValueError, expert_corpus.CorpusError) as exc:
                errors.append(f"棋盘/规则：{exc}")
            if rebuilt is not None:
                try:
                    katago_facts = expert_corpus.verified_katago_facts(
                        projection, rebuilt, katago_registry
                    )
                    checks["katago"] = True
                except (KeyError, TypeError, ValueError, expert_corpus.CorpusError) as exc:
                    errors.append(f"KataGo：{exc}")
            if rebuilt is not None and katago_facts is not None:
                try:
                    expert_corpus.validate_gold_answer(projection, rebuilt, katago_facts)
                    checks["teacherAnswer"] = True
                except (KeyError, TypeError, ValueError, expert_corpus.CorpusError) as exc:
                    errors.append(f"教师回答：{exc}")
            try:
                binding = source_registry.binding_for_unit(projection["source"])
                require(
                    binding.get("creator") == projection["source"].get("creator"),
                    f"{unit_id}: 来源链creator不一致",
                )
                checks["sourceChain"] = True
            except (KeyError, TypeError, ValueError, WorkflowError, source_trust.TrustError) as exc:
                errors.append(f"来源链：{exc}")
        passed = all(checks.values()) and _ready_for_review(
            unit, source_registry, katago_registry
        )
        rows.append({
            "unitId": unit_id,
            "status": "ready_for_human_review" if passed else "blocked",
            "trainingEligible": False,
            "checks": checks,
            "errors": errors,
            "candidateSha256": canonical_hash(candidate),
            "reviewProjectionSha256": (
                canonical_hash(_review_projection(unit)) if isinstance(unit, dict) else None
            ),
        })
    return {
        "schemaVersion": EVIDENCE_AUDIT_SCHEMA,
        "status": "pre_review_only",
        "trainingEligible": False,
        "selectionSha256": file_hash(selection_path),
        "unitsSha256": file_hash(units_path),
        "recordCount": len(rows),
        "readyCount": sum(row["status"] == "ready_for_human_review" for row in rows),
        "passed": all(row["status"] == "ready_for_human_review" for row in rows),
        "records": rows,
    }


def build_review_payload(
    selection_path: Path,
    units_path: Path | None,
    reviewer_id: str,
    source_registry: source_trust.SourceChainRegistry | None = None,
    katago_registry: Any | None = None,
) -> dict[str, Any]:
    selection = read_json(selection_path)
    require(selection.get("schemaVersion") == SELECTION_SCHEMA, "候选清单schema错误")
    units = read_jsonl(units_path) if units_path else []
    by_id = {str(unit.get("id") or ""): unit for unit in units}
    rows = []
    for candidate in selection.get("selected") or []:
        candidate = copy.deepcopy(candidate)
        frame = candidate.get("frame") if isinstance(candidate.get("frame"), dict) else {}
        frame_path_value = str(frame.get("framePath") or "")
        if frame_path_value:
            relative = Path(frame_path_value)
            frame["localAvailable"] = (
                not relative.is_absolute()
                and ".." not in relative.parts
                and (selection_path.resolve().parent / relative).is_file()
            )
        candidate_id = str(candidate.get("candidateId") or "")
        unit = by_id.get(candidate_id)
        ready = _ready_for_review(unit, source_registry, katago_registry)
        projection = _review_projection(unit) if ready else None
        rows.append({
            "candidate": candidate,
            "unit": unit,
            "readyForReview": ready,
            "unitContentSha256": canonical_hash(projection) if projection else None,
            "blockingReasons": [] if ready else [
                "需要补齐待审转写与棋盘、规则制品、受信KataGo引用、教师回答或registry校验"
            ],
        })
    return {
        "schemaVersion": REVIEW_PACK_SCHEMA,
        "status": "review_draft_only",
        "trainingEligible": False,
        "selectionSha256": file_hash(selection_path),
        "reviewerId": reviewer_id,
        "requiredScopes": list(REQUIRED_SCOPES),
        "recordCount": len(rows),
        "readyCount": sum(row["readyForReview"] for row in rows),
        "records": rows,
    }


def render_review_html(payload: dict[str, Any], title: str) -> str:
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title><style>
:root{{--paper:#f5f0e6;--card:#fffaf1;--ink:#1f2c29;--muted:#66736e;--jade:#285f54;--red:#a33d2d;--line:#d8cdbb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif}}
header{{position:sticky;top:0;z-index:3;padding:16px 22px;background:#f5f0e6f2;border-bottom:1px solid var(--line)}}h1{{margin:0;font-size:23px}}
main{{display:grid;grid-template-columns:300px 1fr;min-height:90vh}}aside{{padding:12px;border-right:1px solid var(--line)}}button,select,textarea,input{{font:inherit}}
.item{{display:block;width:100%;text-align:left;padding:10px;margin:7px 0;border:1px solid var(--line);border-radius:10px;background:var(--card)}}.item.active{{border-color:var(--jade)}}
article{{padding:22px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px}}
pre{{white-space:pre-wrap;word-break:break-word;max-height:360px;overflow:auto}}.pill{{display:inline-block;padding:3px 8px;border:1px solid var(--line);border-radius:999px;margin:3px}}
.bad{{color:var(--red)}}.good{{color:var(--jade)}}textarea{{width:100%;min-height:80px}}.actions{{display:grid;gap:9px}}.download{{background:var(--jade);color:white;border:0;border-radius:8px;padding:9px 13px}}.frame-preview{{max-width:100%;max-height:440px;border:1px solid var(--line);border-radius:10px}}.frame-missing{{color:var(--red)}}
@media(max-width:850px){{main{{display:block}}aside{{border-right:0;border-bottom:1px solid var(--line)}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>{safe_title}</h1><div id="summary"></div></header><main><aside><div id="list"></div><button class="download" id="export">导出审核草稿</button></aside><article id="detail"></article></main>
<script id="payload" type="application/json">{data}</script><script>
const pack=JSON.parse(document.getElementById('payload').textContent);const key='yijian-gold-review-'+pack.selectionSha256;let drafts=JSON.parse(localStorage.getItem(key)||'{{}}');let active=pack.records[0]?.candidate.candidateId||'';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
function row(){{return pack.records.find(r=>r.candidate.candidateId===active)}}
function renderList(){{document.getElementById('list').innerHTML=pack.records.map(r=>`<button class="item ${{r.candidate.candidateId===active?'active':''}}" data-id="${{esc(r.candidate.candidateId)}}"><b>${{esc(r.candidate.videoId)}}</b><br>${{Math.floor(r.candidate.startMs/1000)}}s · ${{esc(r.candidate.theme)}} · <span class="${{r.readyForReview?'good':'bad'}}">${{r.readyForReview?'证据齐全':'待补证据'}}</span></button>`).join('');document.querySelectorAll('.item').forEach(b=>b.onclick=()=>{{active=b.dataset.id;renderList();renderDetail()}})}}
function renderDetail(){{const r=row(),c=r.candidate,u=r.unit||{{}},d=drafts[c.candidateId]||{{decision:'needs_changes',scopes:[],notes:''}};const frame=c.frame||{{}},frameSrc=frame.reviewPath||frame.framePath;document.getElementById('detail').innerHTML=`<h2>${{esc(c.candidateId)}}</h2><p><a href="${{esc(c.videoUrl)}}?t=${{Math.floor(c.startMs/1000)}}" target="_blank">打开原视频时间段</a> <span class="pill">${{esc(c.targetKind)}}</span><span class="pill">${{esc(c.theme)}}</span></p>${{frame.framePath?`<p>证据帧：${{esc(frame.framePath)}} · SHA ${{esc(frame.frameSha256)}}</p><div>${{frame.localAvailable?`<img class="frame-preview" src="${{esc(frameSrc)}}" alt="证据帧">`:`<span class="frame-missing">证据帧文件当前不在本机工作区；审核前必须恢复与该 SHA 匹配的文件。</span>`}}</div>`:''}}<div class="grid"><section><h3>核验转写</h3><pre>${{esc(c.transcript)}}</pre></section><section><h3>棋盘与问题目标</h3><pre>${{esc(JSON.stringify(u.board||{{}},null,2))}}</pre></section><section><h3>KataGo 与规则证据</h3><pre>${{esc(JSON.stringify(u.evidence||{{}},null,2))}}</pre></section><section><h3>教学回答</h3><pre>${{esc(JSON.stringify((u.evidence||{{}}).teacherExpression||{{}},null,2))}}</pre></section></div><section class="actions"><b class="${{r.readyForReview?'good':'bad'}}">${{r.readyForReview?'可以进入人工审核':'禁止批准：'+r.blockingReasons.join('；')}}</b><select id="decision"><option value="approve" ${{r.readyForReview?'':'disabled'}}>批准</option><option value="needs_changes">需要修改</option><option value="reject">拒绝</option></select><div>${{pack.requiredScopes.map(s=>`<label><input type="checkbox" class="scope" value="${{esc(s)}}"> ${{esc(s)}}</label>`).join(' · ')}}</div><textarea id="notes" placeholder="记录核验依据或退回原因"></textarea><button class="download" id="save">保存本条草稿</button><small>待批准内容 SHA-256：${{esc(r.unitContentSha256||'尚未生成')}}</small></section>`;document.getElementById('decision').value=r.readyForReview?d.decision:'needs_changes';document.getElementById('notes').value=d.notes||'';document.querySelectorAll('.scope').forEach(x=>x.checked=(d.scopes||[]).includes(x.value));document.getElementById('save').onclick=()=>{{const decision=document.getElementById('decision').value;const scopes=[...document.querySelectorAll('.scope:checked')].map(x=>x.value).sort();if(decision==='approve'&&(!r.readyForReview||scopes.length!==pack.requiredScopes.length)){{alert('批准前必须证据齐全并确认全部四项审核范围。');return}}drafts[c.candidateId]={{unitId:c.candidateId,reviewerId:pack.reviewerId,decision,scopes,notes:document.getElementById('notes').value,reviewedAt:new Date().toISOString(),unitContentSha256:r.unitContentSha256,selectionSha256:pack.selectionSha256}};localStorage.setItem(key,JSON.stringify(drafts));renderList()}}}}
document.getElementById('export').onclick=()=>{{const value={{schemaVersion:'{REVIEW_DRAFT_SCHEMA}',status:'review_draft_only',trainingEligible:false,selectionSha256:pack.selectionSha256,reviewerId:pack.reviewerId,records:Object.values(drafts)}};const blob=new Blob([JSON.stringify(value,null,2)],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='yijian-gold-review-drafts.json';a.click();URL.revokeObjectURL(a.href)}};
document.getElementById('summary').textContent=`候选 ${{pack.recordCount}} · 可审核 ${{pack.readyCount}} · 草稿不能直接训练`;renderList();renderDetail();
</script></body></html>"""


def render_guided_review_html(payload: dict[str, Any], title: str) -> str:
    """Layer a reviewer-friendly view over the immutable review payload.

    The original raw evidence remains in a collapsed section.  This keeps the
    audit surface inspectable while making the ordinary path a four-question
    human review instead of a JSON-reading exercise.
    """
    base = render_review_html(payload, title)
    guided = r"""
<style>
.review-guide{padding:12px 14px;background:#e5f0ea;border:1px solid #bfd3c9;border-radius:11px;margin-bottom:14px}.review-guide b{color:#285f54}
.facts{display:grid;grid-template-columns:repeat(4,minmax(110px,1fr));gap:8px;margin:12px 0}.fact{padding:10px;background:#f1eadc;border-radius:9px}.fact strong{display:block;color:#285f54;font-size:21px}
.guided-answer{font-size:17px;line-height:1.8}.guided-question{font-weight:700;font-size:18px}.scope-card{display:block;padding:10px;border:1px solid #d8cdbb;border-radius:9px;margin:7px 0}.scope-card input{transform:scale(1.25);margin-right:8px}.quick{padding:9px 13px;border:1px solid #b9d0c5;border-radius:8px;background:#e0ece6;color:#285f54}canvas{display:block;width:min(100%,500px);height:auto;margin:auto;background:#d9ad66;border-radius:8px}table{border-collapse:collapse;width:100%}th,td{padding:7px;border-bottom:1px solid #d8cdbb;text-align:left}details{margin-top:9px}code{font-size:12px;word-break:break-all}.frame-preview{max-height:520px}.item small{color:#66736e}
@media(max-width:850px){.facts{grid-template-columns:1fr 1fr}}
</style>
<script>
const targetLabel=s=>({actual:'核对实战手',best:'核对 AI 首选',comparison:'比较实战与首选',position:'分析当前局面'}[s]||s);
const colorLabel=s=>s==='B'?'黑棋':'白棋';
const scopeLabel=s=>({transcript:'① 转写与原视频一致',board:'② 棋盘、行棋方和落子正确',semantics:'③ 教学解释忠实且没有夸大',source_chain:'④ 视频、帧和引擎来源链可信'}[s]||s);
const percent=n=>Number.isFinite(Number(n))?(Number(n)*100).toFixed(1)+'%':'—';
const points=n=>Number.isFinite(Number(n))?(Number(n)>=0?'+':'')+Number(n).toFixed(1)+'目':'—';
function guidedSummary(){const values=Object.values(drafts),approved=values.filter(x=>x.decision==='approve').length;document.getElementById('summary').textContent=`证据齐全 ${pack.readyCount} / ${pack.recordCount} · 已保存 ${values.length} · 已批准 ${approved} · 草稿不能直接训练`}
function drawReviewBoard(u){const canvas=document.getElementById('review-board');if(!canvas)return;const ctx=canvas.getContext('2d'),size=19,pad=42,gap=(canvas.width-pad*2)/(size-1),letters='ABCDEFGHJKLMNOPQRST';ctx.fillStyle='#d9ad66';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#302718';ctx.font='bold 15px system-ui, "Microsoft YaHei", sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';for(let i=0;i<size;i++){const x=pad+i*gap,y=pad+i*gap,row=String(size-i);ctx.fillText(letters[i],x,17);ctx.fillText(letters[i],x,canvas.height-17);ctx.fillText(row,17,y);ctx.fillText(row,canvas.width-17,y)}ctx.strokeStyle='#463721';ctx.lineWidth=1;for(let i=0;i<size;i++){ctx.beginPath();ctx.moveTo(pad,pad+i*gap);ctx.lineTo(pad+(size-1)*gap,pad+i*gap);ctx.stroke();ctx.beginPath();ctx.moveTo(pad+i*gap,pad);ctx.lineTo(pad+i*gap,pad+(size-1)*gap);ctx.stroke()}for(const x of [3,9,15])for(const y of [3,9,15]){ctx.beginPath();ctx.arc(pad+x*gap,pad+y*gap,3,0,Math.PI*2);ctx.fillStyle='#463721';ctx.fill()}const moves=u.board?.moves||[],limit=u.board?.actualMoveNumber||moves.length;moves.slice(0,limit).forEach((m,i)=>{if(!m.coord||m.coord.length!==2)return;const x=m.coord.charCodeAt(0)-97,y=m.coord.charCodeAt(1)-97;ctx.beginPath();ctx.arc(pad+x*gap,pad+y*gap,gap*.43,0,Math.PI*2);ctx.fillStyle=m.color==='B'?'#111':'#f7f4ed';ctx.fill();ctx.strokeStyle='#222';ctx.stroke();if(i===limit-1){ctx.beginPath();ctx.arc(pad+x*gap,pad+y*gap,gap*.18,0,Math.PI*2);ctx.strokeStyle='#d33';ctx.lineWidth=3;ctx.stroke();ctx.lineWidth=1}})}
renderList=function(){document.getElementById('list').innerHTML=pack.records.map((r,i)=>{const d=drafts[r.candidate.candidateId],state=d?.decision==='approve'?'已批准':d?.decision==='reject'?'已拒绝':d?'待修改':r.readyForReview?'待你审核':'待补证据';return `<button class="item ${r.candidate.candidateId===active?'active':''}" data-id="${esc(r.candidate.candidateId)}"><b>${i+1}. ${esc(r.candidate.videoId)}</b><br><small>${Math.floor(r.candidate.startMs/1000)} 秒 · ${esc(targetLabel(r.candidate.targetKind))}</small><br><span class="${d?.decision==='approve'?'good':r.readyForReview?'':'bad'}">${esc(state)}</span></button>`}).join('');document.querySelectorAll('.item').forEach(b=>b.onclick=()=>{active=b.dataset.id;renderList();renderDetail()});guidedSummary()};
renderDetail=function(){const r=row(),c=r.candidate,u=r.unit||{},d=drafts[c.candidateId]||{decision:'needs_changes',scopes:[],notes:''},frame=c.frame||{},frameSrc=frame.reviewPath||frame.framePath,b=u.board||{},e=u.evidence||{},k=e.katagoFacts||{},artifact=k.analysisArtifact||{},expr=e.teacherExpression||{},rule=(e.ruleFacts||{}).ruleArtifact||{},candidates=artifact.candidates||[];document.getElementById('detail').innerHTML=`<div class="review-guide"><b>你只需要核对四件事：</b>画面与转写是否对应；棋盘与实战手是否正确；教学解释是否忠实；来源与引擎证据是否可信。四项都正确即可批准。</div><h2>${esc(targetLabel(c.targetKind))}</h2><p><a href="${esc(c.videoUrl)}?t=${Math.floor(c.startMs/1000)}" target="_blank">▶ 打开原视频第 ${Math.floor(c.startMs/1000)} 秒</a><span class="pill">${esc(c.theme)}</span><span class="pill">KataGo ${esc(k.visits)} visits</span></p><div class="facts"><div class="fact">行棋方<strong>${esc(colorLabel(b.subjectColor))}</strong></div><div class="fact">实战手<strong>${esc(b.actualMove)}</strong></div><div class="fact">AI 首选<strong>${esc(b.bestMove)}</strong></div><div class="fact">规则重放<strong>${rule.legal?'合法':'异常'}</strong></div></div><div class="grid"><section><h3>① 视频证据帧</h3>${frame.localAvailable?`<img class="frame-preview" src="${esc(frameSrc)}" alt="证据帧">`:'<span class="frame-missing">证据帧缺失，不能批准。</span>'}<p><small>时间：${(Number(frame.requestedTimestampMs)/1000).toFixed(1)} 秒</small></p></section><section><h3>② 重建棋盘（红圈为实战手）</h3><canvas id="review-board" width="560" height="560"></canvas><p>请核对：棋子位置，以及${esc(colorLabel(b.subjectColor))}是否落在 <b>${esc(b.actualMove)}</b>。</p><p><small>坐标规则：上下为 A–T（跳过 I），左右为 19–1；左下角是 A1。</small></p></section></div><section><h3>③ 讲解原意与教学回答</h3><p><b>核验转写：</b>${esc(c.transcript)}</p><p class="guided-question">问题：${esc(expr.question)}</p><p class="guided-answer">${esc(expr.answer)}</p><p><b>证据边界：</b>${esc((u.pedagogy||{}).boundary)}</p></section><section><h3>④ KataGo 比较（数值来自登记制品）</h3><table><thead><tr><th>候选手</th><th>本方胜率</th><th>本方目差</th><th>访问</th><th>主变化</th></tr></thead><tbody>${candidates.map(x=>`<tr><td><b>${esc(x.move)}</b>${x.move===b.bestMove?'（首选）':''}${x.move===b.actualMove?'（实战）':''}</td><td>${esc(percent(x.winrate))}</td><td>${esc(points(x.scoreLead))}</td><td>${esc(x.visits)}</td><td>${esc((x.pv||[]).join(' → '))}</td></tr>`).join('')}</tbody></table><details><summary>展开来源哈希与原始证据（一般无需阅读）</summary><p>证据帧 SHA：<code>${esc(frame.frameSha256)}</code></p><p>待批准内容 SHA：<code>${esc(r.unitContentSha256)}</code></p><pre>${esc(JSON.stringify({source:u.source,ruleFacts:e.ruleFacts,katagoRef:k.trustedArtifactRef},null,2))}</pre></details></section><section class="actions"><b class="${r.readyForReview?'good':'bad'}">${r.readyForReview?'证据齐全，可以由你审核签发':'禁止批准：'+r.blockingReasons.join('；')}</b><button class="quick" id="confirm-all" ${r.readyForReview?'':'disabled'}>四项都正确：一键确认四项</button><div>${pack.requiredScopes.map(s=>`<label class="scope-card"><input type="checkbox" class="scope" value="${esc(s)}"> ${esc(scopeLabel(s))}</label>`).join('')}</div><label><b>审核结论：</b> <select id="decision"><option value="approve" ${r.readyForReview?'':'disabled'}>批准</option><option value="needs_changes">需要修改</option><option value="reject">拒绝</option></select></label><textarea id="notes" placeholder="可选：写下核对依据；如果退回，请说明哪里不对"></textarea><button class="download" id="save">保存本条审核</button><small>保存后审核左侧下一条；全部完成后点左侧“导出审核草稿”。</small></section>`;drawReviewBoard(u);document.getElementById('decision').value=r.readyForReview?d.decision:'needs_changes';document.getElementById('notes').value=d.notes||'';document.querySelectorAll('.scope').forEach(x=>x.checked=(d.scopes||[]).includes(x.value));document.getElementById('confirm-all').onclick=()=>{document.querySelectorAll('.scope').forEach(x=>x.checked=true);document.getElementById('decision').value='approve'};document.getElementById('save').onclick=()=>{const decision=document.getElementById('decision').value,scopes=[...document.querySelectorAll('.scope:checked')].map(x=>x.value).sort();if(decision==='approve'&&(!r.readyForReview||scopes.length!==pack.requiredScopes.length)){alert('批准前必须确认全部四项。');return}drafts[c.candidateId]={unitId:c.candidateId,reviewerId:pack.reviewerId,decision,scopes,notes:document.getElementById('notes').value,reviewedAt:new Date().toISOString(),unitContentSha256:r.unitContentSha256,selectionSha256:pack.selectionSha256};localStorage.setItem(key,JSON.stringify(drafts));renderList();renderDetail()}};
renderList();renderDetail();guidedSummary();
</script>
"""
    return base.replace("</body>", guided + "</body>")


def _load_reviewer(
    path: Path, expected_sha: str, reviewer_id: str
) -> dict[str, Any]:
    require(file_hash(path) == expected_sha.lower(), "审核人registry SHA-256不一致")
    document = read_json(path)
    require(document.get("schemaVersion") == "human-reviewer-registry-v1", "审核人registry schema错误")
    rows = [row for row in document.get("reviewers") or [] if isinstance(row, dict)]
    matches = [row for row in rows if row.get("reviewerId") == reviewer_id]
    require(len(matches) == 1, f"审核人未登记或重复：{reviewer_id}")
    reviewer = matches[0]
    require(reviewer.get("status") == "active", f"审核人未启用：{reviewer_id}")
    require(set(REQUIRED_SCOPES) <= set(reviewer.get("scopes") or []), "审核人缺少金标签发范围")
    return reviewer


def record_signing_intent(
    *,
    selection_path: Path,
    reviewer_registry_path: Path,
    reviewer_registry_sha: str,
    authorization_path: Path,
    output_path: Path,
    reviewer_id: str,
    statement: str,
    model_display_name: str = "弈鉴 LoRA",
) -> dict[str, Any]:
    """Record human intent without promoting incomplete candidates to gold.

    The actual approval remains content-hash bound and can only be created by
    ``finalize`` after board, rule, KataGo, teacher-answer and source evidence
    are all present.  This artifact is therefore auditable but never training
    eligible on its own.
    """
    selection_path = selection_path.resolve()
    reviewer_registry_path = reviewer_registry_path.resolve()
    authorization_path = authorization_path.resolve()
    output_path = output_path.resolve()
    selection = read_json(selection_path)
    require(selection.get("schemaVersion") == SELECTION_SCHEMA, "候选清单schema错误")
    selected = selection.get("selected")
    require(isinstance(selected, list) and len(selected) == 8, "签发试批必须恰好包含8条候选")
    require(selection.get("trainingEligible") is False, "候选清单不得已具备训练资格")
    require(selection.get("sourceId") == SOURCE_ID, "候选来源ID错误")
    require(selection.get("authorizationId") == AUTHORIZATION_ID, "候选授权ID错误")
    _load_reviewer(reviewer_registry_path, reviewer_registry_sha, reviewer_id)

    authorization = read_json(authorization_path)
    grant = authorization.get("grant") or {}
    uses = set(grant.get("uses") or [])
    require(authorization.get("schemaVersion") == "creator-authorization-v1", "创作者授权schema错误")
    require(authorization.get("authorizationId") == AUTHORIZATION_ID, "创作者授权ID错误")
    require(authorization.get("sourceId") == SOURCE_ID, "创作者授权来源ID错误")
    require(grant.get("status") == "granted", "创作者授权未生效")
    require({"ai_model_training", "lora_finetuning", "competition_demo"} <= uses, "授权用途不足")
    statement = statement.strip()
    require(bool(statement), "必须保留用户明确签发声明")

    records = []
    for candidate in selected:
        require(isinstance(candidate, dict), "候选记录必须是对象")
        candidate_id = str(candidate.get("candidateId") or "")
        require(bool(candidate_id), "候选缺少candidateId")
        records.append({
            "candidateId": candidate_id,
            "videoId": candidate.get("videoId"),
            "decision": "approve_after_evidence_verification",
            "requestedScopes": list(REQUIRED_SCOPES),
            "effectiveApproval": False,
            "unitContentSha256": None,
            "trainingEligible": False,
        })
    value = {
        "schemaVersion": SIGNING_INTENT_SCHEMA,
        "status": "preapproved_pending_evidence",
        "trainingEligible": False,
        "effectiveApprovalCount": 0,
        "reviewerId": reviewer_id,
        "recordedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "statement": statement,
        "model": {
            "displayName": model_display_name,
            "apiAlias": "yijian-lora",
            "baseModel": "Qwen/Qwen3-14B",
            "method": "BF16 LoRA",
        },
        "authorizationConfirmation": {
            "authorizationId": AUTHORIZATION_ID,
            "sourceId": SOURCE_ID,
            "status": "granted",
            "authorizationSha256": file_hash(authorization_path),
            "evidenceSha256": (authorization.get("evidence") or {}).get("sha256"),
            "usesConfirmed": sorted({"ai_model_training", "lora_finetuning", "competition_demo"}),
        },
        "selection": {
            "schemaVersion": SELECTION_SCHEMA,
            "sha256": file_hash(selection_path),
            "selectedCount": len(records),
        },
        "reviewerRegistrySha256": reviewer_registry_sha.lower(),
        "records": records,
        "activationRequirements": [
            "八条单元均补齐棋盘人工校对、goboard规则重放、KataGo 128 visits和教师回答",
            "审核页展示最终内容及全部来源哈希",
            "审核人对最终内容逐条确认四项审核范围",
            "finalize命令验证内容哈希和全部上游制品",
        ],
    }
    require(not output_path.exists(), f"拒绝覆盖已有签发意图：{output_path}")
    write_json(output_path, value)
    return value


def recover_selected_frames(
    *,
    selection_path: Path,
    downloads_path: Path,
    media_workspace: Path,
    ffmpeg_path: Path,
    output_manifest: Path,
    output_selection: Path,
) -> dict[str, Any]:
    """Re-extract selected evidence frames from a newly verified media copy."""
    selection_path = selection_path.resolve()
    downloads_path = downloads_path.resolve()
    media_workspace = media_workspace.resolve()
    ffmpeg_path = ffmpeg_path.resolve()
    output_manifest = output_manifest.resolve()
    output_selection = output_selection.resolve()
    require(ffmpeg_path.is_file(), f"FFmpeg不存在：{ffmpeg_path}")
    require(output_manifest.parent == output_selection.parent, "恢复清单与新候选清单必须位于同一目录")
    require(not output_manifest.exists(), f"拒绝覆盖恢复清单：{output_manifest}")
    require(not output_selection.exists(), f"拒绝覆盖候选清单：{output_selection}")
    selection = read_json(selection_path)
    require(selection.get("schemaVersion") == SELECTION_SCHEMA, "候选清单schema错误")
    selected = selection.get("selected")
    require(isinstance(selected, list) and len(selected) == 8, "恢复帧必须对应恰好8条候选")
    downloads = read_json(downloads_path)
    require(downloads.get("schemaVersion") == "licensed-video-downloads-v1", "下载清单schema错误")
    require(downloads.get("sourceId") == SOURCE_ID, "恢复媒体来源ID错误")
    require(downloads.get("authorizationId") == AUTHORIZATION_ID, "恢复媒体授权ID错误")
    download_rows = {
        str(row.get("videoId") or ""): row
        for row in downloads.get("records") or []
        if isinstance(row, dict)
    }
    version = subprocess.run(
        [str(ffmpeg_path), "-version"], check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout.splitlines()[0]
    evidence_name = "evidence-gold-pilot-restored-v1"
    evidence_root = output_manifest.parent / evidence_name
    require(not evidence_root.exists(), f"拒绝覆盖已恢复证据目录：{evidence_root}")
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    replacement_frames: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="gold-frame-recovery-", dir=output_manifest.parent) as temporary_name:
        temporary = Path(temporary_name)
        temporary_evidence = temporary / evidence_name
        for candidate in selected:
            require(isinstance(candidate, dict), "候选记录必须是对象")
            candidate_id = str(candidate.get("candidateId") or "")
            video_id = str(candidate.get("videoId") or "")
            frame = candidate.get("frame") or {}
            timestamp = frame.get("requestedTimestampMs")
            require(video_id in download_rows, f"恢复下载清单缺少视频：{video_id}")
            require(isinstance(timestamp, int) and not isinstance(timestamp, bool) and timestamp >= 0,
                    f"{candidate_id}: 帧时间戳无效")
            files = download_rows[video_id].get("files") or []
            require(len(files) == 1 and isinstance(files[0], dict), f"{video_id}: 媒体文件必须唯一")
            media = (media_workspace / str(files[0].get("path") or "")).resolve()
            require(media_workspace == media or media_workspace in media.parents, f"{video_id}: 媒体路径逃逸")
            require(media.is_file(), f"{video_id}: 媒体文件不存在")
            media_sha = file_hash(media)
            require(media_sha == str(files[0].get("sha256") or "").lower(), f"{video_id}: 媒体SHA不一致")
            relative = Path(evidence_name) / video_id / f"frame-{timestamp:012d}.png"
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            command = [
                str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-ss",
                f"{timestamp / 1000:.3f}", "-i", str(media), "-frames:v", "1",
                "-an", "-sn", str(destination),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            require(completed.returncode == 0 and destination.is_file() and destination.stat().st_size > 0,
                    f"{candidate_id}: FFmpeg抽帧失败：{completed.stderr.strip()}")
            recovered = {
                "frameId": f"{video_id}:{timestamp:012d}:restored-v1",
                "framePath": relative.as_posix(),
                "requestedTimestampMs": timestamp,
                "plannedRequestedTimestampMs": timestamp,
                "extractionRequestedTimestampMs": timestamp,
                "frameSha256": file_hash(destination),
                "sourceMediaSha256": media_sha,
                "extractionAttempts": [{"requestedTimestampMs": timestamp, "result": "frame_written"}],
                "tailFallbackApplied": False,
                "recoveredFromNewMediaManifest": True,
            }
            replacement_frames[candidate_id] = recovered
            manifest_rows.append({
                "candidateId": candidate_id,
                "videoId": video_id,
                "sourceMedia": {
                    "path": str(files[0].get("path") or ""),
                    "bytes": media.stat().st_size,
                    "sha256": media_sha,
                },
                "previousFrameSha256": frame.get("frameSha256"),
                "frame": recovered,
            })
        os.replace(temporary_evidence, evidence_root)
    manifest = {
        "schemaVersion": FRAME_RECOVERY_SCHEMA,
        "status": "frame_evidence_only",
        "trainingEligible": False,
        "sourceId": SOURCE_ID,
        "authorizationId": AUTHORIZATION_ID,
        "selectionSha256": file_hash(selection_path),
        "downloadsSha256": file_hash(downloads_path),
        "extractor": {"name": "ffmpeg", "version": version},
        "recordCount": len(manifest_rows),
        "records": manifest_rows,
    }
    write_json(output_manifest, manifest)
    rebound = copy.deepcopy(selection)
    for candidate in rebound["selected"]:
        candidate["frame"] = replacement_frames[str(candidate["candidateId"])]
    rebound["inputs"]["frames"] = {
        "path": str(output_manifest),
        "sha256": file_hash(output_manifest),
        "schemaVersion": FRAME_RECOVERY_SCHEMA,
    }
    rebound["frameRecovery"] = {
        "previousSelectionSha256": file_hash(selection_path),
        "downloadsSha256": file_hash(downloads_path),
        "frameManifestSha256": file_hash(output_manifest),
        "semanticClaim": "same public video IDs and exact selected timestamps; new media and frame hashes",
    }
    write_json(output_selection, rebound)
    return {
        "frames": len(manifest_rows),
        "manifestSha256": file_hash(output_manifest),
        "selectionSha256": file_hash(output_selection),
        "evidenceRoot": str(evidence_root),
    }


def finalize_reviews(
    *,
    selection_path: Path,
    units_path: Path,
    drafts_path: Path,
    source_registry_path: Path,
    source_registry_sha: str,
    reviewer_registry_path: Path,
    reviewer_registry_sha: str,
    katago_registry_path: Path,
    katago_registry_sha: str,
    output_dir: Path,
) -> dict[str, Any]:
    selection = read_json(selection_path)
    require(selection.get("schemaVersion") == SELECTION_SCHEMA, "候选清单schema错误")
    selection_sha = file_hash(selection_path)
    selected = _selected_candidates(selection)
    units = read_jsonl(units_path)
    require(units, "没有待定稿单元")
    require(len({str(unit.get("id") or "") for unit in units}) == len(units), "unit id重复")
    require(all(unit.get("trainingEligible") is False for unit in units), "待审核单元必须保持trainingEligible=false")
    drafts_document = read_json(drafts_path)
    require(drafts_document.get("schemaVersion") == REVIEW_DRAFT_SCHEMA, "审核草稿schema错误")
    require(drafts_document.get("status") == "review_draft_only", "审核草稿状态错误")
    require(
        drafts_document.get("selectionSha256") == selection_sha,
        "审核草稿顶层selectionSha256与候选清单不一致",
    )
    reviewer_id = str(drafts_document.get("reviewerId") or "")
    _load_reviewer(reviewer_registry_path, reviewer_registry_sha, reviewer_id)
    drafts = {
        str(row.get("unitId") or ""): row
        for row in drafts_document.get("records") or []
        if isinstance(row, dict)
    }
    source_registry = source_trust.SourceChainRegistry.load(
        source_registry_path, source_registry_sha
    )
    katago_registry = katago_trust.load_registry_snapshot(
        katago_registry_path, expected_sha256=katago_registry_sha
    )

    finalized = []
    approvals = []
    for unit in units:
        unit_id = str(unit.get("id") or "")
        require(unit_id in selected, f"{unit_id}: 不属于指定候选清单")
        _validate_selection_unit_binding(unit, selected[unit_id], unit_id)
        require(unit_id in drafts, f"缺少审核草稿：{unit_id}")
        draft = drafts[unit_id]
        require(draft.get("reviewerId") == reviewer_id, f"{unit_id}: reviewerId不一致")
        require(
            draft.get("selectionSha256") == selection_sha,
            f"{unit_id}: 审核记录selectionSha256与候选清单不一致",
        )
        require(draft.get("decision") == "approve", f"{unit_id}: 尚未明确批准")
        require(set(draft.get("scopes") or []) == set(REQUIRED_SCOPES), f"{unit_id}: 四项审核范围未全部确认")
        candidate = _review_projection(unit)
        require(
            _ready_for_review(unit, source_registry, katago_registry),
            f"{unit_id}: 待审内容不完整、仍含机器候选状态或缺少受信引用",
        )
        content_sha = canonical_hash(candidate)
        require(draft.get("unitContentSha256") == content_sha, f"{unit_id}: 审核后内容已变化")
        binding = source_registry.binding_for_unit(candidate["source"])
        input_hashes = source_trust.review_input_hashes(candidate, binding)
        approval = {
            "schemaVersion": "human-review-approval-v1",
            "approvalId": f"approval-{unit_id}-{content_sha[:12]}",
            "unitId": unit_id,
            "reviewerId": reviewer_id,
            "reviewedAt": draft.get("reviewedAt"),
            "decision": "approved",
            "scopes": list(REQUIRED_SCOPES),
            "selectionSha256": selection_sha,
            "unitContentSha256": content_sha,
            "hashes": input_hashes,
        }
        finalized.append(candidate)
        approvals.append(approval)

    output_dir = output_dir.resolve()
    if output_dir.exists():
        require(not any(output_dir.iterdir()), f"输出目录非空，拒绝覆盖：{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yijian-gold-", dir=output_dir.parent) as temporary_name:
        temporary = Path(temporary_name)
        units_out = temporary / "teaching-units-v3.jsonl"
        approvals_out = temporary / "review-approvals.jsonl"
        reviewer_out = temporary / "reviewer-registry.json"
        source_out = temporary / "source-chain-registry.json"
        katago_out = temporary / "katago-registry.jsonl"
        selection_out = temporary / "selection.json"
        write_jsonl(units_out, finalized)
        write_jsonl(approvals_out, approvals)
        shutil.copyfile(reviewer_registry_path, reviewer_out)
        source_dependencies = copy_source_registry_snapshot(source_registry_path, source_out)
        katago_dependencies = copy_katago_registry_snapshot(katago_registry_path, katago_out)
        shutil.copyfile(selection_path, selection_out)
        reviewer_sha = file_hash(reviewer_out)
        approvals_sha = file_hash(approvals_out)
        review_registry = source_trust.HumanReviewRegistry.load(
            reviewer_out, approvals_out, reviewer_sha, approvals_sha
        )
        # Full compiler validation is the final fail-closed boundary.
        for unit in finalized:
            expert_corpus.validate_unit(
                unit,
                expert_corpus.load_sources(),
                source_chain=source_registry,
                review_registry=review_registry,
                katago_registry=katago_registry,
            )
        bundle = {
            "schemaVersion": HASH_BUNDLE_SCHEMA,
            "passed": True,
            "units": len(finalized),
            "reviewerId": reviewer_id,
            "artifacts": {
                path.name: file_hash(path)
                for path in (
                    units_out, approvals_out, reviewer_out, source_out, katago_out,
                    selection_out,
                )
            },
            "registryDependencies": {
                "source": source_dependencies,
                "katago": katago_dependencies,
            },
        }
        write_json(temporary / "hash-bundle.json", bundle)
        os.replace(temporary, output_dir)
    return bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    select = subparsers.add_parser("select", help="生成确定性的8单元机器候选清单")
    select.add_argument("--transcripts", type=Path, required=True)
    select.add_argument("--frames", type=Path, required=True)
    select.add_argument("--output", type=Path, required=True)
    select.add_argument("--limit", type=int, default=8)
    select.add_argument("--per-video", type=int, default=4)

    registry = subparsers.add_parser("source-registry", help="固定五类来源manifest")
    for name in ("catalog", "downloads", "audio", "transcripts", "frames", "output"):
        registry.add_argument(f"--{name}", type=Path, required=True)

    rebind = subparsers.add_parser("rebind-frames", help="语义哈希一致时另存并重绑帧输入manifest")
    rebind.add_argument("--original-frames", type=Path, required=True)
    rebind.add_argument("--downloads", type=Path, required=True)
    rebind.add_argument("--audio", type=Path, required=True)
    rebind.add_argument("--transcripts", type=Path, required=True)
    rebind.add_argument("--output", type=Path, required=True)

    review = subparsers.add_parser("review-pack", help="生成离线金标审核页")
    review.add_argument("--selection", type=Path, required=True)
    review.add_argument("--units", type=Path)
    review.add_argument("--source-registry", type=Path)
    review.add_argument("--source-registry-sha256")
    review.add_argument("--katago-registry", type=Path)
    review.add_argument("--katago-registry-sha256")
    review.add_argument("--reviewer-id", default="reviewer-alimoqi-go-v1")
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--title", default="弈鉴 · v3 金标证据审核")

    intent = subparsers.add_parser("record-intent", help="登记8条人工签发意图，不提前授予训练资格")
    intent.add_argument("--selection", type=Path, required=True)
    intent.add_argument("--reviewer-registry", type=Path, required=True)
    intent.add_argument("--reviewer-registry-sha256", required=True)
    intent.add_argument("--authorization", type=Path, required=True)
    intent.add_argument("--reviewer-id", default="reviewer-alimoqi-go-v1")
    intent.add_argument("--statement", required=True)
    intent.add_argument("--model-display-name", default="弈鉴 LoRA")
    intent.add_argument("--output", type=Path, required=True)

    recover = subparsers.add_parser("recover-frames", help="从重新验证的授权媒体恢复8张精确证据帧")
    recover.add_argument("--selection", type=Path, required=True)
    recover.add_argument("--downloads", type=Path, required=True)
    recover.add_argument("--media-workspace", type=Path, required=True)
    recover.add_argument("--ffmpeg", type=Path, required=True)
    recover.add_argument("--output-manifest", type=Path, required=True)
    recover.add_argument("--output-selection", type=Path, required=True)

    audit = subparsers.add_parser("evidence-audit", help="生成不可签发的证据预审清单")
    audit.add_argument("--selection", type=Path, required=True)
    audit.add_argument("--units", type=Path, required=True)
    audit.add_argument("--source-registry", type=Path, required=True)
    audit.add_argument("--source-registry-sha256", required=True)
    audit.add_argument("--katago-registry", type=Path, required=True)
    audit.add_argument("--katago-registry-sha256", required=True)
    audit.add_argument("--output", type=Path, required=True)

    finalize = subparsers.add_parser("finalize", help="把显式批准绑定为可信金标")
    finalize.add_argument("--selection", type=Path, required=True)
    finalize.add_argument("--units", type=Path, required=True)
    finalize.add_argument("--drafts", type=Path, required=True)
    finalize.add_argument("--source-registry", type=Path, required=True)
    finalize.add_argument("--source-registry-sha256", required=True)
    finalize.add_argument("--reviewer-registry", type=Path, required=True)
    finalize.add_argument("--reviewer-registry-sha256", required=True)
    finalize.add_argument("--katago-registry", type=Path, required=True)
    finalize.add_argument("--katago-registry-sha256", required=True)
    finalize.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "select":
            value = build_selection(
                args.transcripts.resolve(), args.frames.resolve(),
                limit=args.limit, per_video=args.per_video,
            )
            write_json(args.output.resolve(), value)
            print(json.dumps({"selected": value["selectedCount"], "output": str(args.output)}, ensure_ascii=False))
        elif args.command == "source-registry":
            value = build_source_registry(
                catalog=args.catalog,
                downloads=args.downloads,
                audio=args.audio,
                transcripts=args.transcripts,
                frames=args.frames,
                output=args.output,
            )
            print(json.dumps(value, ensure_ascii=False))
        elif args.command == "rebind-frames":
            value = rebind_frame_manifest(
                original_frames=args.original_frames.resolve(),
                downloads=args.downloads.resolve(),
                audio=args.audio.resolve(),
                transcripts=args.transcripts.resolve(),
                output=args.output.resolve(),
            )
            print(json.dumps(value, ensure_ascii=False))
        elif args.command == "review-pack":
            source_registry = None
            katago_registry = None
            if args.units:
                require(
                    all((args.source_registry, args.source_registry_sha256,
                         args.katago_registry, args.katago_registry_sha256)),
                    "有待审单元时必须同时提供来源链和KataGo registry及其SHA-256",
                )
                source_registry = source_trust.SourceChainRegistry.load(
                    args.source_registry.resolve(), args.source_registry_sha256
                )
                katago_registry = katago_trust.load_registry_snapshot(
                    args.katago_registry.resolve(),
                    expected_sha256=args.katago_registry_sha256,
                )
            payload = build_review_payload(
                args.selection.resolve(), args.units, args.reviewer_id,
                source_registry, katago_registry,
            )
            atomic_write_text(args.output.resolve(), render_guided_review_html(payload, args.title))
            print(json.dumps({"records": payload["recordCount"], "ready": payload["readyCount"]}, ensure_ascii=False))
        elif args.command == "record-intent":
            value = record_signing_intent(
                selection_path=args.selection,
                reviewer_registry_path=args.reviewer_registry,
                reviewer_registry_sha=args.reviewer_registry_sha256,
                authorization_path=args.authorization,
                output_path=args.output,
                reviewer_id=args.reviewer_id,
                statement=args.statement,
                model_display_name=args.model_display_name,
            )
            print(json.dumps({
                "status": value["status"],
                "selected": value["selection"]["selectedCount"],
                "effectiveApprovals": value["effectiveApprovalCount"],
                "output": str(args.output),
            }, ensure_ascii=False))
        elif args.command == "recover-frames":
            value = recover_selected_frames(
                selection_path=args.selection,
                downloads_path=args.downloads,
                media_workspace=args.media_workspace,
                ffmpeg_path=args.ffmpeg,
                output_manifest=args.output_manifest,
                output_selection=args.output_selection,
            )
            print(json.dumps(value, ensure_ascii=False, indent=2))
        elif args.command == "evidence-audit":
            source_registry = source_trust.SourceChainRegistry.load(
                args.source_registry.resolve(), args.source_registry_sha256
            )
            katago_registry = katago_trust.load_registry_snapshot(
                args.katago_registry.resolve(),
                expected_sha256=args.katago_registry_sha256,
            )
            value = build_evidence_audit(
                selection_path=args.selection.resolve(),
                units_path=args.units.resolve(),
                source_registry=source_registry,
                katago_registry=katago_registry,
            )
            write_json(args.output.resolve(), value)
            print(json.dumps({
                "records": value["recordCount"], "ready": value["readyCount"],
                "passed": value["passed"], "output": str(args.output),
            }, ensure_ascii=False))
        else:
            value = finalize_reviews(
                selection_path=args.selection.resolve(),
                units_path=args.units.resolve(), drafts_path=args.drafts.resolve(),
                source_registry_path=args.source_registry.resolve(),
                source_registry_sha=args.source_registry_sha256,
                reviewer_registry_path=args.reviewer_registry.resolve(),
                reviewer_registry_sha=args.reviewer_registry_sha256,
                katago_registry_path=args.katago_registry.resolve(),
                katago_registry_sha=args.katago_registry_sha256,
                output_dir=args.output_dir,
            )
            print(json.dumps(value, ensure_ascii=False, indent=2))
    except (WorkflowError, source_trust.TrustError, katago_trust.RegistryError, expert_corpus.CorpusError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
