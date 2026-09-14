from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import unquote, urlparse
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from glass_gateway.evaluation.retrieval_production import (
    NoAnswerPolicy,
    RetrievedEpisode,
    VisualEpisodeIndex,
    embed_query,
    fuse_embedding_and_reranker,
    rerank_candidates,
    rerank_visual_candidates,
)


PostJSON = Callable[[str, dict[str, object]], dict[str, object]]
_IMAGE_QUERY_TYPES = frozenset({"image", "image_text"})
_LEXICAL_STOP_TERMS = frozenset(
    {
        "什么",
        "哪里",
        "哪天",
        "时候",
        "后来",
        "发生",
        "怎么",
        "是否",
        "记得",
        "我的",
        "我在",
        "了什么",
    }
)


def _lexical_terms(value: object) -> set[str]:
    text = str(value or "").casefold()
    terms = {
        item
        for item in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text)
        if item not in _LEXICAL_STOP_TERMS
    }
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        for size in (2, 3, 4):
            terms.update(
                run[index : index + size]
                for index in range(max(0, len(run) - size + 1))
            )
    return {
        item
        for item in terms
        if item not in _LEXICAL_STOP_TERMS
    }


def _has_lexical_support(query: str, content: str) -> bool:
    focused_query = re.sub(
        r"(发生了什么|发生什么|后来怎么样|后来|什么时候|哪一天|哪天|"
        r"在哪里|哪里|怎么|为什么|是否|有没有|记不记得|记得|"
        r"我|你|他|她|它|的|了|吗|呢|啊|呀|？|\?)",
        "",
        query,
    )
    shared = _lexical_terms(focused_query) & _lexical_terms(content)
    return any(len(item) >= 3 for item in shared) or any(
        len(item) == 2 and item not in _LEXICAL_STOP_TERMS
        for item in shared
    )


def _envelope_results(envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = envelope.get("data")
    if not isinstance(data, Mapping):
        return []
    direct = data.get("results", data.get("items"))
    if isinstance(direct, list):
        return [dict(item) for item in direct if isinstance(item, Mapping)]
    merged: list[dict[str, Any]] = []
    for key in ("episodes", "profiles", "agent_cases", "agent_skills"):
        rows = data.get(key)
        if isinstance(rows, list):
            merged.extend(dict(item) for item in rows if isinstance(item, Mapping))
    return merged


def _content_text(item: Mapping[str, Any]) -> str:
    content = item.get("content") or item.get("text")
    if not content:
        summary = str(item.get("summary") or "").strip()
        episode = str(item.get("episode") or "").strip()
        content = episode if episode.startswith(summary) else "\n".join(
            value for value in (summary, episode) if value
        )
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, Mapping):
        for key in ("summary", "text", "markdown", "body"):
            value = content.get(key)
            if isinstance(value, str):
                return value.strip()
    return str(content or "").strip()


def _item_id(item: Mapping[str, Any]) -> str:
    return str(item.get("id") or item.get("memory_id") or "").strip()


def _source(item: Mapping[str, Any], score: float | None = None) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    return {
        "id": _item_id(item),
        "session_id": item.get("session_id") or metadata.get("session_id"),
        "window_id": item.get("window_id") or metadata.get("window_id"),
        "manifest": metadata.get("manifest")
        or metadata.get("bridge_manifest")
        or item.get("manifest"),
        "score": score if score is not None else item.get("score"),
        "memory_type": item.get("memory_type") or item.get("type") or "episode",
    }


