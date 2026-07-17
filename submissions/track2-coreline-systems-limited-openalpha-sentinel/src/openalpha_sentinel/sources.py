"""Source adapters for local snapshots, GitHub repositories, and RSS feeds."""

from __future__ import annotations

import base64
import binascii
import hashlib
import mimetypes
import os
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx
import yaml

from .schemas import FetchedArtifact, SourceDocument


DEFAULT_USER_AGENT = "OpenAlpha-Sentinel/0.1"
GITHUB_API_URL = "https://api.github.com"
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}
_GITHUB_COMMIT_BLOB_PATH = re.compile(
    r"^/[^/]+/[^/]+/blob/(?:[0-9a-f]{40}|[0-9a-f]{64})(?:/|$)",
    re.IGNORECASE,
)
_SUPPORTED_SNAPSHOT_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".htm",
    ".html",
    ".java",
    ".js",
    ".json",
    ".md",
    ".markdown",
    ".py",
    ".r",
    ".rst",
    ".rs",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
_ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
_CONTENT_NAMESPACE = "http://purl.org/rss/1.0/modules/content/"
_DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class SourceError(RuntimeError):
    """Base error raised by source adapters."""


class SourceHTTPError(SourceError):
    """A source request failed or returned an unsuccessful response."""

    def __init__(
        self,
        provider: str,
        url: str,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        self.provider = provider
        self.url = url
        self.status_code = status_code
        status = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"{provider} request failed{status} for {url}: {message}")


class SourceParseError(SourceError):
    """A fetched or local source could not be parsed."""


def canonicalize_url(url: str) -> str:
    """Return a stable HTTP(S) URL without fragments or tracking parameters."""

    value = url.strip()
    if not value:
        raise ValueError("URL must not be empty")

    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Expected an absolute HTTP(S) URL, got {url!r}")

    hostname = parsed.hostname.lower()
    port = parsed.port
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")

    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_QUERY_KEYS:
            continue
        query_items.append((key, value))

    return urlunsplit(
        (scheme, hostname, path, urlencode(sorted(query_items)), "")
    )


def _github_repository_url(url: str) -> str:
    canonical = canonicalize_url(url)
    parsed = urlsplit(canonical)
    path = parsed.path
    if parsed.hostname == "github.com" and path.lower().endswith(".git"):
        path = path[:-4]
    return urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), "", ""))


def _sha256(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _bounded_limit(limit: int, *, maximum: int, label: str = "limit") -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError(f"{label} must be an integer")
    if limit < 1:
        raise ValueError(f"{label} must be at least 1")
    if limit > maximum:
        raise ValueError(f"{label} must not exceed {maximum}")
    return limit


def _immutable_snapshot_url(canonical_url: str, revision: str) -> str:
    separator = "&" if "?" in canonical_url else "?"
    return f"{canonical_url}{separator}openalpha_revision=sha256-{revision}"


def _is_commit_pinned_github_blob_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.hostname == "github.com"
        and _GITHUB_COMMIT_BLOB_PATH.match(parsed.path) is not None
    )


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return None


def _content_type(path: Path, override: Any = None) -> str:
    if isinstance(override, str) and override.strip():
        return override.strip()
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown"
    return "text/plain"


