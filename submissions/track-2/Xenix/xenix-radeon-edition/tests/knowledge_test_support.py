from __future__ import annotations

import re

from xenix.exceptions import ValidationError
from xenix.services.knowledge_service import (
    KnowledgeService,
    KnowledgeUnitInput,
    bound_knowledge_units,
    prepare_knowledge_search_text,
)
from xenix.services.knowledge_projection import (
    RETRIEVAL_PROJECTION_VERSION,
    knowledge_unit_id,
    retrieval_content_fingerprint,
)
from xenix.services.storage.models import (
    KnowledgeDocumentRow,
    KnowledgeUnitRow,
    generate_id,
    utc_now,
)
from xenix.services.storage.repositories.knowledge import KnowledgeRepository


def seed_knowledge_text(
    service: KnowledgeService,
    *,
    title: str,
    text: str,
    document_id: str | None = None,
    source_artifact_id: str | None = None,
    library_id: str = "global",
) -> KnowledgeDocumentRow:
    """Seed a retrieval projection for focused tests without adding a product writer."""

    normalized_title = title.strip()
    if not normalized_title:
        raise ValidationError("Knowledge document title is required.")
    passages = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    units = bound_knowledge_units(
        KnowledgeUnitInput(text=part, locator={"passage": index + 1})
        for index, part in enumerate(passages)
    )
    if not units:
        raise ValidationError("Knowledge document must contain searchable text.")

    repository = KnowledgeRepository()
    session_factory = service._session_factory  # noqa: SLF001 - explicit test seam
    with session_factory() as session:
        document = repository.get_document(session, document_id) if document_id else None
        generation_id = generate_id()
        if document is None:
            document = repository.create_document(
                session,
                KnowledgeDocumentRow(
                    id=document_id or generate_id(),
                    library_id=library_id,
                    title=normalized_title,
                    source_artifact_id=source_artifact_id,
                    canonical_generation_id=generation_id,
                    retrieval_generation_id=generation_id,
                    retrieval_status="ready",
                ),
            )
        else:
            document.title = normalized_title
            document.source_artifact_id = source_artifact_id
            document.canonical_generation_id = generation_id
            document.retrieval_generation_id = generation_id
            document.retrieval_status = "ready"
            document.active = True
            document.updated_at = utc_now()
            session.add(document)

        rows = [
            KnowledgeUnitRow(
                id=knowledge_unit_id(
                    document_id=document.id,
                    canonical_generation_id=generation_id,
                    ordinal=ordinal,
                ),
                document_id=document.id,
                canonical_generation_id=generation_id,
                ordinal=ordinal,
                text=unit.text,
                search_text=prepare_knowledge_search_text(unit.text),
                locator_payload=dict(unit.locator),
            )
            for ordinal, unit in enumerate(units)
        ]
        repository.replace_units(session, document=document, units=rows)
        document.retrieval_projection_version = RETRIEVAL_PROJECTION_VERSION
        document.retrieval_content_fingerprint = retrieval_content_fingerprint(
            (row.ordinal, row.text, row.locator_payload) for row in rows
        )
        document.retrieval_unit_count = len(rows)
        session.add(document)
        session.commit()
        session.refresh(document)
        return document
