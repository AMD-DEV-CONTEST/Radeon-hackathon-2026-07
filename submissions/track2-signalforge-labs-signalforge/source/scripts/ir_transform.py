#!/usr/bin/env python3
"""Transform private IR artifacts into citation chunks and silent projections."""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
from typing import Any, Iterable


CHUNK_VERSION = "ir-section-aware/v1"
PROJECTION_VERSION = "ir-numerical-silence/v3"
SPACE = re.compile(r"\s+")
BOILERPLATE = {
    "back to top",
    "skip to main content",
    "learn more",
    "read more",
    "view all",
    "download",
}
BOILERPLATE_PATTERN = re.compile(
    r"^(?:for more information,?\s+(?:financial analysts|investors|media|press)|note to editors?:|"
    r"your privacy choices|copyright\b|all rights reserved\b|sign up for (?:email|investor))",
    re.IGNORECASE,
)
EXCLUDED_SECTION_PATTERN = re.compile(
    r"(?:stock price|investment calculator|cost basis|email alerts?|contact investor relations)",
    re.IGNORECASE,
)
FINANCIAL_LITERAL = re.compile(
    r"(?<![A-Za-z0-9_])-?\d{1,3}(?:\.\d+)?\s+(?:to|through|[-–—])\s+-?\d{1,3}(?:\.\d+)?"
    r"(?=\s+(?:in\s+constant\s+currency|percent(?:age)?|bps?\b|million\b|billion\b|trillion\b))"
    r"|(?:[$€£]\s*)-?\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:million|billion|trillion|(?-i:[MBTK])))?"
    r"|(?<![A-Za-z0-9_])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?:\s*(?:%|bps?|million|billion|trillion|(?-i:[MBTK])))?"
    r"|(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?\s*(?:%|bps?|million|billion|trillion|(?-i:[MBTKxX]))",
    re.IGNORECASE,
)


class NarrativeHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str, str]] = []
        self.section = "Document"
        self._capture = ""
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth == 0 and lowered in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"}:
            self._capture = lowered
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0 and self._capture and data.strip():
            self._parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg", "nav", "footer"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth or lowered != self._capture:
            return
        text = SPACE.sub(" ", " ".join(self._parts)).strip()
        if text and text.lower() not in BOILERPLATE and not BOILERPLATE_PATTERN.search(text):
            if lowered.startswith("h"):
                self.section = text[:300]
            elif len(text) >= 30 and not EXCLUDED_SECTION_PATTERN.search(self.section):
                kind = "table_cell" if lowered in {"td", "th"} else "paragraph"
                self.blocks.append((self.section, text, kind))
        self._capture = ""
        self._parts = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--raw-store", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-chars", type=int, default=1800)
    parser.add_argument("--overlap-chars", type=int, default=180)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def extract_html(payload: bytes) -> list[tuple[str, str, str, int]]:
    parser = NarrativeHTMLParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    counters: dict[str, int] = {}
    result: list[tuple[str, str, str, int]] = []
    for section, text, kind in parser.blocks:
        counters[kind] = counters.get(kind, 0) + 1
        result.append((section, text, f"html:{kind}={counters[kind]}", 0))
    return result


def extract_pdf(payload: bytes) -> list[tuple[str, str, str, int]]:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as error:
        raise RuntimeError("pypdf_not_installed") from error
    reader = PdfReader(io.BytesIO(payload), strict=False)
    blocks: list[tuple[str, str, str, int]] = []
    for page_number, page in enumerate(reader.pages, 1):
        text = SPACE.sub(" ", page.extract_text() or "").strip()
        if text:
            blocks.append((f"Page {page_number}", text, f"pdf:page={page_number}", page_number))
    return blocks


def extract_text(payload: bytes) -> list[tuple[str, str, str, int]]:
    text = payload.decode("utf-8", errors="replace")
    paragraphs = [SPACE.sub(" ", item).strip() for item in re.split(r"\n\s*\n+", text)]
    result: list[tuple[str, str, str, int]] = []
    section = "Document"
    speaker = re.compile(r"^([A-Z][A-Za-z .'-]{2,80})\s+(?:--|—|-)\s+([A-Za-z][A-Za-z &/'-]{2,100})$")
    for index, paragraph in enumerate(paragraphs, 1):
        if not paragraph:
            continue
        match = speaker.match(paragraph)
        if match:
            section = f"Speaker: {match.group(1)} | Role: {match.group(2)}"
            continue
        if len(paragraph) >= 30:
            result.append((section, paragraph, f"text:paragraph={index}", 0))
    return result


def extract_json(payload: bytes) -> list[tuple[str, str, str, int]]:
    value = json.loads(payload.decode("utf-8"))
    result: list[tuple[str, str, str, int]] = []
    stack: list[tuple[str, Any]] = [("$", value)]
    visited = 0
    while stack:
        path, item = stack.pop()
        visited += 1
        if visited > 100_000:
            raise RuntimeError("json_node_limit_exceeded")
        if isinstance(item, dict):
            for key in reversed(sorted(item)):
                stack.append((f"{path}.{key}", item[key]))
        elif isinstance(item, list):
            for index in range(len(item) - 1, -1, -1):
                stack.append((f"{path}[{index}]", item[index]))
        elif isinstance(item, str):
            text = SPACE.sub(" ", item).strip()
            if len(text) >= 30:
                section = path.rsplit(".", 1)[-1].replace("_", " ").title()
                result.append((section, text, f"json:path={path}", 0))
    return result


