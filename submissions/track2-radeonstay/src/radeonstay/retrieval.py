"""Offline hotel-policy retrieval with a small BM25 index.

The module deliberately uses only the Python standard library.  It performs no
network access and keeps both the policy corpus and the index in process.
Markdown headings are preserved so every result can be cited as a document,
section and source file rather than as an untraceable text fragment.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*|[\u3400-\u9fff]+")
_MARKDOWN_RE = re.compile(r"[`*_>\[\]()]|!\[[^]]*\]\([^)]*\)|\[[^]]+\]\([^)]*\)")


def _absolute_lexical_path(path: str | Path) -> Path:
    """Return an absolute path without resolving symbolic links."""

    return Path(os.path.abspath(Path(path).expanduser()))


def validate_policy_directory(
    policy_dir: str | Path,
    *,
    project_root: str | Path | None = None,
) -> Path:
    """Resolve a real policy tree and reject links in its root and descendants.

    Official evidence passes ``project_root`` so a checked-in ``data`` or
    ``data/policies`` parent link also cannot redirect the authoritative corpus.
    """

    lexical_root = _absolute_lexical_path(policy_dir)
    if lexical_root.is_symlink():
        raise ValueError(
            f"Policy directory must not be a symbolic link: {lexical_root}"
        )
    if not lexical_root.is_dir():
        raise FileNotFoundError(f"Policy directory does not exist: {lexical_root}")

    resolved_project: Path | None = None
    if project_root is not None:
        lexical_project = _absolute_lexical_path(project_root)
        if lexical_project.is_symlink():
            raise ValueError(
                f"Project root must not be a symbolic link: {lexical_project}"
            )
        if not lexical_project.is_dir():
            raise FileNotFoundError(f"Project root does not exist: {lexical_project}")
        try:
            relative_root = lexical_root.relative_to(lexical_project)
        except ValueError as exc:
            raise ValueError(
                "Policy directory must be located within the project root"
            ) from exc
        current = lexical_project
        for component in relative_root.parts:
            current /= component
            if current.is_symlink():
                raise ValueError(
                    f"Policy path component must not be a symbolic link: {current}"
                )
        resolved_project = lexical_project.resolve(strict=True)

    resolved_root = lexical_root.resolve(strict=True)
    if resolved_project is not None:
        try:
            resolved_root.relative_to(resolved_project)
        except ValueError as exc:
            raise ValueError("Resolved policy directory escapes the project root") from exc

    for path in sorted(resolved_root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ValueError(f"Policy tree must not contain symbolic links: {path}")
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"Policy path escapes the policy directory: {path}") from exc
    return resolved_root


def _policy_document_paths(root: Path) -> list[Path]:
    paths = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".md", ".txt"}
        ),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    if not paths:
        raise ValueError(f"No .md or .txt policy documents found in: {root}")
    return paths


def tokenize(text: str) -> list[str]:
    """Tokenize English and Chinese policy text deterministically.

    English terms are lower-cased.  Chinese runs produce individual characters
    and character bigrams, which gives useful lexical retrieval without a word
    segmentation dependency.
    """

    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        value = match.group(0)
        if "\u3400" <= value[0] <= "\u9fff":
            chars = list(value)
            tokens.extend(chars)
            tokens.extend("".join(chars[index : index + 2]) for index in range(len(chars) - 1))
        else:
            tokens.append(value)
    return tokens


@dataclass(frozen=True, slots=True)
class PolicyChunk:
    """A citation-addressable paragraph from one policy document."""

    document: str
    section: str
    text: str
    source_path: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A ranked result suitable for UI rendering and grounded prompting."""

    document: str
    section: str
    snippet: str
    score: float
    context: str
    matched_text: str
    source_path: str

    @property
    def citation(self) -> str:
        return f"[{self.document} > {self.section}]"

    @property
    def citation_context(self) -> str:
        """Alias used by prompt builders that request citation context."""

        return self.context

    def to_citation(self, *, include_context: bool = True) -> dict[str, str | float]:
        body = self.context if include_context else self.snippet
        return {
            "document": self.document,
            "section": self.section,
            "excerpt": body,
            "score": self.score,
            "source_path": self.source_path,
        }

    def to_evidence_citation(self) -> dict[str, str | float]:
        """Return the complete matched paragraph without adjacent context."""
        return {
            "document": self.document,
            "section": self.section,
            "excerpt": self.matched_text,
            "score": self.score,
            "source_path": self.source_path,
        }

    def as_dict(self) -> dict[str, str | float]:
        return {
            "document": self.document,
            "section": self.section,
            "snippet": self.snippet,
            "score": self.score,
            "context": self.context,
            "matched_text": self.matched_text,
            "source_path": self.source_path,
            "citation": self.citation,
        }


