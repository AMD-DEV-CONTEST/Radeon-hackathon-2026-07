from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import math
import mimetypes
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence
import urllib.error
import urllib.request


PostJSON = Callable[[str, dict[str, object]], dict[str, object]]
EMBEDDING_DIMENSION = 1024
DEFAULT_EMBEDDING_FUSION_WEIGHT = 0.15
IMAGE_QUERY_TYPES = frozenset({"image", "image_text", "image_text_proxy"})


@dataclass(frozen=True)
class RetrievedEpisode:
    document_id: str
    episode_id: str
    episode_text: str
    score: float
    evidence_ref: str | None = None


@dataclass(frozen=True)
class NoAnswerPolicy:
    min_reranker_score: float = 0.4
    min_reranker_margin: float | None = None

    def should_abstain(self, *, top1_score: float, top1_margin: float) -> bool:
        if top1_score >= self.min_reranker_score:
            return False
        if (
            self.min_reranker_margin is not None
            and top1_margin >= self.min_reranker_margin
        ):
            return False
        return True


def _default_post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300.0) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"model endpoint HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"model endpoint request failed: {type(exc).__name__}") from exc
    if not isinstance(body, dict):
        raise RuntimeError("model endpoint response is not a JSON object")
    return body


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _verified_media(query: Mapping[str, object], dataset_parent: Path) -> Path:
    reference = query.get("query_media_ref")
    expected = query.get("query_media_sha256")
    if not reference or not expected:
        raise ValueError(f"query {query.get('query_id', '')} is missing media contract")
    path = (dataset_parent / str(reference)).resolve()
    try:
        path.relative_to(dataset_parent.resolve())
    except ValueError as exc:
        raise ValueError(f"query media escapes dataset parent: {reference}") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"media SHA-256 mismatch for {query.get('query_id', '')}")
    return path


def build_embedding_payload(
    query: Mapping[str, object], dataset_parent: Path, model: str
) -> dict[str, object]:
    query_type = str(query.get("query_type", ""))
    query_text = str(query.get("query_text", "")).strip()
    if query_type not in IMAGE_QUERY_TYPES:
        if not query_text:
            raise ValueError(f"text query {query.get('query_id', '')} is empty")
        return {
            "model": model,
            "input": {"contents": [{"text": query_text}]},
            "parameters": {"dimension": EMBEDDING_DIMENSION},
        }

    path = _verified_media(query, dataset_parent)
    prompt = (
        query_text
        if query_type in {"image_text", "image_text_proxy"} and query_text
        else "Represent this egocentric image for personal memory retrieval."
    )
    return {
        "model": model,
        "input": {
            "contents": [
                {
                    "text": prompt,
                    "image": _data_url(path),
                }
            ]
        },
        "parameters": {"dimension": EMBEDDING_DIMENSION},
    }


def embed_query(
    query: Mapping[str, object],
    *,
    dataset_parent: Path,
    embedding_url: str,
    embedding_model: str,
    post_json: PostJSON = _default_post_json,
) -> list[float]:
    response = post_json(
        embedding_url,
        build_embedding_payload(query, dataset_parent, embedding_model),
    )
    output = response.get("output")
    rows = (
        output.get("embeddings") if isinstance(output, dict) else None
    ) or response.get("data")
    vector = rows[0].get("embedding") if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) else None
    if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSION:
        size = len(vector) if isinstance(vector, list) else 0
        raise ValueError(
            f"embedding response must contain one {EMBEDDING_DIMENSION}-dimensional vector; got {size}"
        )
    return [float(value) for value in vector]


def _quote(value: str) -> str:
    return value.replace("'", "''")