def chunk_blocks(
    blocks: list[tuple[str, str, str, int]],
    max_chars: int,
    overlap_chars: int,
) -> list[tuple[str, str, str, int]]:
    chunks: list[tuple[str, str, str, int]] = []
    for section, text, locator, page in blocks:
        cursor = 0
        part = 1
        while cursor < len(text):
            end = min(len(text), cursor + max_chars)
            if end < len(text):
                boundary = text.rfind(" ", cursor + max_chars // 2, end)
                if boundary > cursor:
                    end = boundary
            value = text[cursor:end].strip()
            if value:
                chunks.append((section, value, f"{locator}:part={part}", page))
            if end >= len(text):
                break
            cursor = max(cursor + 1, end - overlap_chars)
            part += 1
    return chunks


def silent_projection(text: str) -> tuple[str, list[str]]:
    references: list[str] = []

    def replace(match: re.Match[str]) -> str:
        reference = f"FINANCIAL_VALUE_{len(references) + 1:03d}"
        references.append(reference)
        return f"[{reference}]"

    projected = text
    while FINANCIAL_LITERAL.search(projected):
        projected = FINANCIAL_LITERAL.sub(replace, projected)
    return projected, references


def transform_document(
    document: dict[str, Any],
    raw_store: Path,
    max_chars: int,
    overlap_chars: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    digest = document["content_sha256"]
    raw_path = raw_store / "sha256" / digest[:2] / digest
    payload = raw_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise RuntimeError("raw_hash_mismatch")
    media_type = document["media_type"]
    if media_type == "text/html":
        blocks = extract_html(payload)
    elif media_type == "application/pdf":
        blocks = extract_pdf(payload)
    elif media_type == "text/plain":
        blocks = extract_text(payload)
    elif media_type == "application/json":
        blocks = extract_json(payload)
    else:
        raise RuntimeError("unsupported_media_type")
    chunks: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []
    for index, (section, text, locator, page) in enumerate(chunk_blocks(blocks, max_chars, overlap_chars), 1):
        content_sha = hashlib.sha256(text.encode()).hexdigest()
        chunk_id = f"{document['document_id']}-chunk-{index:05d}-{content_sha[:10]}"
        available_at = document["available_at"]
        chunk = {
            "schema_version": "signalforge/evidence-chunk/v1",
            "chunk_id": chunk_id,
            "document_id": document["document_id"],
            "company_id": document["company_id"],
            "evidence_type": "investor_relations",
            "document_type": document["document_type"],
            "authority_tier": document["authority_tier"],
            "issuer": document["issuer"],
            "language": document["language"],
            "rights_class": document["rights_class"],
            "audited": document["audited"],
            "filed_with_sec": document["filed_with_sec"],
            "forward_looking": document["forward_looking"],
            "promotional": document["promotional"],
            "published_at": document.get("published_at", available_at),
            "section": section,
            "locator": locator,
            "text": text,
            "source_uri": document["source_uri"],
            "document_sha256": digest,
            "content_sha256": content_sha,
            "available_at": available_at,
            "retrieved_at": document["retrieved_at"],
            "token_estimate": max(1, len(text) // 4 + 1),
            "chunking_version": CHUNK_VERSION,
        }
        if page:
            chunk["page"] = page
        projection_text, references = silent_projection(text)
        projection_sha = hashlib.sha256(projection_text.encode()).hexdigest()
        projection = {
            "schema_version": "signalforge/ir-semantic-projection/v1",
            "projection_id": f"projection-{chunk_id}",
            "chunk_id": chunk_id,
            "document_id": document["document_id"],
            "company_id": document["company_id"],
            "text": projection_text,
            "source_content_sha256": content_sha,
            "projection_sha256": projection_sha,
            "projection_version": PROJECTION_VERSION,
            "numeric_span_count": len(references),
            "numeric_references": references,
        }
        chunks.append(chunk)
        projections.append(projection)
    return chunks, projections


def main() -> int:
    args = parse_args()
    if args.max_chars < 500 or args.overlap_chars < 0 or args.overlap_chars >= args.max_chars // 2:
        raise SystemExit("invalid chunk size or overlap")
    documents = read_jsonl(args.documents)
    chunks: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for document in documents:
        try:
            document_chunks, document_projections = transform_document(
                document, args.raw_store, args.max_chars, args.overlap_chars
            )
            chunks.extend(document_chunks)
            projections.extend(document_projections)
        except Exception as error:
            failures.append({"document_id": document["document_id"], "failure_class": str(error)})
    write_jsonl(args.output_dir / "chunks.jsonl", chunks)
    write_jsonl(args.output_dir / "semantic-projections.jsonl", projections)
    report = {
        "schema_version": "signalforge/ir-transform-run/v1",
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "projection_count": len(projections),
        "numeric_span_count": sum(item["numeric_span_count"] for item in projections),
        "failure_count": len(failures),
        "failures": failures,
        "claim_boundary": "Projections are retrieval-only. Exact text and deterministic financial sources remain authoritative.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "transform-summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("document_count", "chunk_count", "projection_count", "failure_count")}, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