def _parse_front_matter(text: str, path: Path) -> tuple[dict[str, Any], str, int]:
    normalized = text.removeprefix("\ufeff")
    lines = normalized.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, normalized, 0

    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() in {"---", "..."}),
        None,
    )
    if closing_index is None:
        raise SourceParseError(f"Unterminated YAML front matter in {path}")

    raw_front_matter = "".join(lines[1:closing_index])
    try:
        parsed = yaml.safe_load(raw_front_matter) or {}
    except yaml.YAMLError as exc:
        raise SourceParseError(f"Invalid YAML front matter in {path}: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise SourceParseError(f"YAML front matter in {path} must be a mapping")
    raw_body = "".join(lines[closing_index + 1 :])
    body = raw_body.lstrip("\r\n")
    stripped_prefix = raw_body[: len(raw_body) - len(body)]
    line_offset = closing_index + 1 + len(stripped_prefix.splitlines())
    return dict(parsed), body, line_offset


class SnapshotSource:
    """Load deterministic, content-addressed artifacts from local text files."""

    def __init__(
        self,
        *,
        max_files: int = 100,
        supported_suffixes: set[str] | None = None,
    ) -> None:
        self.max_files = _bounded_limit(max_files, maximum=10_000, label="max_files")
        suffixes = supported_suffixes or _SUPPORTED_SNAPSHOT_SUFFIXES
        self.supported_suffixes = {
            suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
            for suffix in suffixes
        }

    def load_file(self, path: str | os.PathLike[str]) -> FetchedArtifact:
        """Load one UTF-8 text file as a content-addressed artifact."""

        file_path = Path(path).expanduser()
        return self._load_file(file_path, document_root=file_path.parent)

    def load_directory(
        self,
        directory: str | os.PathLike[str],
        *,
        limit: int | None = None,
    ) -> list[FetchedArtifact]:
        """Recursively load supported files in deterministic path order."""

        root = Path(directory).expanduser()
        if not root.exists():
            raise FileNotFoundError(f"Snapshot directory does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Snapshot path is not a directory: {root}")

        effective_limit = self.max_files
        if limit is not None:
            effective_limit = _bounded_limit(
                limit, maximum=self.max_files, label="limit"
            )

        candidates = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and path.suffix.lower() in self.supported_suffixes
                and not any(part.startswith(".") for part in path.relative_to(root).parts)
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
        return [
            self._load_file(path, document_root=root)
            for path in candidates[:effective_limit]
        ]

    def _load_file(self, path: Path, *, document_root: Path) -> FetchedArtifact:
        if not path.exists():
            raise FileNotFoundError(f"Snapshot file does not exist: {path}")
        if not path.is_file():
            raise IsADirectoryError(f"Snapshot path is not a file: {path}")
        if path.suffix.lower() not in self.supported_suffixes:
            raise SourceParseError(
                f"Unsupported snapshot file type {path.suffix!r}: {path}"
            )

        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SourceParseError(f"Snapshot file is not valid UTF-8: {path}") from exc

        front_matter, text, line_offset = _parse_front_matter(raw_text, path)
        revision = _sha256(raw_text)

        source_url = front_matter.get("source_url") or front_matter.get("url")
        if source_url:
            try:
                canonical_url = canonicalize_url(str(source_url))
            except ValueError as exc:
                raise SourceParseError(
                    f"Invalid source URL in YAML front matter for {path}: {exc}"
                ) from exc
        else:
            canonical_url = path.resolve().as_uri()

        configured_immutable_url = front_matter.get("immutable_url")
        if configured_immutable_url:
            try:
                immutable_url = canonicalize_url(str(configured_immutable_url))
            except ValueError as exc:
                raise SourceParseError(
                    f"Invalid immutable URL in YAML front matter for {path}: {exc}"
                ) from exc
        elif _is_commit_pinned_github_blob_url(canonical_url):
            immutable_url = canonical_url
        else:
            immutable_url = _immutable_snapshot_url(canonical_url, revision)

        try:
            document_path = path.relative_to(document_root).as_posix()
        except ValueError:
            document_path = path.name
        title = str(
            front_matter.get("title") or _first_heading(text) or path.stem
        ).strip()
        author_value = front_matter.get("author")
        author = str(author_value).strip() if author_value is not None else None
        license_value = front_matter.get("license_spdx") or front_matter.get("license")
        license_spdx = str(license_value).strip() if license_value else "NOASSERTION"
        external_id_value = front_matter.get("external_id")
        external_id = (
            str(external_id_value).strip()
            if external_id_value
            else f"snapshot:{_sha256(canonical_url)}"
        )

        metadata = {
            "provider": "snapshot",
            "local_path": str(path.resolve()),
            "content_sha256": revision,
            "front_matter": _json_safe(front_matter),
        }
        return FetchedArtifact(
            kind="snapshot",
            canonical_url=canonical_url,
            external_id=external_id,
            title=title,
            author=author,
            revision_key=revision,
            immutable_url=immutable_url,
            license_spdx=license_spdx,
            documents=[
                SourceDocument(
                    path=document_path,
                    title=title,
                    text=text,
                    content_type=_content_type(path, front_matter.get("content_type")),
                    source_url=immutable_url,
                    line_offset=line_offset,
                )
            ],
            metadata=metadata,
        )


class _HTTPSource:
    provider = "HTTP"

    def __init__(
        self,
        *,
        client: httpx.Client | None,
        timeout: float,
        headers: Mapping[str, str] | None = None,
        url_validator: Callable[[str], None] | None = None,
        max_redirects: int = 5,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if max_redirects < 0:
            raise ValueError("max_redirects must not be negative")
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=False,
        )
        self.timeout = timeout
        self.headers = {"User-Agent": DEFAULT_USER_AGENT, **dict(headers or {})}
        self.url_validator = url_validator
        self.max_redirects = max_redirects

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> _HTTPSource:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        allow_not_found: bool = False,
        max_response_bytes: int | None = None,
    ) -> httpx.Response | None:
        current_url = str(httpx.URL(url, params=params))
        request_headers = dict(self.headers)
        response: httpx.Response | None = None

        for redirect_count in range(self.max_redirects + 1):
            if self.url_validator is not None:
                self.url_validator(current_url)
            try:
                response = self._get_once(
                    current_url,
                    headers=request_headers,
                    max_response_bytes=max_response_bytes,
                )
            except httpx.HTTPError as exc:
                raise SourceHTTPError(self.provider, current_url, str(exc)) from exc

            location = response.headers.get("location")
            if response.status_code not in _REDIRECT_STATUS_CODES or not location:
                break
            if redirect_count >= self.max_redirects:
                raise SourceHTTPError(
                    self.provider,
                    current_url,
                    f"redirect limit exceeded ({self.max_redirects})",
                    status_code=response.status_code,
                )

            next_url = urljoin(str(response.request.url), location)
            current_parts = urlsplit(current_url)
            next_parts = urlsplit(next_url)
            if current_parts.scheme.lower() == "https" and next_parts.scheme.lower() != "https":
                raise SourceHTTPError(
                    self.provider,
                    next_url,
                    "refusing an HTTPS-to-HTTP redirect",
                    status_code=response.status_code,
                )
            if (
                current_parts.scheme.lower(),
                current_parts.hostname,
                current_parts.port,
            ) != (
                next_parts.scheme.lower(),
                next_parts.hostname,
                next_parts.port,
            ):
                request_headers.pop("Authorization", None)
            response.close()
            current_url = next_url

        assert response is not None

        if allow_not_found and response.status_code == 404:
            return None
        if response.is_error:
            message = _response_error_message(response)
            if (
                self.provider == "GitHub"
                and response.status_code == 403
                and response.headers.get("x-ratelimit-remaining") == "0"
            ):
                reset = response.headers.get("x-ratelimit-reset", "unknown")
                message = f"GitHub API rate limit exhausted; reset={reset}; {message}"
            raise SourceHTTPError(
                self.provider,
                str(response.request.url),
                message,
                status_code=response.status_code,
            )
        return response

    def _get_once(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        max_response_bytes: int | None,
    ) -> httpx.Response:
        if max_response_bytes is None:
            return self.client.get(
                url,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=False,
            )

        with self.client.stream(
            "GET",
            url,
            headers=headers,
            timeout=self.timeout,
            follow_redirects=False,
        ) as streamed:
            declared_size = streamed.headers.get("content-length")
            if (
                declared_size
                and declared_size.isdigit()
                and int(declared_size) > max_response_bytes
            ):
                raise SourceParseError(
                    f"{self.provider} response exceeds {max_response_bytes} byte limit: {url}"
                )
            content = bytearray()
            if streamed.status_code not in _REDIRECT_STATUS_CODES:
                for chunk in streamed.iter_bytes():
                    content.extend(chunk)
                    if len(content) > max_response_bytes:
                        raise SourceParseError(
                            f"{self.provider} response exceeds "
                            f"{max_response_bytes} byte limit: {url}"
                        )
            return httpx.Response(
                streamed.status_code,
                headers=streamed.headers,
                content=bytes(content),
                request=streamed.request,
            )