class EverOSEpisodeIndex:
    def __init__(self, *, table: Any, episode_to_document: Mapping[str, str]) -> None:
        self._table = table
        self._episode_to_document = dict(episode_to_document)

    @classmethod
    def open(
        cls, *, memory_root: Path, episode_to_document: Mapping[str, str]
    ) -> "EverOSEpisodeIndex":
        try:
            import lancedb
        except ImportError as exc:
            raise RuntimeError(
                "lancedb is required; run this command with the EverOS virtualenv"
            ) from exc
        database = lancedb.connect(memory_root / ".index" / "lancedb")
        table = database.open_table("episode")
        return cls(table=table, episode_to_document=episode_to_document)

    def search(
        self, vector: Sequence[float], *, owner_id: str, top_k: int = 20
    ) -> list[RetrievedEpisode]:
        if len(vector) != EMBEDDING_DIMENSION:
            raise ValueError(f"query vector must be {EMBEDDING_DIMENSION}-dimensional")
        if not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        where = (
            f"owner_id = '{_quote(owner_id)}' AND owner_type = 'user' "
            "AND app_id = 'default' AND project_id = 'default' "
            "AND deprecated_by IS NULL"
        )
        rows = self._table.search(list(vector)).where(where).limit(top_k).to_list()
        hits: list[RetrievedEpisode] = []
        for row in rows:
            episode_id = str(row.get("id", ""))
            document_id = self._episode_to_document.get(episode_id)
            if document_id is None:
                raise ValueError(f"unmapped EverOS Episode returned by index: {episode_id}")
            distance = float(row.get("_distance", 0.0))
            hits.append(
                RetrievedEpisode(
                    document_id=document_id,
                    episode_id=episode_id,
                    episode_text=str(row.get("episode", "")),
                    score=1.0 - distance,
                )
            )
        return hits


class VisualEpisodeIndex:
    """Small, rebuildable visual projection keyed back to EverOS Episodes.

    EverOS Markdown/Episode remains the memory truth.  This projection only
    stores evidence-image vectors and the minimum Episode fields needed to
    return and rerank a hit.  Deleting it never deletes a memory.
    """

    def __init__(
        self,
        *,
        rows: Sequence[Mapping[str, object]],
        aggregation_weights: Sequence[float] = (1.0,),
    ) -> None:
        weights = tuple(float(value) for value in aggregation_weights)
        if not weights or any(value < 0 or not math.isfinite(value) for value in weights):
            raise ValueError("aggregation weights must be finite and non-negative")
        if sum(weights) <= 0:
            raise ValueError("aggregation weights must have a positive sum")
        self._aggregation_weights = weights
        parsed: list[tuple[str, str, str, str, str, tuple[float, ...]]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            owner_id = str(row.get("owner_id", ""))
            document_id = str(row.get("document_id", ""))
            episode_id = str(row.get("episode_id", ""))
            episode_text = str(row.get("episode_text", ""))
            evidence_ref = str(row.get("evidence_ref", ""))
            vector_value = row.get("vector")
            if (
                not owner_id
                or not document_id
                or not episode_id
                or not episode_text
                or not evidence_ref
            ):
                raise ValueError("visual projection row is missing identity or Episode text")
            if not isinstance(vector_value, list) or len(vector_value) != EMBEDDING_DIMENSION:
                raise ValueError(
                    f"visual projection vector must be {EMBEDDING_DIMENSION}-dimensional"
                )
            key = (owner_id, document_id, evidence_ref)
            if key in seen:
                raise ValueError(f"duplicate visual projection row: {owner_id}:{document_id}")
            seen.add(key)
            vector = tuple(float(value) for value in vector_value)
            norm = math.sqrt(sum(value * value for value in vector))
            if not math.isfinite(norm) or norm == 0:
                raise ValueError(f"invalid visual projection vector: {document_id}")
            parsed.append(
                (owner_id, document_id, episode_id, episode_text, evidence_ref, vector)
            )
        self._rows = parsed

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        aggregation_weights: Sequence[float] = (1.0,),
    ) -> "VisualEpisodeIndex":
        rows: list[dict[str, object]] = []
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"visual projection line {line_number} is not an object")
                rows.append(value)
        return cls(rows=rows, aggregation_weights=aggregation_weights)

    def search(
        self, vector: Sequence[float], *, owner_id: str, top_k: int = 20
    ) -> list[RetrievedEpisode]:
        if len(vector) != EMBEDDING_DIMENSION:
            raise ValueError(f"query vector must be {EMBEDDING_DIMENSION}-dimensional")
        if not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        query = tuple(float(value) for value in vector)
        query_norm = math.sqrt(sum(value * value for value in query))
        if not math.isfinite(query_norm) or query_norm == 0:
            raise ValueError("query vector has zero or invalid norm")
        scores_by_document: dict[
            str, tuple[str, str, list[tuple[float, str]]]
        ] = {}
        for (
            row_owner,
            document_id,
            episode_id,
            episode_text,
            _evidence_ref,
            candidate,
        ) in self._rows:
            if row_owner != owner_id:
                continue
            candidate_norm = math.sqrt(sum(value * value for value in candidate))
            score = sum(left * right for left, right in zip(query, candidate, strict=True)) / (
                query_norm * candidate_norm
            )
            stored = scores_by_document.setdefault(
                document_id, (episode_id, episode_text, [])
            )
            stored[2].append((score, _evidence_ref))
        hits: list[RetrievedEpisode] = []
        for document_id, (episode_id, episode_text, evidence_rows) in (
            scores_by_document.items()
        ):
            ordered = sorted(evidence_rows, reverse=True)
            used_scores = ordered[: len(self._aggregation_weights)]
            used_weights = self._aggregation_weights[: len(used_scores)]
            weight_sum = sum(used_weights)
            aggregate = sum(
                score[0] * weight
                for score, weight in zip(used_scores, used_weights, strict=True)
            ) / weight_sum
            hits.append(
                RetrievedEpisode(
                    document_id=document_id,
                    episode_id=episode_id,
                    episode_text=episode_text,
                    score=aggregate,
                    evidence_ref=ordered[0][1],
                )
            )
        return sorted(hits, key=lambda row: (-row.score, row.document_id))[:top_k]


