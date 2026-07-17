from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = {"fbclid", "gclid", "ref", "source"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str, seed: str | None = None) -> str:
    if seed is None:
        return f"{prefix}_{uuid.uuid4().hex[:20]}"
    return f"{prefix}_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:20]}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    host = (parts.hostname or "").lower()
    if parts.port and not ((scheme == "https" and parts.port == 443) or (scheme == "http" and parts.port == 80)):
        host = f"{host}:{parts.port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
        )
    )
    return urlunsplit((scheme, host, path, query, ""))


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    groups = re.findall(r"[a-z0-9_+#.-]+|[\u4e00-\u9fff]+", normalized)
    tokens: list[str] = []
    for group in groups:
        if re.fullmatch(r"[\u4e00-\u9fff]+", group):
            tokens.extend(group)
            tokens.extend(group[index : index + 2] for index in range(len(group) - 1))
        elif len(group) > 1:
            tokens.append(group)
    return tokens


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        clean = re.sub(r"^[#>*\-\s]+", "", line).strip()
        if clean:
            return clean[:160]
    return "Untitled strategy"
