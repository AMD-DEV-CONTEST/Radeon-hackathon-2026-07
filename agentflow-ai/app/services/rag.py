from __future__ import annotations

from dataclasses import dataclass
import mimetypes
from pathlib import Path
import re
import uuid
from typing import Any

import chromadb
from chromadb.config import Settings
from pypdf import PdfReader

from app.config import AppConfig
from app.services.embeddings import LocalEmbeddingEngine
from app.services.storage import SQLiteStorage


@dataclass(slots=True)
class ParsedDocument:
    document_id: str
    filename: str
    mime_type: str
    page_count: int
    text: str
    chunks: list[dict[str, Any]]
    saved_path: Path


class ChromaRAGService:
    def __init__(self, config: AppConfig, storage: SQLiteStorage, embeddings: LocalEmbeddingEngine) -> None:
        self.config = config
        self.storage = storage
        self.embeddings = embeddings
        self.client = chromadb.PersistentClient(
            path=str(config.chroma_dir),
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        self.collection = self.client.get_or_create_collection(name="agentflow_documents")

    def ingest_file(self, source_path: Path, original_filename: str) -> ParsedDocument:
        mime_type, _ = mimetypes.guess_type(original_filename)
        mime_type = mime_type or "application/octet-stream"

        if original_filename.lower().endswith(".pdf"):
            page_texts = self._extract_pdf(source_path)
        elif original_filename.lower().endswith((".txt", ".md")):
            text = source_path.read_text(encoding="utf-8", errors="ignore")
            page_texts = [(1, text)]
        else:
            raise ValueError("Unsupported file type. Upload PDF, TXT, or MD files only.")

        document_id = str(uuid.uuid4())
        filename = Path(original_filename).name
        full_text = "\n\n".join(text for _, text in page_texts).strip()
        chunks = self._chunk_pages(page_texts, document_id=document_id, filename=filename)

        for chunk in chunks:
            self.collection.upsert(
                ids=[chunk["id"]],
                documents=[chunk["content"]],
                embeddings=[self.embeddings.embed(chunk["content"])],
                metadatas=[chunk["metadata"]],
            )

        self.storage.add_document(
            document_id=document_id,
            filename=filename,
            path=str(source_path),
            mime_type=mime_type,
            page_count=len(page_texts),
            chunk_count=len(chunks),
        )

        return ParsedDocument(
            document_id=document_id,
            filename=filename,
            mime_type=mime_type,
            page_count=len(page_texts),
            text=full_text,
            chunks=chunks,
            saved_path=source_path,
        )

    def query(self, query: str, *, document_ids: list[str] | None = None, top_k: int | None = None) -> list[dict[str, Any]]:
        filters = None
        if document_ids:
            filters = {"document_id": {"$in": document_ids}}

        results = self.collection.query(
            query_embeddings=[self.embeddings.embed(query)],
            n_results=top_k or self.config.rag_top_k,
            where=filters,
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        payload = []

        for document, metadata, distance in zip(documents, metadatas, distances, strict=False):
            payload.append(
                {
                    "content": document,
                    "metadata": metadata,
                    "distance": float(distance),
                }
            )
        return payload

    def list_documents(self) -> list[dict[str, Any]]:
        return self.storage.list_documents()

    @staticmethod
    def _extract_pdf(path: Path) -> list[tuple[int, str]]:
        reader = PdfReader(str(path))
        pages: list[tuple[int, str]] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append((index, text.strip()))
        return pages or [(1, "")]

    def _chunk_pages(self, page_texts: list[tuple[int, str]], *, document_id: str, filename: str) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        chunk_size = self.config.rag_chunk_size
        overlap = self.config.rag_chunk_overlap

        for page_number, text in page_texts:
            cleaned = self._clean_text(text)
            if not cleaned:
                continue
            start = 0
            while start < len(cleaned):
                end = min(len(cleaned), start + chunk_size)
                content = cleaned[start:end]
                chunk_id = str(uuid.uuid4())
                chunks.append(
                    {
                        "id": chunk_id,
                        "content": content,
                        "metadata": {
                            "document_id": document_id,
                            "filename": filename,
                            "page": page_number,
                            "start": start,
                            "end": end,
                        },
                    }
                )
                if end >= len(cleaned):
                    break
                start = max(0, end - overlap)

        if not chunks:
            chunks.append(
                {
                    "id": str(uuid.uuid4()),
                    "content": "Document uploaded successfully, but no text could be extracted.",
                    "metadata": {
                        "document_id": document_id,
                        "filename": filename,
                        "page": 1,
                        "start": 0,
                        "end": 0,
                    },
                }
            )
        return chunks

    @staticmethod
    def _clean_text(text: str) -> str:
        text = text.replace("\x00", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()
