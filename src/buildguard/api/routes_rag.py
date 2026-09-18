"""Local RAG API routes."""

import hashlib
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from buildguard.rag.advanced.answer_grounding import AnswerGrounder
from buildguard.rag.advanced.corrective_retriever import AdvancedRagPipeline
from buildguard.rag.schemas import RagSearchInput
from buildguard.rag.service import RagService
from buildguard.security.path_guard import PathGuard


class RagIngestRequest(BaseModel):
    source_path: Path
    project: str | None = None


class GroundAnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=100_000)
    chunk_ids: list[str] = Field(default_factory=list, max_length=100)


class RagRemoveRequest(BaseModel):
    source_path: Path


SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024


def _safe_document_name(value: str) -> str:
    name = Path(value).name
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(name).stem).strip(".-")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise ValueError(f"Unsupported document extension: {suffix}")
    return f"{stem[:120] or 'document'}{suffix}"


def create_rag_router(
    service: RagService,
    source_roots: list[Path],
    advanced: AdvancedRagPipeline | None = None,
    grounder: AnswerGrounder | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/rag", tags=["rag"])
    guard = PathGuard(source_roots, source_roots)

    @router.get("/status")
    def status() -> dict[str, object]:
        return {
            **service.status().model_dump(mode="json"),
            "validation": service.validate_index(),
        }

    @router.get("/documents")
    def documents() -> list[dict[str, object]]:
        return [
            {"source_path": path, **metadata}
            for path, metadata in sorted(service.documents.items())
        ]

    @router.get("/chunks")
    def chunks(
        source_path: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, object]:
        candidates = service.bm25.chunks
        if source_path is not None:
            candidates = [item for item in candidates if str(item.source_path) == source_path]
        selected = candidates[offset : offset + limit]
        return {
            "total": len(candidates),
            "offset": offset,
            "chunks": [item.model_dump(mode="json") for item in selected],
        }

    @router.post("/rebuild")
    def rebuild() -> dict[str, object]:
        return service.rebuild()

    @router.delete("/documents")
    def remove_document(
        request: RagRemoveRequest,
        confirmed: bool = False,
    ) -> dict[str, object]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Removing an indexed document requires explicit confirmation",
            )
        try:
            source = guard.resolve_read(request.source_path)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return service.remove(source).model_dump(mode="json")

    @router.post("/documents/upload")
    async def upload_documents(
        files: Annotated[list[UploadFile], File()],
        project: str | None = None,
    ) -> list[dict[str, object]]:
        if not files or len(files) > 100:
            raise HTTPException(status_code=422, detail="Upload 1..100 documents")
        upload_root = (source_roots[0] / "uploads").resolve()
        upload_root.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, object]] = []
        for upload in files:
            try:
                safe_name = _safe_document_name(upload.filename or "document")
            except ValueError as exc:
                raise HTTPException(status_code=415, detail=str(exc)) from exc
            content = await upload.read(MAX_DOCUMENT_BYTES + 1)
            if len(content) > MAX_DOCUMENT_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Document exceeds {MAX_DOCUMENT_BYTES} bytes",
                )
            digest = hashlib.sha256(content).hexdigest()
            requested_target = upload_root / f"{digest[:16]}-{safe_name}"
            if requested_target.exists():
                target = guard.resolve_read(requested_target)
            else:
                target = guard.resolve_write(
                    requested_target,
                    root=source_roots[0],
                    overwrite_confirmed=False,
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".tmp")
                try:
                    temporary.write_bytes(content)
                    temporary.replace(target)
                finally:
                    if temporary.exists():
                        temporary.unlink()
            indexed = service.ingest(target, project)
            results.append(indexed.model_dump(mode="json"))
        return results

    @router.post("/search")
    def search(request: RagSearchInput) -> dict[str, object]:
        return service.search(request).model_dump(mode="json")

    @router.post("/ingest")
    def ingest(request: RagIngestRequest) -> list[dict[str, object]]:
        try:
            source = guard.resolve_read(request.source_path)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        results = service.ingest_path(source, request.project)
        return [result.model_dump(mode="json") for result in results]

    @router.post("/advanced-search")
    def advanced_search(request: RagSearchInput) -> dict[str, object]:
        if advanced is None:
            raise HTTPException(status_code=503, detail="Advanced RAG is unavailable")
        return advanced.retrieve(request).model_dump(mode="json")

    @router.post("/ground-answer")
    def ground_answer(request: GroundAnswerRequest) -> dict[str, object]:
        if grounder is None:
            raise HTTPException(status_code=503, detail="Answer grounding is unavailable")
        available = {chunk.chunk_id: chunk for chunk in service.bm25.chunks}
        unknown = set(request.chunk_ids) - set(available)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown local RAG chunk IDs: {sorted(unknown)}",
            )
        chunks = [available[chunk_id] for chunk_id in request.chunk_ids]
        return grounder.validate(request.answer, chunks).model_dump(mode="json")

    return router