def _plain_text(value: str) -> str:
    value = _MARKDOWN_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


def _split_long_paragraph(text: str, limit: int = 720) -> Iterator[str]:
    if len(text) <= limit:
        yield text
        return

    sentences = re.split(r"(?<=[。！？.!?；;])\s*", text)
    buffer = ""
    for sentence in sentences:
        if not sentence:
            continue
        if buffer and len(buffer) + len(sentence) > limit:
            yield buffer.strip()
            buffer = ""
        while len(sentence) > limit:
            yield sentence[:limit].strip()
            sentence = sentence[limit:]
        buffer += sentence
    if buffer.strip():
        yield buffer.strip()


def parse_policy_file(path: str | Path, *, root: str | Path | None = None) -> list[PolicyChunk]:
    """Parse a UTF-8 Markdown or text policy into section-aware chunks."""

    policy_path = Path(path)
    text = policy_path.read_text(encoding="utf-8")
    document = policy_path.stem.replace("-", " ").replace("_", " ").strip()
    section = "正文"
    paragraphs: list[tuple[str, str]] = []
    pending: list[str] = []

    def flush() -> None:
        if not pending:
            return
        paragraph = _plain_text(" ".join(pending))
        pending.clear()
        if paragraph:
            paragraphs.append((section, paragraph))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            title = _plain_text(heading.group(2))
            if level == 1:
                document = title or document
            else:
                section = title or "正文"
            continue
        if not line:
            flush()
            continue
        if line.startswith("---"):
            flush()
            continue
        pending.append(line.lstrip("- "))
    flush()

    try:
        source_path = str(policy_path.relative_to(Path(root))) if root else str(policy_path)
    except ValueError:
        source_path = str(policy_path)

    chunks: list[PolicyChunk] = []
    for current_section, paragraph in paragraphs:
        for piece in _split_long_paragraph(paragraph):
            chunks.append(
                PolicyChunk(
                    document=document,
                    section=current_section,
                    text=piece,
                    source_path=source_path,
                    ordinal=len(chunks),
                )
            )
    return chunks


def load_policy_documents(
    policy_dir: str | Path,
    *,
    project_root: str | Path | None = None,
) -> list[PolicyChunk]:
    """Load all Markdown/text policies below ``policy_dir`` in stable order."""

    root = validate_policy_directory(policy_dir, project_root=project_root)
    paths = _policy_document_paths(root)
    chunks: list[PolicyChunk] = []
    for path in paths:
        chunks.extend(parse_policy_file(path, root=root))
    if not chunks:
        raise ValueError(f"Policy documents contain no retrievable text: {root}")
    return chunks


def policy_corpus_sha256(
    policy_dir: str | Path,
    *,
    project_root: str | Path | None = None,
) -> str:
    """Hash the in-repository policy corpus with stable relative-path framing."""

    root = validate_policy_directory(policy_dir, project_root=project_root)
    paths = _policy_document_paths(root)
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


