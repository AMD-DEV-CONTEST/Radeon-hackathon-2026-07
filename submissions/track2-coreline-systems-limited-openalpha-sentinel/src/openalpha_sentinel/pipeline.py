from __future__ import annotations

from pathlib import Path

from .chunking import chunk_document
from .config import Settings
from .database import Database
from .embeddings import HashEmbedding
from .extractor import RuleBasedExtractor
from .schemas import FetchedArtifact, PipelineResult
from .utils import normalize_text, sha256_text, stable_json


class IngestionPipeline:
    STAGES = (
        "FETCHING",
        "NORMALIZING",
        "LICENSE_CHECKING",
        "DEDUPLICATING",
        "EXTRACTING",
        "INDEXING",
        "NOTIFYING",
    )

    def __init__(
        self,
        settings: Settings,
        database: Database,
        extractor: RuleBasedExtractor | None = None,
        embedding: HashEmbedding | None = None,
    ):
        self.settings = settings
        self.database = database
        self.extractor = extractor or RuleBasedExtractor()
        self.embedding = embedding or HashEmbedding()

    def process(self, artifacts: list[FetchedArtifact], kind: str = "manual") -> PipelineResult:
        job_id = self.database.create_job(kind, {"artifact_count": len(artifacts)})
        created_cards = 0
        skipped = 0
        processed = 0
        errors: list[str] = []
        self.database.update_job(job_id, stage="FETCHING", detail=f"Received {len(artifacts)} artifacts")

        for index, artifact in enumerate(artifacts):
            revision_id: str | None = None
            revision_created = False
            try:
                self.database.update_job(
                    job_id,
                    stage="NORMALIZING",
                    checkpoint={"artifact_index": index, "canonical_url": artifact.canonical_url},
                )
                normalized_documents = []
                total_bytes = 0
                for document in artifact.documents:
                    text = normalize_text(document.text)
                    total_bytes += len(text.encode("utf-8"))
                    if total_bytes > self.settings.max_document_bytes:
                        raise ValueError(
                            f"Source exceeds OPENALPHA_MAX_DOCUMENT_BYTES ({self.settings.max_document_bytes})"
                        )
                    normalized_documents.append(document.model_copy(update={"text": text}))
                if not normalized_documents:
                    raise ValueError("Source did not contain an ingestible document")

                artifact = artifact.model_copy(update={"documents": normalized_documents})
                source_id = self.database.upsert_source(artifact)
                content_digest = sha256_text(
                    stable_json([(document.path, document.text) for document in normalized_documents])
                )
                self.database.update_job(job_id, stage="DEDUPLICATING")
                revision_id, revision_created = self.database.create_revision(
                    source_id, artifact, content_digest
                )
                if not revision_created:
                    skipped += 1
                    processed += 1
                    continue

                self._cache_raw(content_digest, artifact)
                all_chunks = []
                chunk_source_urls: dict[str, str] = {}
                self.database.update_job(job_id, stage="EXTRACTING")
                for document in normalized_documents:
                    document_hash = sha256_text(document.text)
                    document_id = self.database.store_document(
                        revision_id=revision_id,
                        path=document.path,
                        title=document.title,
                        content_type=document.content_type,
                        source_url=document.source_url,
                        text=document.text,
                        content_sha256=document_hash,
                    )
                    chunks = chunk_document(
                        document.text,
                        document_id,
                        revision_id,
                        line_offset=document.line_offset,
                    )
                    self.database.store_chunks(document.title, chunks)
                    all_chunks.extend(chunks)
                    evidence_url = document.source_url or artifact.immutable_url
                    chunk_source_urls.update({chunk.id: evidence_url for chunk in chunks})

                card = self.extractor.extract(
                    artifact,
                    source_id,
                    revision_id,
                    all_chunks,
                    chunk_source_urls=chunk_source_urls,
                )
                stored_card = self.database.save_card(card)
                self.database.update_job(job_id, stage="INDEXING")
                vectors = self.embedding.embed_many([chunk.text for chunk in all_chunks])
                for chunk, vector in zip(all_chunks, vectors):
                    self.database.save_embedding(chunk.id, self.embedding.model_id, vector)

                self.database.update_job(job_id, stage="NOTIFYING")
                self.database.add_notification(
                    "strategy_added",
                    f"New strategy: {stored_card.title}",
                    f"Indexed revision {artifact.revision_key} from {artifact.canonical_url}",
                    source_id,
                )
                created_cards += 1
                processed += 1
            except Exception as exc:  # A partial source failure must not stop the watch job.
                error = f"{artifact.canonical_url}: {exc}"
                if revision_created and revision_id is not None:
                    try:
                        self.database.delete_revision(revision_id)
                    except Exception as cleanup_exc:
                        error = f"{error} (incomplete revision cleanup failed: {cleanup_exc})"
                errors.append(error)

        state = "COMPLETED" if not errors else ("PARTIAL_SUCCESS" if processed else "FAILED")
        self.database.update_job(
            job_id,
            state=state,
            stage=state,
            items_processed=processed,
            error="\n".join(errors) if errors else None,
            detail=f"created={created_cards}, skipped={skipped}, errors={len(errors)}",
        )
        return PipelineResult(
            job_id=job_id,
            state=state,
            processed=processed,
            created_cards=created_cards,
            skipped_revisions=skipped,
            errors=errors,
        )

    def _cache_raw(self, digest: str, artifact: FetchedArtifact) -> Path:
        raw_dir = self.settings.data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        target = raw_dir / f"{digest}.json"
        if not target.exists():
            target.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return target