EpisodeProjectionIndex = VisualEpisodeIndex


def chunk_episode_text(
    text: str, *, chunk_chars: int = 800, overlap_chars: int = 160
) -> list[str]:
    """Create deterministic overlapping chunks from an EverOS Episode."""
    cleaned = " ".join(text.split())
    if not cleaned:
        raise ValueError("Episode text is empty")
    if chunk_chars < 200:
        raise ValueError("chunk_chars must be at least 200")
    if not 0 <= overlap_chars < chunk_chars:
        raise ValueError("overlap_chars must be smaller than chunk_chars")
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_chars)
        if end < len(cleaned):
            boundary = max(
                cleaned.rfind(marker, start + chunk_chars // 2, end)
                for marker in (". ", "! ", "? ", "。", "！", "？")
            )
            if boundary >= start + chunk_chars // 2:
                end = boundary + 1
        chunk = cleaned[start:end].strip()
        if chunk and (not chunks or chunk != chunks[-1]):
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(start + 1, end - overlap_chars)
    return chunks


def build_text_projection_rows(
    *,
    episode_rows: Sequence[Mapping[str, object]],
    episode_mappings: Sequence[Mapping[str, object]],
    owner_id: str,
    embedding_url: str,
    embedding_model: str,
    chunk_chars: int = 800,
    overlap_chars: int = 160,
    post_json: PostJSON = _default_post_json,
) -> list[dict[str, object]]:
    """Embed chunks derived only from existing EverOS Episode text."""
    document_by_episode = {
        str(row.get("episode_id", "")): str(row.get("document_id", ""))
        for row in episode_mappings
    }
    if len(document_by_episode) != len(episode_mappings) or not all(
        document_by_episode.values()
    ):
        raise ValueError("Episode mapping is incomplete or duplicated")
    output: list[dict[str, object]] = []
    seen_episodes: set[str] = set()
    for episode in sorted(episode_rows, key=lambda row: str(row.get("id", ""))):
        episode_id = str(episode.get("id", ""))
        document_id = document_by_episode.get(episode_id)
        if not document_id:
            continue
        episode_text = str(episode.get("episode", "")).strip()
        seen_episodes.add(episode_id)
        for index, chunk in enumerate(
            chunk_episode_text(
                episode_text,
                chunk_chars=chunk_chars,
                overlap_chars=overlap_chars,
            )
        ):
            vector = embed_query(
                {
                    "query_id": f"text-projection:{episode_id}:{index}",
                    "query_type": "text",
                    "query_text": chunk,
                },
                dataset_parent=Path("."),
                embedding_url=embedding_url,
                embedding_model=embedding_model,
                post_json=post_json,
            )
            output.append(
                {
                    "contract_version": 1,
                    "owner_id": owner_id,
                    "document_id": document_id,
                    "episode_id": episode_id,
                    "episode_text": episode_text,
                    "evidence_ref": f"everos://episode/{episode_id}#chunk-{index}",
                    "evidence_sha256": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    "embedding_model": embedding_model,
                    "chunk_chars": chunk_chars,
                    "overlap_chars": overlap_chars,
                    "vector": vector,
                }
            )
    missing = sorted(set(document_by_episode) - seen_episodes)
    if missing:
        raise ValueError(f"EverOS Episode rows missing from projection: {len(missing)}")
    return output


def build_visual_projection_rows(
    *,
    corpus_rows: Sequence[Mapping[str, object]],
    episode_mappings: Sequence[Mapping[str, object]],
    owner_id: str,
    dataset_parent: Path,
    embedding_url: str,
    embedding_model: str,
    post_json: PostJSON = _default_post_json,
) -> list[dict[str, object]]:
    """Embed one representative evidence frame per EverOS Episode."""
    from .retrieval_everos_ingest import build_episode_message

    mapping = {
        str(row.get("document_id", "")): str(row.get("episode_id", ""))
        for row in episode_mappings
    }
    if len(mapping) != len(episode_mappings) or not all(mapping.values()):
        raise ValueError("Episode mapping is incomplete or contains duplicate documents")
    output: list[dict[str, object]] = []
    for corpus_row in sorted(corpus_rows, key=lambda row: str(row.get("document_id", ""))):
        document_id = str(corpus_row.get("document_id", ""))
        episode_id = mapping.get(document_id)
        if not episode_id:
            raise ValueError(f"missing EverOS Episode mapping for {document_id}")
        evidence_rows = corpus_row.get("visual_evidence_refs")
        if not isinstance(evidence_rows, list) or not evidence_rows:
            evidence_rows = [
                {
                    "ref": corpus_row.get("representative_image_ref"),
                    "sha256": corpus_row.get("representative_image_sha256"),
                }
            ]
        for evidence_index, evidence in enumerate(evidence_rows):
            if not isinstance(evidence, Mapping):
                raise ValueError(f"invalid visual evidence row for {document_id}")
            query = {
                "query_id": f"visual-projection:{document_id}:{evidence_index}",
                "query_type": "image",
                "query_text": "",
                "query_media_ref": evidence.get("ref"),
                "query_media_sha256": evidence.get("sha256"),
            }
            vector = embed_query(
                query,
                dataset_parent=dataset_parent,
                embedding_url=embedding_url,
                embedding_model=embedding_model,
                post_json=post_json,
            )
            output.append(
                {
                    "contract_version": 1,
                    "owner_id": owner_id,
                    "document_id": document_id,
                    "episode_id": episode_id,
                    "episode_text": build_episode_message(dict(corpus_row)),
                    "evidence_ref": evidence.get("ref"),
                    "evidence_sha256": evidence.get("sha256"),
                    "embedding_model": embedding_model,
                    "vector": vector,
                }
            )
    return output


def _reranker_query(
    query: Mapping[str, object], dataset_parent: Path
) -> str | dict[str, object]:
    query_type = str(query.get("query_type", ""))
    text = str(query.get("query_text", "")).strip()
    if query_type not in IMAGE_QUERY_TYPES:
        if not text:
            raise ValueError(f"text query {query.get('query_id', '')} is empty")
        return {"text": text}
    path = _verified_media(query, dataset_parent)
    prompt = (
        text
        if query_type in {"image_text", "image_text_proxy"} and text
        else "Find the personal memory that best matches this egocentric image."
    )
    return {"text": prompt, "image": _data_url(path)}


def build_reranker_payload(
    query: Mapping[str, object],
    candidates: Sequence[RetrievedEpisode],
    dataset_parent: Path,
    model: str,
) -> dict[str, object]:
    if not candidates:
        raise ValueError("reranker needs at least one recalled candidate")
    return {
        "model": model,
        "input": {
            "query": _reranker_query(query, dataset_parent),
            "documents": [
                {"text": candidate.episode_text} for candidate in candidates
            ],
        },
        "parameters": {
            "return_documents": True,
            "top_n": len(candidates),
        },
    }


def rerank_candidates(
    query: Mapping[str, object],
    candidates: Sequence[RetrievedEpisode],
    *,
    dataset_parent: Path,
    reranker_url: str,
    reranker_model: str,
    post_json: PostJSON = _default_post_json,
) -> list[RetrievedEpisode]:
    response = post_json(
        reranker_url,
        build_reranker_payload(query, candidates, dataset_parent, reranker_model),
    )
    output = response.get("output")
    results = (
        output.get("results") if isinstance(output, dict) else None
    ) or response.get("results")
    if not isinstance(results, list):
        raise ValueError("reranker response is missing results")
    indices: list[int] = []
    scores: list[float] = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("reranker result is not an object")
        indices.append(int(result.get("index", -1)))
        scores.append(float(result.get("relevance_score", result.get("score", 0.0))))
    if sorted(indices) != list(range(len(candidates))):
        raise ValueError("reranker must return the exact candidate set")
    return [
        RetrievedEpisode(
            document_id=candidates[index].document_id,
            episode_id=candidates[index].episode_id,
            episode_text=candidates[index].episode_text,
            score=score,
            evidence_ref=candidates[index].evidence_ref,
        )
        for index, score in zip(indices, scores, strict=True)
    ]


def build_visual_reranker_payload(
    query: Mapping[str, object],
    candidates: Sequence[RetrievedEpisode],
    dataset_parent: Path,
    model: str,
) -> dict[str, object]:
    if not candidates or any(not row.evidence_ref for row in candidates):
        raise ValueError("visual reranker requires evidence media for every candidate")
    documents: list[dict[str, object]] = []
    for candidate in candidates:
        path = (dataset_parent / str(candidate.evidence_ref)).resolve()
        try:
            path.relative_to(dataset_parent.resolve())
        except ValueError as exc:
            raise ValueError(f"visual evidence escapes dataset parent: {path}") from exc
        if not path.is_file():
            raise FileNotFoundError(path)
        documents.append(
            {
                "text": (
                    "Candidate personal-memory evidence image. "
                    f"Episode context: {candidate.episode_text[:800]}"
                ),
                "image": _data_url(path),
            }
        )
    return {
        "model": model,
        "input": {
            "query": _reranker_query(query, dataset_parent),
            "documents": documents,
        },
        "parameters": {
            "return_documents": True,
            "top_n": len(candidates),
        },
    }


def rerank_visual_candidates(
    query: Mapping[str, object],
    candidates: Sequence[RetrievedEpisode],
    *,
    dataset_parent: Path,
    reranker_url: str,
    reranker_model: str,
    post_json: PostJSON = _default_post_json,
) -> list[RetrievedEpisode]:
    response = post_json(
        reranker_url,
        build_visual_reranker_payload(
            query, candidates, dataset_parent, reranker_model
        ),
    )
    output = response.get("output")
    results = (
        output.get("results") if isinstance(output, dict) else None
    ) or response.get("results")
    if not isinstance(results, list):
        raise ValueError("visual reranker response is missing results")
    ranked: list[RetrievedEpisode] = []
    indices: list[int] = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("visual reranker result is not an object")
        index = int(result.get("index", -1))
        indices.append(index)
        candidate = candidates[index]
        ranked.append(
            RetrievedEpisode(
                document_id=candidate.document_id,
                episode_id=candidate.episode_id,
                episode_text=candidate.episode_text,
                score=float(result.get("relevance_score", result.get("score", 0.0))),
                evidence_ref=candidate.evidence_ref,
            )
        )
    if sorted(indices) != list(range(len(candidates))):
        raise ValueError("visual reranker must return the exact candidate set")
    return ranked


def fuse_embedding_and_reranker(
    embedding_candidates: Sequence[RetrievedEpisode],
    reranked_candidates: Sequence[RetrievedEpisode],
    *,
    embedding_weight: float = DEFAULT_EMBEDDING_FUSION_WEIGHT,
) -> list[RetrievedEpisode]:
    """Blend recall and reranker scores without changing the recalled set.

    The two models expose scores on different scales, so each score list is
    min-max normalised per query before blending.  Keeping a small amount of
    the embedding score prevents an unstable reranker decision from erasing a
    strong nearest-neighbour match.
    """
    if not 0.0 <= embedding_weight <= 1.0:
        raise ValueError("embedding_weight must be between 0 and 1")
    embedding_by_id = {row.document_id: row for row in embedding_candidates}
    reranked_by_id = {row.document_id: row for row in reranked_candidates}
    if len(embedding_by_id) != len(embedding_candidates) or len(reranked_by_id) != len(
        reranked_candidates
    ):
        raise ValueError("fusion candidates contain duplicate document IDs")
    if set(embedding_by_id) != set(reranked_by_id):
        raise ValueError("fusion requires the exact recalled candidate set")
    if not embedding_candidates:
        return []

    def normalise(rows: Sequence[RetrievedEpisode]) -> dict[str, float]:
        low = min(row.score for row in rows)
        high = max(row.score for row in rows)
        width = high - low
        if width == 0:
            return {row.document_id: 0.0 for row in rows}
        return {row.document_id: (row.score - low) / width for row in rows}

    embedding_scores = normalise(embedding_candidates)
    reranker_scores = normalise(reranked_candidates)
    fused = [
        RetrievedEpisode(
            document_id=row.document_id,
            episode_id=row.episode_id,
            episode_text=row.episode_text,
            score=(
                embedding_weight * embedding_scores[row.document_id]
                + (1.0 - embedding_weight) * reranker_scores[row.document_id]
            ),
            evidence_ref=row.evidence_ref,
        )
        for row in embedding_candidates
    ]
    return sorted(fused, key=lambda row: (-row.score, row.document_id))


def _prediction(
    *,
    query_id: str,
    hits: Sequence[RetrievedEpisode],
    latency_ms: float,
    source: str,
    error: Exception | None = None,
    metadata: Mapping[str, object] | None = None,
    no_answer: bool = False,
) -> dict[str, object]:
    row: dict[str, object] = {
        "contract_version": 1,
        "query_id": query_id,
        "ranked_document_ids": [hit.document_id for hit in hits],
        "scores": [round(hit.score, 8) for hit in hits],
        "no_answer": no_answer,
        "latency_ms": round(max(0.0, latency_ms), 3),
        "prediction_source": source,
    }
    if error is not None:
        row["error_type"] = type(error).__name__
        row["error_message"] = str(error)[:240]
    if metadata:
        row.update(metadata)
    return row


def run_production_queries(
    *,
    queries: Sequence[Mapping[str, object]],
    split: str,
    contract_sha256: str,
    index: Any,
    visual_index: Any | None = None,
    text_projection_index: Any | None = None,
    dataset_parent: Path,
    embedding_url: str,
    embedding_model: str,
    reranker_url: str,
    reranker_model: str,
    post_json: PostJSON = _default_post_json,
    allow_reranker_fallback: bool = False,
    embedding_fusion_weight: float = DEFAULT_EMBEDDING_FUSION_WEIGHT,
    enable_visual_reranker: bool = False,
    visual_reranker_candidate_count: int = 20,
    no_answer_policy: NoAnswerPolicy | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not 1 <= visual_reranker_candidate_count <= 20:
        raise ValueError("visual reranker candidate count must be between 1 and 20")
    owner_id = f"mvp08b1-{contract_sha256[:12]}-{split}"
    embedding_rows: list[dict[str, object]] = []
    reranked_rows: list[dict[str, object]] = []
    for query in sorted(queries, key=lambda row: str(row.get("query_id", ""))):
        query_id = str(query.get("query_id", ""))
        if not query_id:
            raise ValueError("query is missing query_id")
        started = time.perf_counter()
        try:
            vector = embed_query(
                query,
                dataset_parent=dataset_parent,
                embedding_url=embedding_url,
                embedding_model=embedding_model,
                post_json=post_json,
            )
            query_type = str(query.get("query_type", ""))
            if visual_index is not None and query_type in IMAGE_QUERY_TYPES:
                selected_index = visual_index
            elif text_projection_index is not None and query_type not in IMAGE_QUERY_TYPES:
                selected_index = text_projection_index
            else:
                selected_index = index
            hits = selected_index.search(vector, owner_id=owner_id, top_k=20)
        except Exception as exc:
            latency = (time.perf_counter() - started) * 1000
            failed = _prediction(
                query_id=query_id,
                hits=[],
                latency_ms=latency,
                source="embedding_or_everos_index_error",
                error=exc,
            )
            embedding_rows.append(failed)
            reranked_rows.append(dict(failed))
            continue
        embedding_latency = (time.perf_counter() - started) * 1000
        embedding_rows.append(
            _prediction(
                query_id=query_id,
                hits=hits,
                latency_ms=embedding_latency,
                source="qwen3_vl_embedding_2b_everos_episode_index",
            )
        )
        if (
            visual_index is not None
            and str(query.get("query_type", "")) == "image"
            and not enable_visual_reranker
        ):
            reranked_rows.append(
                _prediction(
                    query_id=query_id,
                    hits=hits,
                    latency_ms=embedding_latency,
                    source="qwen3_vl_visual_projection_without_text_rerank",
                )
            )
            continue
        rerank_started = time.perf_counter()
        try:
            if query_type == "image":
                reranker_candidates = hits[:visual_reranker_candidate_count]
                reranked_only = rerank_visual_candidates(
                    query,
                    reranker_candidates,
                    dataset_parent=dataset_parent,
                    reranker_url=reranker_url,
                    reranker_model=reranker_model,
                    post_json=post_json,
                )
            else:
                reranker_candidates = hits
                reranked_only = rerank_candidates(
                    query,
                    hits,
                    dataset_parent=dataset_parent,
                    reranker_url=reranker_url,
                    reranker_model=reranker_model,
                    post_json=post_json,
                )
            reranked = fuse_embedding_and_reranker(
                reranker_candidates,
                reranked_only,
                embedding_weight=embedding_fusion_weight,
            )
            raw_scores = sorted(
                (row.score for row in reranked_only), reverse=True
            )
            confidence = {
                "reranker_top1_score": round(raw_scores[0], 8),
                "reranker_top1_margin": round(
                    raw_scores[0] - raw_scores[1]
                    if len(raw_scores) > 1
                    else raw_scores[0],
                    8,
                ),
            }
            abstain = bool(
                no_answer_policy is not None
                and query_type not in IMAGE_QUERY_TYPES
                and no_answer_policy.should_abstain(
                    top1_score=float(confidence["reranker_top1_score"]),
                    top1_margin=float(confidence["reranker_top1_margin"]),
                )
            )
            reranked_rows.append(
                _prediction(
                    query_id=query_id,
                    hits=reranked,
                    latency_ms=embedding_latency
                    + (time.perf_counter() - rerank_started) * 1000,
                    source=(
                        "qwen3_vl_visual_embedding_visual_reranker_fusion"
                        if query_type == "image"
                        else "qwen3_vl_embedding_15pct_reranker_85pct_fusion"
                    ),
                    metadata={
                        **confidence,
                        "embedding_fusion_weight": embedding_fusion_weight,
                        "reranker_candidate_count": len(reranker_candidates),
                    },
                    no_answer=abstain,
                )
            )
        except Exception as exc:
            if not allow_reranker_fallback:
                reranked_rows.append(
                    _prediction(
                        query_id=query_id,
                        hits=[],
                        latency_ms=embedding_latency
                        + (time.perf_counter() - rerank_started) * 1000,
                        source="reranker_error",
                        error=exc,
                    )
                )
                continue
            reranked_rows.append(
                _prediction(
                    query_id=query_id,
                    hits=hits,
                    latency_ms=embedding_latency
                    + (time.perf_counter() - rerank_started) * 1000,
                    source="reranker_unavailable_embedding_fallback",
                    error=exc,
                )
            )
    return embedding_rows, reranked_rows