class PolicyRetriever:
    """In-memory BM25 retriever for local policy documents."""

    def __init__(self, chunks_or_directory: Sequence[PolicyChunk] | str | Path) -> None:
        if isinstance(chunks_or_directory, (str, Path)):
            chunks = load_policy_documents(chunks_or_directory)
        else:
            chunks = list(chunks_or_directory)
        if not chunks:
            raise ValueError("PolicyRetriever requires at least one policy chunk")

        self._chunks = tuple(chunks)
        self._term_counts: list[Counter[str]] = []
        self._lengths: list[int] = []
        document_frequency: Counter[str] = Counter()

        for chunk in self._chunks:
            # Repeating metadata tokens gives document/section matches modestly
            # more influence while retaining ordinary BM25 scoring.
            tokens = tokenize(chunk.text)
            tokens.extend(tokenize(chunk.document) * 2)
            tokens.extend(tokenize(chunk.section) * 3)
            counts = Counter(tokens)
            self._term_counts.append(counts)
            self._lengths.append(sum(counts.values()))
            document_frequency.update(counts.keys())

        total = len(self._chunks)
        self._idf = {
            term: math.log(1.0 + (total - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }
        self._average_length = sum(self._lengths) / total

    @classmethod
    def from_directory(
        cls,
        policy_dir: str | Path,
        *,
        project_root: str | Path | None = None,
    ) -> "PolicyRetriever":
        return cls(load_policy_documents(policy_dir, project_root=project_root))

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        context_chars: int = 220,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        """Return ranked document/section/snippet results for ``query``.

        ``context`` includes adjacent paragraphs from the same section when
        available, making the result safe to pass to a grounded answer prompt.
        Empty or punctuation-only queries return an empty list.
        """

        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        if context_chars < 0:
            raise ValueError("context_chars cannot be negative")

        query_tokens = list(dict.fromkeys(tokenize(query)))
        if not query_tokens:
            return []

        k1 = 1.5
        b = 0.75
        normalized_query = re.sub(r"\s+", "", query.lower())
        scored: list[tuple[float, int]] = []
        for index, (counts, length) in enumerate(
            zip(self._term_counts, self._lengths, strict=True)
        ):
            score = 0.0
            length_factor = 1.0 - b + b * length / self._average_length
            for term in query_tokens:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                score += self._idf.get(term, 0.0) * (
                    frequency * (k1 + 1.0) / (frequency + k1 * length_factor)
                )

            chunk = self._chunks[index]
            searchable = re.sub(
                r"\s+", "", f"{chunk.document}{chunk.section}{chunk.text}".lower()
            )
            if len(normalized_query) >= 2 and normalized_query in searchable:
                score += 1.25
            if score > min_score:
                scored.append((score, index))

        scored.sort(
            key=lambda pair: (
                -pair[0],
                self._chunks[pair[1]].document,
                self._chunks[pair[1]].section,
                self._chunks[pair[1]].ordinal,
            )
        )

        results: list[SearchResult] = []
        for score, index in scored[:top_k]:
            chunk = self._chunks[index]
            results.append(
                SearchResult(
                    document=chunk.document,
                    section=chunk.section,
                    snippet=self._snippet(chunk.text, query_tokens),
                    score=round(score, 6),
                    context=self._context(index, context_chars),
                    matched_text=chunk.text,
                    source_path=chunk.source_path,
                )
            )
        return results

    def _snippet(self, text: str, query_tokens: Sequence[str], limit: int = 280) -> str:
        if len(text) <= limit:
            return text
        lowered = text.lower()
        positions = [lowered.find(term) for term in query_tokens if len(term) > 1]
        positions = [position for position in positions if position >= 0]
        center = min(positions) if positions else 0
        start = max(0, center - limit // 3)
        end = min(len(text), start + limit)
        prefix = "…" if start else ""
        suffix = "…" if end < len(text) else ""
        return f"{prefix}{text[start:end].strip()}{suffix}"

    def _context(self, index: int, context_chars: int) -> str:
        chunk = self._chunks[index]
        parts: list[str] = []
        if context_chars and index > 0:
            previous = self._chunks[index - 1]
            if previous.document == chunk.document and previous.section == chunk.section:
                parts.append(previous.text[-context_chars:])
        parts.append(chunk.text)
        if context_chars and index + 1 < len(self._chunks):
            following = self._chunks[index + 1]
            if following.document == chunk.document and following.section == chunk.section:
                parts.append(following.text[:context_chars])
        return "\n".join(parts)


def search_policies(
    policy_dir: str | Path, query: str, *, top_k: int = 5
) -> list[SearchResult]:
    """Convenience API for one-shot, fully local policy retrieval."""

    return PolicyRetriever.from_directory(policy_dir).search(query, top_k=top_k)


__all__ = [
    "PolicyChunk",
    "PolicyRetriever",
    "SearchResult",
    "load_policy_documents",
    "parse_policy_file",
    "policy_corpus_sha256",
    "search_policies",
    "tokenize",
    "validate_policy_directory",
]