def _timestamp_ms(value: object) -> int | None:
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 10_000_000_000 else number * 1000
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def _display_time(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(
        timestamp_ms / 1000,
        tz=ZoneInfo("Asia/Shanghai"),
    ).strftime("%Y-%m-%d %H:%M:%S")


def _normalise_file_uri(uri: str, root: Path) -> tuple[Path, str] | None:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
    elif parsed.scheme == "":
        path = Path(uri)
    else:
        return None
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return resolved, relative


def _even_sample(rows: Sequence[tuple[Path, str]], count: int) -> list[tuple[Path, str]]:
    if len(rows) <= count:
        return list(rows)
    if count == 1:
        return [rows[len(rows) // 2]]
    indices = [round(index * (len(rows) - 1) / (count - 1)) for index in range(count)]
    return [rows[index] for index in dict.fromkeys(indices)]


def _text_value(value: object) -> str:
    if isinstance(value, Mapping):
        value = value.get("value") or value.get("text") or ""
    return " ".join(str(value or "").split()).strip()


def _capsule_search_text(capsule: Mapping[str, Any]) -> str:
    """Build a rebuildable retrieval projection from one technical window."""

    interpretation = (
        capsule.get("interpretation")
        if isinstance(capsule.get("interpretation"), Mapping)
        else {}
    )
    stabilized = (
        capsule.get("stabilized_projection")
        if isinstance(capsule.get("stabilized_projection"), Mapping)
        else {}
    )
    asr = capsule.get("asr") if isinstance(capsule.get("asr"), Mapping) else {}
    values = [
        _text_value(capsule.get("scene")),
        _text_value(capsule.get("activity")),
        _text_value(stabilized.get("corrected_caption")),
        _text_value(interpretation.get("first_person_caption")),
        _text_value(capsule.get("text")),
        _text_value(asr.get("transcript")),
    ]
    for row in capsule.get("observations", []):
        if isinstance(row, Mapping):
            values.append(_text_value(row.get("text")))
    for row in capsule.get("objects", []):
        if isinstance(row, Mapping):
            values.append(
                _text_value(
                    row.get("label")
                    or row.get("object_label")
                    or row.get("normalized_label")
                )
            )
    return "；".join(dict.fromkeys(value for value in values if value))


def _capsule_caption(capsule: Mapping[str, Any]) -> str:
    """Return the user-facing first-person caption without appending ASR."""

    interpretation = (
        capsule.get("interpretation")
        if isinstance(capsule.get("interpretation"), Mapping)
        else {}
    )
    stabilized = (
        capsule.get("stabilized_projection")
        if isinstance(capsule.get("stabilized_projection"), Mapping)
        else {}
    )
    for value in (
        stabilized.get("corrected_caption"),
        interpretation.get("first_person_caption"),
        capsule.get("text"),
    ):
        caption = _text_value(value)
        if caption:
            return caption
    return ""


def _capsule_evidence(capsule: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in capsule.get("evidence", [])
        if isinstance(row, Mapping) and row.get("uri")
    ]


def _focused_excerpt(text: str, query: str, *, limit: int = 420) -> str:
    text = " ".join(text.split()).strip()
    query = " ".join(query.split()).strip()
    if len(text) <= limit or not query:
        return text[:limit]
    match = SequenceMatcher(None, query.casefold(), text.casefold()).find_longest_match()
    if match.size < 2:
        return text[:limit]
    start = max(0, match.b - limit // 5)
    end = min(len(text), start + limit)
    prefix = "…" if start else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


class ProductionMemorySearch:
    """Production retrieval bridge; EverOS remains the memory truth source."""

    def __init__(self, settings: Any, *, post_json: PostJSON | None = None) -> None:
        self.settings = settings
        self.raw_media_root = Path(settings.raw_media_dir).expanduser().resolve()
        self.projection_path = Path(
            settings.memory_search_visual_projection_path
        ).expanduser()
        if not self.projection_path.is_absolute():
            self.projection_path = (Path.cwd() / self.projection_path).resolve()
        self.embedding_url = settings.memory_search_embedding_url
        self.embedding_model = settings.memory_search_embedding_model
        self.embedding_api_key = settings.memory_search_embedding_api_key
        self.reranker_url = settings.memory_search_reranker_url
        self.reranker_model = settings.memory_search_reranker_model
        self.reranker_api_key = settings.memory_search_reranker_api_key
        self.candidate_k = settings.memory_search_candidate_k
        self.visual_frames_per_episode = settings.memory_search_visual_frames_per_episode
        self.visual_reranker_candidates = settings.memory_search_visual_reranker_candidates
        self.visual_embedding_weight = settings.memory_search_visual_embedding_weight
        self.no_answer_policy = NoAnswerPolicy(
            min_reranker_score=settings.memory_search_no_answer_min_score,
            min_reranker_margin=settings.memory_search_no_answer_min_margin,
        )
        self.pipeline_version = settings.memory_search_pipeline_version
        self._post_json_override = post_json
        self._projection_lock = asyncio.Lock()

    def _post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        if self._post_json_override is not None:
            return self._post_json_override(url, payload)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        api_key = (
            self.embedding_api_key
            if url == self.embedding_url
            else self.reranker_api_key
            if url == self.reranker_url
            else ""
        )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.settings.memory_search_model_timeout_seconds,
            ) as response:
                value = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"retrieval model HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"retrieval model request failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError("retrieval model response is not an object")
        return value

    async def search_text(
        self,
        *,
        everos: Any,
        review_store: Any,
        user_id: str,
        query: str,
        query_type: str,
        top_k: int,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        # Memory search has one responsibility: retrieve EverOS Episodes.
        # Object lookup is exposed by the independent search_objects tool and
        # must never be inferred here from regexes or wording.
        resolved_type = "text"
        try:
            return await self._search_everos_text(
                everos=everos,
                review_store=review_store,
                user_id=user_id,
                query=query,
                top_k=top_k,
                started=started,
                resolved_type="text",
            )
        except Exception as exc:
            return self._response(
                query_type=resolved_type,
                status="error",
                results=[],
                started=started,
                degraded_reasons=[f"{type(exc).__name__}: {str(exc)[:180]}"],
            )

    async def search_media(
        self,
        *,
        everos: Any,
        review_store: Any,
        user_id: str,
        query: str,
        media_path: Path,
        top_k: int,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        query_type = "image_text" if query.strip() else "image"
        degraded: list[str] = []
        try:
            episodes_envelope = await everos.get_episodes(
                user_id,
                page=1,
                page_size=100,
                filters=None,
            )
            episode_items = _envelope_results(episodes_envelope)
            if not episode_items:
                return self._response(
                    query_type=query_type,
                    status="not_found",
                    results=[],
                    started=started,
                )
            rows = await self._refresh_visual_projection(
                episode_items=episode_items,
                review_store=review_store,
                user_id=user_id,
            )
            if not rows:
                return self._response(
                    query_type=query_type,
                    status="error",
                    results=[],
                    started=started,
                    degraded_reasons=["visual_projection_missing"],
                )
            query_ref = media_path.resolve().relative_to(self.raw_media_root).as_posix()
            query_sha = hashlib.sha256(media_path.read_bytes()).hexdigest()
            query_row = {
                "query_id": f"web-{uuid.uuid4().hex}",
                "query_type": query_type,
                "query_text": query.strip(),
                "query_media_ref": query_ref,
                "query_media_sha256": query_sha,
            }
            vector = await asyncio.to_thread(
                embed_query,
                query_row,
                dataset_parent=self.raw_media_root,
                embedding_url=self.embedding_url,
                embedding_model=self.embedding_model,
                post_json=self._post_json,
            )
            # Each projection document is one real evidence frame.  EverOS is
            # still the parent-memory truth; this index only supplies a frame
            # anchor inside that Episode.
            index = VisualEpisodeIndex(rows=rows, aggregation_weights=(1.0,))
            recalled = index.search(
                vector,
                owner_id=user_id,
                top_k=min(self.candidate_k, len(rows)),
            )
            ranked = recalled
            try:
                reranked = await asyncio.to_thread(
                    rerank_visual_candidates,
                    query_row,
                    recalled[: self.visual_reranker_candidates],
                    dataset_parent=self.raw_media_root,
                    reranker_url=self.reranker_url,
                    reranker_model=self.reranker_model,
                    post_json=self._post_json,
                )
                head = (
                    reranked
                    if len(reranked) == 1
                    else fuse_embedding_and_reranker(
                        recalled[: self.visual_reranker_candidates],
                        reranked,
                        embedding_weight=self.visual_embedding_weight,
                    )
                )
                ranked = [*head, *recalled[self.visual_reranker_candidates :]]
            except Exception as exc:
                degraded.append(f"visual_reranker_unavailable:{type(exc).__name__}")
            ranked = self._dedupe_episode_hits(ranked)
            item_by_id = {_item_id(item): item for item in episode_items}
            anchor_by_ref = self._visual_anchor_by_ref(
                review_store=review_store,
                episode_items=episode_items,
            )
            results: list[dict[str, Any]] = []
            for hit in ranked:
                item = item_by_id.get(hit.episode_id) or item_by_id.get(hit.document_id)
                if item is None:
                    continue
                hit_anchor = anchor_by_ref.get(str(hit.evidence_ref or ""))
                result = self._result_from_item(
                    item,
                    score=hit.score,
                    query_type=query_type,
                    evidence_ref=hit.evidence_ref,
                    review_store=review_store,
                    hit_anchor=hit_anchor,
                )
                if result is not None:
                    results.append(result)
                if len(results) >= top_k:
                    break
            status = "not_found" if not results else "degraded" if degraded else "found"
            return self._response(
                query_type=query_type,
                status=status,
                results=results,
                started=started,
                degraded_reasons=degraded,
            )
        except Exception as exc:
            return self._response(
                query_type=query_type,
                status="error",
                results=[],
                started=started,
                degraded_reasons=[f"{type(exc).__name__}: {str(exc)[:180]}"],
            )

    async def _search_everos_text(
        self,
        *,
        everos: Any,
        review_store: Any,
        user_id: str,
        query: str,
        top_k: int,
        started: float,
        resolved_type: str,
    ) -> dict[str, Any]:
        envelope = await everos.search(
            user_id,
            query,
            top_k=max(top_k, self.candidate_k),
            include_profile=True,
        )
        items = [item for item in _envelope_results(envelope) if _item_id(item) and _content_text(item)]
        if not items:
            return self._response(
                query_type=resolved_type,
                status="not_found",
                results=[],
                started=started,
                everos=envelope,
            )
        recalled = self._dedupe_episode_hits(
            [
                RetrievedEpisode(
                    document_id=_item_id(item),
                    episode_id=_item_id(item),
                    episode_text=_content_text(item),
                    score=float(item.get("score") or 0.0),
                )
                for item in items
            ]
        )
        degraded: list[str] = []
        ranked = recalled
        reranked: list[RetrievedEpisode] | None = None
        try:
            reranked = await asyncio.to_thread(
                rerank_candidates,
                {
                    "query_id": f"web-{uuid.uuid4().hex}",
                    "query_type": "text",
                    "query_text": query,
                },
                recalled,
                dataset_parent=self.raw_media_root,
                reranker_url=self.reranker_url,
                reranker_model=self.reranker_model,
                post_json=self._post_json,
            )
            if len(recalled) == 1:
                ranked = reranked
            else:
                ranked = fuse_embedding_and_reranker(recalled, reranked)
        except Exception as exc:
            degraded.append(f"reranker_unavailable:{type(exc).__name__}")
        episode_should_abstain = False
        if reranked:
            ordered_reranker = sorted(reranked, key=lambda row: (-row.score, row.document_id))
            top_score = ordered_reranker[0].score
            margin = top_score - ordered_reranker[1].score if len(ordered_reranker) > 1 else 0.0
            episode_should_abstain = self.no_answer_policy.should_abstain(
                top1_score=top_score,
                top1_margin=margin,
            )
        lexical_episode_ids = {
            _item_id(item)
            for item in items
            if _has_lexical_support(query, _content_text(item))
        }
        if episode_should_abstain and not lexical_episode_ids:
            return self._response(
                query_type=resolved_type,
                status="not_found",
                results=[],
                started=started,
                degraded_reasons=degraded,
                everos=envelope,
            )

        ranked = self._dedupe_episode_hits(ranked)
        item_by_id = {_item_id(item): item for item in items}
        segment_rows, segment_sources = self._text_segment_candidates(
            ranked=ranked,
            item_by_id=item_by_id,
            review_store=review_store,
        )
        episodes_with_segment_candidates = {
            row.episode_id for row in segment_rows
        }
        selected_segments: dict[str, RetrievedEpisode] = {}
        if segment_rows:
            try:
                reranked_segments = await asyncio.to_thread(
                    rerank_candidates,
                    {
                        "query_id": f"web-capsule-{uuid.uuid4().hex}",
                        "query_type": "text",
                        "query_text": query,
                    },
                    segment_rows,
                    dataset_parent=self.raw_media_root,
                    reranker_url=self.reranker_url,
                    reranker_model=self.reranker_model,
                    post_json=self._post_json,
                )
                for hit in sorted(
                    reranked_segments,
                    key=lambda row: (-row.score, row.document_id),
                ):
                    # One concrete Capsule is selected for each parent Episode.
                    # This prevents several cards for one Episode and prevents
                    # every Episode in the same boot session from opening the
                    # same undifferentiated evidence list.
                    source_pair = segment_sources.get(hit.document_id)
                    capsule_text = (
                        _capsule_search_text(source_pair[1])
                        if source_pair is not None
                        else ""
                    )
                    if (
                        hit.score >= self.no_answer_policy.min_reranker_score
                        or _has_lexical_support(query, capsule_text)
                    ):
                        selected_segments.setdefault(hit.episode_id, hit)
            except Exception as exc:
                degraded.append(f"capsule_reranker_unavailable:{type(exc).__name__}")
                for hit in segment_rows:
                    selected_segments.setdefault(hit.episode_id, hit)
        results: list[dict[str, Any]] = []
        for hit in ranked:
            item = item_by_id.get(hit.document_id)
            if item is None:
                continue
            # An explicit noun/phrase match is stronger than a broad semantic
            # association for Web search. Once EverOS returned at least one
            # lexically grounded Episode, do not mix in unrelated high-scoring
            # semantic neighbours merely to fill ``top_k``.
            if lexical_episode_ids and hit.document_id not in lexical_episode_ids:
                continue
            segment_hit = selected_segments.get(hit.episode_id)
            if (
                hit.episode_id in episodes_with_segment_candidates
                and segment_hit is None
            ):
                # The parent Episode was recalled, but none of its concrete
                # Capsules passed the precision gate for this query.
                continue
            anchor = None
            result_score = hit.score
            if segment_hit is not None:
                source_pair = segment_sources.get(segment_hit.document_id)
                if source_pair is not None:
                    _, capsule = source_pair
                    anchor = self._capsule_anchor(
                        capsule,
                        hit_kind="capsule_fragment",
                        query=query,
                    )
                    result_score = segment_hit.score
            result = self._result_from_item(
                item,
                score=result_score,
                query_type=resolved_type,
                evidence_ref=None,
                review_store=review_store,
                hit_anchor=anchor,
            )
            if result is not None:
                results.append(result)
            if len(results) >= top_k:
                break
        status = "not_found" if not results else "degraded" if degraded else "found"
        return self._response(
            query_type=resolved_type,
            status=status,
            results=results,
            started=started,
            degraded_reasons=degraded,
            everos=envelope,
        )

    async def _search_object(
        self,
        *,
        everos: Any,
        review_store: Any,
        user_id: str,
        query: str,
        top_k: int,
        started: float,
    ) -> dict[str, Any]:
        object_term = self._object_term(query, review_store)
        degraded: list[str] = []
        object_result: dict[str, Any] | None = None
        try:
            last_seen = review_store.query_last_seen_object(object_term)
            latest = last_seen.get("latest_reliable")
            if isinstance(latest, Mapping):
                evidence_uris = [str(value) for value in latest.get("evidence_uris", []) if value]
                source_id = str(
                    latest.get("observation_id")
                    or latest.get("id")
                    or f"object:{last_seen.get('normalized_query') or object_term}"
                )
                captured_at_ms = _timestamp_ms(latest.get("captured_at_ms"))
                object_result = {
                    "result_id": source_id,
                    "rank": 0,
                    "episode_id": None,
                    "capsule_ids": [latest.get("source_capsule_id")]
                    if latest.get("source_capsule_id")
                    else [],
                    "title": f"{object_term}的最近可靠证据",
                    "summary": str(last_seen.get("answer") or ""),
                    "content": str(last_seen.get("answer") or ""),
                    "occurred_at_ms": captured_at_ms,
                    "display_time": _display_time(captured_at_ms),
                    "match_reason": "来自物品 Last-seen 的最近可靠观察",
                    "provenance": "model_inference",
                    "source_refs": [f"object-observation://{source_id}"],
                    "evidence_refs": evidence_uris,
                    "score": float(latest.get("semantic_confidence") or 0.0),
                    "source": {
                        "id": source_id,
                        "session_id": latest.get("boot_session_id"),
                        "window_id": latest.get("window_id"),
                        "manifest": None,
                        "score": latest.get("semantic_confidence"),
                        "memory_type": "object_last_seen",
                    },
                    "atomic_facts": [],
                    "object_last_seen": last_seen,
                }
            else:
                degraded.append("object_last_seen_not_found")
        except Exception as exc:
            degraded.append(f"object_last_seen_unavailable:{type(exc).__name__}")
        context = await self._search_everos_text(
            everos=everos,
            review_store=review_store,
            user_id=user_id,
            query=query,
            top_k=top_k,
            started=started,
            resolved_type="object_last_seen",
        )
        results = list(context.get("results") or [])
        if object_result is not None:
            results.insert(0, object_result)
        results = self._dedupe(results)[:top_k]
        for rank, item in enumerate(results, start=1):
            item["rank"] = rank
        context_degraded = list(
            (context.get("retrieval") or {}).get("degraded_reasons") or []
        )
        degraded.extend(context_degraded)
        if object_result is not None:
            status = "degraded" if context.get("answer_status") == "error" else "found"
        elif results:
            status = "degraded"
        else:
            status = "not_found" if context.get("answer_status") != "error" else "error"
        return self._response(
            query_type="object_last_seen",
            status=status,
            results=results,
            started=started,
            degraded_reasons=list(dict.fromkeys(degraded)),
            everos=context.get("everos"),
        )

    def _text_segment_candidates(
        self,
        *,
        ranked: Sequence[RetrievedEpisode],
        item_by_id: Mapping[str, Mapping[str, Any]],
        review_store: Any,
    ) -> tuple[
        list[RetrievedEpisode],
        dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]],
    ]:
        snapshot = review_store.snapshot()
        capsules = [
            row for row in snapshot.get("capsules", []) if isinstance(row, Mapping)
        ]
        rows: list[RetrievedEpisode] = []
        sources: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
        episodes_by_session: dict[
            str, list[tuple[RetrievedEpisode, Mapping[str, Any]]]
        ] = {}
        for episode_hit in self._dedupe_episode_hits(ranked):
            item = item_by_id.get(episode_hit.document_id)
            session_id = str(item.get("session_id") or "") if item is not None else ""
            if item is not None and session_id:
                episodes_by_session.setdefault(session_id, []).append((episode_hit, item))

        capsules_by_session: dict[str, list[Mapping[str, Any]]] = {}
        for capsule in capsules:
            session_id = str(capsule.get("boot_session_id") or "")
            if session_id in episodes_by_session:
                capsules_by_session.setdefault(session_id, []).append(capsule)

        for session_id, episode_pairs in episodes_by_session.items():
            episode_pairs.sort(
                key=lambda pair: (
                    _timestamp_ms(
                        pair[1].get("timestamp")
                        or pair[1].get("captured_at_ms")
                        or pair[1].get("created_at")
                    )
                    or 0,
                    pair[0].episode_id,
                )
            )
            matches = sorted(
                capsules_by_session.get(session_id, []),
                key=lambda capsule: int(capsule.get("captured_at_ms") or 0),
            )
            # A stabilized context thread is one semantic event. Assign the
            # whole thread to one EverOS Episode; assigning each Capsule by its
            # nearest timestamp can split a two-window event because EverOS
            # commonly timestamps the Episode at the final window.
            grouped: dict[str, list[Mapping[str, Any]]] = {}
            group_order: list[str] = []
            for index, capsule in enumerate(matches):
                stabilized = (
                    capsule.get("stabilized_projection")
                    if isinstance(capsule.get("stabilized_projection"), Mapping)
                    else {}
                )
                group_id = str(
                    stabilized.get("context_thread_id")
                    or capsule.get("event_queue_id")
                    or f"unthreaded:{index}"
                )
                if group_id not in grouped:
                    group_order.append(group_id)
                    grouped[group_id] = []
                grouped[group_id].append(capsule)

            assignments: dict[str, list[Mapping[str, Any]]] = {
                hit.episode_id: [] for hit, _ in episode_pairs
            }
            ordered_groups = [grouped[group_id] for group_id in group_order]
            if len(ordered_groups) == len(episode_pairs):
                group_assignments = [
                    (episode_pairs[index][0], capsules)
                    for index, capsules in enumerate(ordered_groups)
                ]
            else:
                group_assignments = []
                for index, capsules in enumerate(ordered_groups):
                    group_time = max(
                        (
                            _timestamp_ms(capsule.get("captured_at_ms")) or 0
                            for capsule in capsules
                        ),
                        default=0,
                    )
                    if len(episode_pairs) == 1:
                        assigned_hit = episode_pairs[0][0]
                    elif group_time:
                        assigned_hit = min(
                            episode_pairs,
                            key=lambda pair: (
                                abs(
                                    group_time
                                    - (
                                        _timestamp_ms(
                                            pair[1].get("timestamp")
                                            or pair[1].get("captured_at_ms")
                                            or pair[1].get("created_at")
                                        )
                                        or group_time
                                    )
                                ),
                                pair[0].episode_id,
                            ),
                        )[0]
                    else:
                        assigned_hit = episode_pairs[index % len(episode_pairs)][0]
                    group_assignments.append((assigned_hit, capsules))
            for assigned_hit, capsules in group_assignments:
                assignments[assigned_hit.episode_id].extend(capsules)

            for episode_hit, item in episode_pairs:
                for capsule in assignments[episode_hit.episode_id]:
                    capsule_id = str(capsule.get("id") or capsule.get("window_id") or "")
                    text = _capsule_search_text(capsule)
                    if not capsule_id or not text:
                        continue
                    document_id = f"{episode_hit.episode_id}::capsule::{capsule_id}"
                    rows.append(
                        RetrievedEpisode(
                            document_id=document_id,
                            episode_id=episode_hit.episode_id,
                            episode_text=text[:4000],
                            score=episode_hit.score,
                        )
                    )
                    sources[document_id] = (item, capsule)
        limited = rows[:100]
        return limited, {row.document_id: sources[row.document_id] for row in limited}

    @staticmethod
    def _dedupe_episode_hits(
        hits: Sequence[RetrievedEpisode],
    ) -> list[RetrievedEpisode]:
        output: list[RetrievedEpisode] = []
        seen: set[str] = set()
        for hit in hits:
            episode_id = str(hit.episode_id or hit.document_id)
            if not episode_id or episode_id in seen:
                continue
            seen.add(episode_id)
            output.append(hit)
        return output

    def _capsule_anchor(
        self,
        capsule: Mapping[str, Any],
        *,
        hit_kind: str,
        preferred_uri: str | None = None,
        preferred_evidence_id: str | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        evidence = _capsule_evidence(capsule)
        images = [row for row in evidence if str(row.get("kind")) == "image"]
        audio = [row for row in evidence if str(row.get("kind")) == "audio"]
        captured_at_ms = int(capsule.get("captured_at_ms") or 0) or None
        duration_ms = int(capsule.get("duration_ms") or 0) or None
        if preferred_uri:
            preferred = next(
                (row for row in evidence if str(row.get("uri")) == preferred_uri),
                None,
            )
        else:
            preferred = None
        if preferred is None and images:
            midpoint = (captured_at_ms or 0) + (duration_ms or 0) // 2
            preferred = min(
                images,
                key=lambda row: abs(int(row.get("captured_at_ms") or midpoint) - midpoint),
            )
        if preferred is None and audio:
            preferred = audio[0]
        asr = capsule.get("asr") if isinstance(capsule.get("asr"), Mapping) else {}
        transcript = _text_value(asr.get("transcript"))
        caption = _capsule_caption(capsule)
        # The reranker sees the full Capsule projection (scene, activity,
        # caption and ASR), so the visible excerpt must come from that same
        # text.  Otherwise a hit caused by visual context such as “手机” could
        # show an unrelated-looking transcript excerpt.
        snippet_source = caption or transcript
        snippet = _focused_excerpt(snippet_source, query)
        frame_at_ms = (
            _timestamp_ms(preferred.get("captured_at_ms"))
            if isinstance(preferred, Mapping)
            else None
        )
        return {
            "kind": hit_kind,
            "precision": "exact_frame" if hit_kind == "visual_frame" else "technical_window",
            "capsule_id": capsule.get("id"),
            "window_id": capsule.get("window_id"),
            "session_id": capsule.get("boot_session_id"),
            "start_ms": captured_at_ms,
            "end_ms": captured_at_ms + duration_ms
            if captured_at_ms is not None and duration_ms is not None
            else None,
            "display_time": _display_time(
                frame_at_ms if hit_kind == "visual_frame" else captured_at_ms
            ),
            "frame_at_ms": frame_at_ms,
            "duration_ms": duration_ms,
            "scene": _text_value(capsule.get("scene")),
            "activity": _text_value(capsule.get("activity")),
            "snippet": snippet,
            "transcript_excerpt": transcript[:900],
            "primary_evidence_ref": str(preferred.get("uri"))
            if isinstance(preferred, Mapping)
            else None,
            "primary_evidence_id": preferred_evidence_id
            or (str(preferred.get("id")) if isinstance(preferred, Mapping) else None),
            "image_refs": [str(row.get("uri")) for row in images],
            "audio_refs": [str(row.get("uri")) for row in audio],
            "evidence_refs": [str(row.get("uri")) for row in evidence],
        }

    def _visual_anchor_by_ref(
        self,
        *,
        review_store: Any,
        episode_items: Sequence[Mapping[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        sessions = {
            str(item.get("session_id") or "")
            for item in episode_items
            if item.get("session_id")
        }
        output: dict[str, dict[str, Any]] = {}
        for capsule in review_store.snapshot().get("capsules", []):
            if not isinstance(capsule, Mapping):
                continue
            if str(capsule.get("boot_session_id") or "") not in sessions:
                continue
            for evidence in _capsule_evidence(capsule):
                uri = str(evidence.get("uri") or "")
                parsed = _normalise_file_uri(uri, self.raw_media_root)
                if parsed is None or str(evidence.get("kind")) != "image":
                    continue
                _, relative = parsed
                output[relative] = self._capsule_anchor(
                    capsule,
                    hit_kind="visual_frame",
                    preferred_uri=uri,
                    preferred_evidence_id=str(evidence.get("id") or ""),
                )
        return output

    async def _refresh_visual_projection(
        self,
        *,
        episode_items: Sequence[Mapping[str, Any]],
        review_store: Any,
        user_id: str,
    ) -> list[dict[str, object]]:
        async with self._projection_lock:
            snapshot = review_store.snapshot()
            capsules = [
                item for item in snapshot.get("capsules", []) if isinstance(item, Mapping)
            ]
            existing: dict[tuple[str, str], dict[str, object]] = {}
            if self.projection_path.is_file():
                for line in self.projection_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if isinstance(value, dict):
                        existing[(str(value.get("episode_id")), str(value.get("evidence_sha256")))] = value
            rows: list[dict[str, object]] = []
            for episode in episode_items:
                episode_id = _item_id(episode)
                session_id = str(episode.get("session_id") or "")
                episode_text = _content_text(episode)
                if not episode_id or not session_id or not episode_text:
                    continue
                evidence: list[
                    tuple[Path, str, Mapping[str, Any], Mapping[str, Any]]
                ] = []
                session_capsules = sorted(
                    (
                        item
                        for item in capsules
                        if str(item.get("boot_session_id") or "") == session_id
                    ),
                    key=lambda item: int(item.get("captured_at_ms") or 0),
                )
                for capsule in session_capsules:
                    for item in capsule.get("evidence", []):
                        if not isinstance(item, Mapping):
                            continue
                        uri = str(item.get("uri") or "")
                        kind = str(item.get("kind") or "")
                        mime = mimetypes.guess_type(urlparse(uri).path)[0] or ""
                        if kind != "image" and not mime.startswith("image/"):
                            continue
                        parsed = _normalise_file_uri(uri, self.raw_media_root)
                        if parsed is not None:
                            evidence.append((*parsed, capsule, item))
                unique_by_ref = {row[1]: row for row in evidence}
                unique = list(unique_by_ref.values())
                sampled = _even_sample(unique, self.visual_frames_per_episode)
                for path, relative, capsule, evidence_item in sampled:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    capsule_id = str(
                        capsule.get("id") or capsule.get("window_id") or "unknown"
                    )
                    document_id = f"{episode_id}::frame::{capsule_id}::{digest[:12]}"
                    segment_text = _capsule_search_text(capsule) or episode_text
                    cached = existing.get((episode_id, digest))
                    if cached is not None and cached.get("embedding_model") == self.embedding_model:
                        row = dict(cached)
                        row.update(
                            {
                                "contract_version": 2,
                                "owner_id": user_id,
                                "document_id": document_id,
                                "episode_id": episode_id,
                                "episode_text": segment_text,
                                "evidence_ref": relative,
                                "capsule_id": capsule_id,
                                "window_id": capsule.get("window_id"),
                                "captured_at_ms": evidence_item.get("captured_at_ms"),
                            }
                        )
                    else:
                        vector = await asyncio.to_thread(
                            embed_query,
                            {
                                "query_id": f"production-projection:{episode_id}:{digest[:12]}",
                                "query_type": "image",
                                "query_text": "",
                                "query_media_ref": relative,
                                "query_media_sha256": digest,
                            },
                            dataset_parent=self.raw_media_root,
                            embedding_url=self.embedding_url,
                            embedding_model=self.embedding_model,
                            post_json=self._post_json,
                        )
                        row = {
                            "contract_version": 2,
                            "owner_id": user_id,
                            "document_id": document_id,
                            "episode_id": episode_id,
                            "episode_text": segment_text,
                            "evidence_ref": relative,
                            "evidence_sha256": digest,
                            "capsule_id": capsule_id,
                            "window_id": capsule.get("window_id"),
                            "captured_at_ms": evidence_item.get("captured_at_ms"),
                            "embedding_model": self.embedding_model,
                            "vector": vector,
                        }
                    rows.append(row)
            if rows:
                self.projection_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.projection_path.with_suffix(
                    self.projection_path.suffix + f".{uuid.uuid4().hex}.tmp"
                )
                temporary.write_text(
                    "".join(
                        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                        for row in rows
                    ),
                    encoding="utf-8",
                )
                temporary.replace(self.projection_path)
            return rows

    def _result_from_item(
        self,
        item: Mapping[str, Any],
        *,
        score: float,
        query_type: str,
        evidence_ref: str | None,
        review_store: Any,
        hit_anchor: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        source = _source(item, score)
        source_id = str(source["id"] or "")
        projected = review_store.apply_corrections(
            target_type="episode",
            target_id=source_id,
            source=dict(item),
        )
        if projected is None:
            return None
        original = _content_text(item)
        content = _content_text(projected) or original
        correction_projection = projected.get("correction_projection") or {}
        provenance = (
            "user_corrected"
            if correction_projection.get("status") == "corrected"
            else "everos_extracted"
        )
        episode_timestamp_ms = _timestamp_ms(
            item.get("timestamp") or item.get("captured_at_ms") or item.get("created_at")
        )
        title = str(
            projected.get("title")
            or projected.get("subject")
            or projected.get("summary")
            or ""
        ).strip()
        if not title:
            title = content[:60] + ("…" if len(content) > 60 else "")
        summary = str(projected.get("summary") or "").strip() or content[:240]
        evidence_refs: list[str] = []
        if evidence_ref:
            evidence_path = (self.raw_media_root / evidence_ref).resolve()
            try:
                evidence_path.relative_to(self.raw_media_root)
                evidence_refs.append(evidence_path.as_uri())
            except ValueError:
                pass
        if source.get("manifest"):
            evidence_refs.append(str(source["manifest"]))
        anchor = dict(hit_anchor) if isinstance(hit_anchor, Mapping) else None
        if anchor:
            evidence_refs = [
                str(value)
                for value in anchor.get("evidence_refs", [])
                if value
            ] or evidence_refs
            anchor_content = str(anchor.get("snippet") or "").strip()
            if anchor_content:
                content = anchor_content
                summary = anchor_content[:240]
            timestamp_ms = _timestamp_ms(
                anchor.get("frame_at_ms")
                if anchor.get("kind") == "visual_frame"
                else anchor.get("start_ms")
            ) or episode_timestamp_ms
            capsule_id = str(anchor.get("capsule_id") or "")
            evidence_id = str(anchor.get("primary_evidence_id") or "")
            anchor_identity = evidence_id or capsule_id or str(anchor.get("window_id") or "")
            result_id = f"segment:{source_id}:{anchor_identity}"
            result_kind = (
                "visual_frame"
                if anchor.get("kind") == "visual_frame"
                else "capsule_fragment"
            )
            source["window_id"] = anchor.get("window_id") or source.get("window_id")
        else:
            timestamp_ms = episode_timestamp_ms
            capsule_id = ""
            result_id = f"episode:{source_id}"
            result_kind = "episode"
        match_reason = {
            "text": "EverOS Episode 召回后，已定位到其中最相关的 Capsule",
            "image": "查询图片与该具体证据帧相似",
            "image_text": "查询图片命中该具体帧，文字线索进一步约束排序",
            "object_last_seen": "EverOS 中包含与该物品问题相关的事件上下文",
        }.get(query_type, "与查询相关")
        facts = [
            dict(value)
            for value in item.get("atomic_facts", [])
            if isinstance(value, Mapping)
        ]
        return {
            "result_id": result_id,
            "result_kind": result_kind,
            "rank": 0,
            "episode_id": source_id,
            "capsule_ids": [capsule_id] if capsule_id else [],
            "title": title,
            "summary": summary,
            "content": content,
            "occurred_at_ms": timestamp_ms,
            "display_time": _display_time(timestamp_ms),
            "match_reason": match_reason,
            "provenance": provenance,
            "source_refs": [f"everos://episode/{source_id}"],
            "evidence_refs": list(dict.fromkeys(evidence_refs)),
            "score": float(score),
            "source": source,
            "atomic_facts": facts,
            "hit": anchor,
            "parent_episode": {
                "episode_id": source_id,
                "title": title,
                "summary": summary,
                "content": content,
                "occurred_at_ms": episode_timestamp_ms,
                "display_time": _display_time(episode_timestamp_ms),
                "source_ref": f"everos://episode/{source_id}",
            },
            "everos": dict(item),
            "correction_projection": correction_projection,
        }

    def _response(
        self,
        *,
        query_type: str,
        status: str,
        results: Sequence[Mapping[str, Any]],
        started: float,
        degraded_reasons: Sequence[str] = (),
        everos: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        deduped = self._dedupe([dict(item) for item in results])
        for rank, item in enumerate(deduped, start=1):
            item["rank"] = rank
        latency_ms = round(max(0.0, (time.perf_counter() - started) * 1000), 3)
        if status == "not_found":
            summary = "未找到可靠证据。"
        elif status == "error":
            summary = "记忆检索暂时不可用，未生成猜测答案。"
        elif status == "degraded":
            summary = f"找到 {len(deduped)} 条记忆，但部分检索能力暂时降级。"
        else:
            summary = f"找到 {len(deduped)} 条有可靠来源的相关记忆。"
        return {
            "query_id": f"search-{uuid.uuid4().hex}",
            "query_type": query_type,
            "answer_status": status,
            "summary": summary,
            "results": deduped,
            "retrieval": {
                "pipeline_version": self.pipeline_version,
                "degraded": status == "degraded",
                "degraded_reasons": list(dict.fromkeys(degraded_reasons)),
                "latency_ms": latency_ms,
            },
            "everos": dict(everos) if isinstance(everos, Mapping) else None,
        }

    @staticmethod
    def _dedupe(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in results:
            key = str(
                item.get("result_id")
                or item.get("episode_id")
                or ""
            )
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(item)
        return output

    @staticmethod
    def _resolve_query_type(query: str, query_type: str) -> str:
        return "text"

    @staticmethod
    def _object_term(query: str, review_store: Any) -> str:
        snapshot = review_store.snapshot()
        candidates: list[str] = []
        for item in snapshot.get("confirmed_objects", []):
            if not isinstance(item, Mapping):
                continue
            candidates.extend(
                str(value).strip()
                for value in [item.get("label"), *(item.get("aliases") or [])]
                if value
            )
        for item in snapshot.get("object_observations", []):
            if isinstance(item, Mapping):
                value = item.get("object_label_raw") or item.get("object_label") or item.get("normalized_label")
                if value:
                    candidates.append(str(value).strip())
        matches = [value for value in candidates if value and value.casefold() in query.casefold()]
        if matches:
            return max(matches, key=len)
        patterns = (
            r"(?:我的)?(.{1,16}?)(?:最后|上次)",
            r"(?:最后|上次).{0,8}(?:看到|见到|把)?(.{1,12}?)(?:放在|放到|在哪|哪里|哪儿|哪裡)",
        )
        for pattern in patterns:
            match = re.search(pattern, query)
            if match and match.group(1).strip():
                return match.group(1).strip("，。！？? 的")
        return query.strip()