def _response_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        payload = None
    if isinstance(payload, Mapping) and payload.get("message"):
        return str(payload["message"])
    text = response.text.strip().replace("\n", " ")
    return text[:300] if text else response.reason_phrase


def _json_object(response: httpx.Response, *, context: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SourceParseError(f"{context} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SourceParseError(f"{context} returned JSON that is not an object")
    return payload


def _decode_github_content(payload: Mapping[str, Any], *, context: str) -> str:
    content = payload.get("content")
    if not isinstance(content, str):
        raise SourceParseError(f"{context} response does not contain text content")
    encoding = str(payload.get("encoding") or "").lower()
    if encoding == "base64":
        try:
            decoded = base64.b64decode(content, validate=False)
            return decoded.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise SourceParseError(f"{context} contains invalid base64 UTF-8 data") from exc
    if encoding in {"", "utf-8", "none"}:
        return content
    raise SourceParseError(f"{context} uses unsupported encoding {encoding!r}")


class GitHubSource(_HTTPSource):
    """Discover public repositories and snapshot their README and license."""

    provider = "GitHub"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        token: str | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20.0,
        api_url: str = GITHUB_API_URL,
        url_validator: Callable[[str], None] | None = None,
    ) -> None:
        token = token if token is not None else os.getenv("GITHUB_TOKEN")
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        super().__init__(
            client=client,
            timeout=timeout,
            headers=headers,
            url_validator=url_validator,
        )
        self.api_url = api_url.rstrip("/")

    def search(self, query: str, limit: int = 10) -> list[FetchedArtifact]:
        """Search repositories and return commit-pinned source artifacts."""

        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("GitHub search query must not be empty")
        requested = _bounded_limit(limit, maximum=100)
        response = self._request(
            f"{self.api_url}/search/repositories",
            params={"q": normalized_query, "per_page": requested, "page": 1},
        )
        assert response is not None
        payload = _json_object(response, context="GitHub repository search")
        items = payload.get("items")
        if not isinstance(items, list):
            raise SourceParseError("GitHub repository search response has no items list")

        artifacts: list[FetchedArtifact] = []
        for item in items[:requested]:
            if not isinstance(item, Mapping):
                raise SourceParseError("GitHub repository search returned an invalid item")
            artifacts.append(self._fetch_repository(item))
        return artifacts

    def _fetch_repository(self, repository: Mapping[str, Any]) -> FetchedArtifact:
        full_name = repository.get("full_name")
        html_url = repository.get("html_url")
        default_branch = repository.get("default_branch") or "HEAD"
        if not isinstance(full_name, str) or "/" not in full_name:
            raise SourceParseError("GitHub repository item has no valid full_name")
        if not isinstance(html_url, str):
            raise SourceParseError(f"GitHub repository {full_name} has no html_url")

        commit_response = self._request(
            f"{self.api_url}/repos/{full_name}/commits/{quote(str(default_branch), safe='')}"
        )
        assert commit_response is not None
        commit = _json_object(
            commit_response, context=f"GitHub commit for {full_name}"
        )
        revision = commit.get("sha")
        if not isinstance(revision, str) or not revision.strip():
            raise SourceParseError(f"GitHub commit for {full_name} has no SHA")
        revision = revision.strip()

        readme_response = self._request(
            f"{self.api_url}/repos/{full_name}/readme",
            params={"ref": revision},
            allow_not_found=True,
        )
        license_response = self._request(
            f"{self.api_url}/repos/{full_name}/license",
            params={"ref": revision},
            allow_not_found=True,
        )

        documents: list[SourceDocument] = []
        missing_documents: list[str] = []
        if readme_response is None:
            missing_documents.append("README")
        else:
            readme = _json_object(
                readme_response, context=f"GitHub README for {full_name}"
            )
            documents.append(
                self._github_document(
                    full_name=full_name,
                    revision=revision,
                    payload=readme,
                    fallback_path="README.md",
                    fallback_title=f"{full_name} README",
                )
            )

        license_spdx = "NOASSERTION"
        if license_response is None:
            missing_documents.append("LICENSE")
        else:
            license_payload = _json_object(
                license_response, context=f"GitHub license for {full_name}"
            )
            license_metadata = license_payload.get("license")
            if isinstance(license_metadata, Mapping):
                spdx = license_metadata.get("spdx_id")
                if isinstance(spdx, str) and spdx.strip():
                    license_spdx = spdx.strip()
            documents.append(
                self._github_document(
                    full_name=full_name,
                    revision=revision,
                    payload=license_payload,
                    fallback_path="LICENSE",
                    fallback_title=f"{full_name} license",
                )
            )

        canonical_url = _github_repository_url(html_url)
        owner = repository.get("owner")
        author = owner.get("login") if isinstance(owner, Mapping) else None
        commit_details = commit.get("commit")
        commit_author_date = None
        if isinstance(commit_details, Mapping):
            commit_author = commit_details.get("author")
            if isinstance(commit_author, Mapping):
                commit_author_date = commit_author.get("date")

        return FetchedArtifact(
            kind="github_repository",
            canonical_url=canonical_url,
            external_id=f"github:{repository.get('id', full_name)}",
            title=str(repository.get("name") or full_name),
            author=str(author) if author else None,
            revision_key=revision,
            immutable_url=f"{canonical_url}/tree/{revision}",
            license_spdx=license_spdx,
            documents=documents,
            metadata={
                "provider": "github",
                "full_name": full_name,
                "default_branch": default_branch,
                "description": repository.get("description"),
                "language": repository.get("language"),
                "topics": repository.get("topics") or [],
                "stargazers_count": repository.get("stargazers_count"),
                "fork": bool(repository.get("fork", False)),
                "archived": bool(repository.get("archived", False)),
                "commit_author_date": commit_author_date,
                "missing_documents": missing_documents,
            },
            etag=commit_response.headers.get("etag"),
            last_modified=commit_response.headers.get("last-modified"),
        )

    def _github_document(
        self,
        *,
        full_name: str,
        revision: str,
        payload: Mapping[str, Any],
        fallback_path: str,
        fallback_title: str,
    ) -> SourceDocument:
        path_value = payload.get("path")
        path = str(path_value).strip() if path_value else fallback_path
        text = _decode_github_content(
            payload, context=f"GitHub document {full_name}/{path}"
        )
        return SourceDocument(
            path=path,
            title=fallback_title,
            text=text,
            content_type=_content_type(Path(path)),
            source_url=(
                f"https://github.com/{full_name}/blob/{revision}/{quote(path, safe='/')}"
            ),
        )


class RSSSource(_HTTPSource):
    """Fetch RSS/Atom entries without following their article links."""

    provider = "RSS"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20.0,
        max_entries: int = 50,
        max_feed_bytes: int = 5_000_000,
        url_validator: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            client=client,
            timeout=timeout,
            headers={
                "User-Agent": user_agent,
                "Accept": (
                    "application/atom+xml, application/rss+xml, "
                    "application/xml;q=0.9, text/xml;q=0.8"
                )
            },
            url_validator=url_validator,
        )
        self.max_entries = _bounded_limit(
            max_entries, maximum=1_000, label="max_entries"
        )
        if max_feed_bytes < 1:
            raise ValueError("max_feed_bytes must be at least 1")
        self.max_feed_bytes = max_feed_bytes

    def fetch(
        self, feed_url: str, *, limit: int | None = None
    ) -> list[FetchedArtifact]:
        """Fetch one feed and ingest only fields embedded in each entry."""

        canonical_feed_url = canonicalize_url(feed_url)
        effective_limit = self.max_entries
        if limit is not None:
            effective_limit = _bounded_limit(
                limit, maximum=self.max_entries, label="limit"
            )
        response = self._request(
            canonical_feed_url,
            max_response_bytes=self.max_feed_bytes,
        )
        assert response is not None

        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise SourceParseError(
                f"Invalid RSS/Atom XML from {canonical_feed_url}: {exc}"
            ) from exc

        entries = _feed_entries(root)
        artifacts = [
            self._entry_artifact(
                entry,
                feed_url=canonical_feed_url,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
            for entry in entries[:effective_limit]
        ]
        return artifacts

    def _entry_artifact(
        self,
        entry: ElementTree.Element,
        *,
        feed_url: str,
        etag: str | None,
        last_modified: str | None,
    ) -> FetchedArtifact:
        is_atom = _local_name(entry.tag) == "entry"
        if is_atom:
            title = _element_text(entry.find(f"{{{_ATOM_NAMESPACE}}}title"))
            summary = _element_text(entry.find(f"{{{_ATOM_NAMESPACE}}}summary"))
            content = _element_text(entry.find(f"{{{_ATOM_NAMESPACE}}}content"))
            external_id = _element_text(entry.find(f"{{{_ATOM_NAMESPACE}}}id"))
            link = _atom_link(entry)
            author_element = entry.find(f"{{{_ATOM_NAMESPACE}}}author")
            author = (
                _element_text(author_element.find(f"{{{_ATOM_NAMESPACE}}}name"))
                if author_element is not None
                else None
            )
            published = _element_text(
                entry.find(f"{{{_ATOM_NAMESPACE}}}published")
            )
            updated = _element_text(entry.find(f"{{{_ATOM_NAMESPACE}}}updated"))
        else:
            title = _child_text(entry, "title")
            summary = _child_text(entry, "description")
            content = _child_text(entry, "encoded", namespace=_CONTENT_NAMESPACE)
            external_id = _child_text(entry, "guid")
            link = _child_text(entry, "link")
            author = _child_text(entry, "author") or _child_text(
                entry, "creator", namespace=_DC_NAMESPACE
            )
            published = _child_text(entry, "pubDate") or _child_text(
                entry, "date", namespace=_DC_NAMESPACE
            )
            updated = None

        title = title or "Untitled feed entry"
        resolved_link = urljoin(feed_url, link) if link else None
        if resolved_link:
            try:
                canonical_url = canonicalize_url(resolved_link)
            except ValueError as exc:
                raise SourceParseError(
                    f"RSS entry {title!r} contains an invalid link: {exc}"
                ) from exc
        else:
            identifier_seed = external_id or f"{title}\n{published or updated or ''}"
            canonical_url = (
                f"{feed_url}{'&' if '?' in feed_url else '?'}"
                f"openalpha_entry={_sha256(identifier_seed)}"
            )

        stable_external_id = external_id or canonical_url
        document_text = _rss_document_text(title, summary, content)
        revision = _sha256(
            "\n".join(
                [
                    stable_external_id,
                    title,
                    summary or "",
                    content or "",
                    published or "",
                    updated or "",
                ]
            )
        )
        return FetchedArtifact(
            kind="rss_entry",
            canonical_url=canonical_url,
            external_id=f"rss:{_sha256(stable_external_id)}",
            title=title,
            author=author,
            revision_key=revision,
            immutable_url=_immutable_snapshot_url(canonical_url, revision),
            license_spdx="NOASSERTION",
            documents=[
                SourceDocument(
                    path=f"rss/{revision[:16]}.md",
                    title=title,
                    text=document_text,
                    content_type="text/markdown",
                    source_url=canonical_url,
                )
            ],
            metadata={
                "provider": "rss",
                "feed_url": feed_url,
                "entry_id": external_id,
                "published": published,
                "updated": updated,
            },
            etag=etag,
            last_modified=last_modified,
        )


def _feed_entries(root: ElementTree.Element) -> list[ElementTree.Element]:
    if _local_name(root.tag) == "feed":
        return list(root.findall(f"{{{_ATOM_NAMESPACE}}}entry"))

    channel = next(
        (child for child in root if _local_name(child.tag) == "channel"), None
    )
    if channel is not None:
        channel_items = [
            child for child in channel if _local_name(child.tag) == "item"
        ]
        if channel_items:
            return channel_items
    return [element for element in root.iter() if _local_name(element.tag) == "item"]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element_text(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    text = "".join(element.itertext()).strip()
    return text or None


def _child_text(
    element: ElementTree.Element,
    name: str,
    *,
    namespace: str | None = None,
) -> str | None:
    child = (
        element.find(f"{{{namespace}}}{name}")
        if namespace
        else next(
            (item for item in element if _local_name(item.tag) == name), None
        )
    )
    return _element_text(child)


def _atom_link(entry: ElementTree.Element) -> str | None:
    links = entry.findall(f"{{{_ATOM_NAMESPACE}}}link")
    for link in links:
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link.get("href")
    return next((link.get("href") for link in links if link.get("href")), None)


def _rss_document_text(
    title: str, summary: str | None, content: str | None
) -> str:
    sections = [f"# {title}"]
    if summary:
        sections.extend(["## Summary", summary])
    if content and content != summary:
        sections.extend(["## Content", content])
    return "\n\n".join(sections).strip() + "\n"


__all__ = [
    "GitHubSource",
    "RSSSource",
    "SnapshotSource",
    "SourceError",
    "SourceHTTPError",
    "SourceParseError",
    "canonicalize_url",
]
