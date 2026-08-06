"""Document metadata extraction.

Metadata is the cheapest Tier M win in the whole system: authors ship .docx and
.pdf files with the creator field intact more often than anyone would like.
"""
from __future__ import annotations

import zipfile
from typing import Any
from xml.etree import ElementTree

from veil.tools.registry import REGISTRY

_INTERESTING = (
    "Author",
    "Creator",
    "Producer",
    "Title",
    "Subject",
    "Keywords",
    "Company",
    "LastModifiedBy",
    "CreationDate",
    "ModDate",
)


def _pdf_metadata(path: str) -> dict[str, Any]:
    import pypdf

    reader = pypdf.PdfReader(path)
    meta = reader.metadata or {}
    out = {k.lstrip("/"): str(v) for k, v in meta.items()}
    out["_page_count"] = len(reader.pages)
    # Incremental updates leave earlier document states in the file.
    with open(path, "rb") as fh:
        blob = fh.read()
    revisions = blob.count(b"%%EOF")
    if revisions > 1:
        out["_incremental_revisions"] = revisions - 1
    return out


def _docx_metadata(path: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with zipfile.ZipFile(path) as z:
        for part in ("docProps/core.xml", "docProps/app.xml"):
            if part not in z.namelist():
                continue
            root = ElementTree.fromstring(z.read(part))
            for el in root.iter():
                tag = el.tag.rsplit("}", 1)[-1]
                if el.text and el.text.strip():
                    out[tag] = el.text.strip()
        # Comments and tracked changes survive "accept all" surprisingly often.
        if "word/comments.xml" in z.namelist():
            out["_has_comments"] = True
        body = z.read("word/document.xml").decode("utf-8", "ignore")
        if "w:ins " in body or "w:del " in body:
            out["_has_tracked_changes"] = True
    return out


@REGISTRY.register(
    name="doc_metadata",
    description=(
        "Read embedded document metadata (author, creator, company, last "
        "modified by, timestamps) and structural remnants (tracked changes, "
        "comments, incremental PDF revisions). Mechanical evidence only."
    ),
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path to the document."}},
        "required": ["path"],
    },
)
def doc_metadata(path: str) -> dict[str, Any]:
    lower = path.lower()
    try:
        if lower.endswith(".pdf"):
            raw = _pdf_metadata(path)
        elif lower.endswith((".docx", ".dotx")):
            raw = _docx_metadata(path)
        else:
            return {"supported": False, "reason": f"No metadata reader for {path!r}"}
    except Exception as exc:  # noqa: BLE001 - a malformed file is a finding, not a crash
        return {"supported": True, "error": f"{type(exc).__name__}: {exc}"}

    identifying = {
        k: v for k, v in raw.items() if any(t.lower() in k.lower() for t in _INTERESTING)
    }
    return {
        "supported": True,
        "identifying_fields": identifying,
        "structural_flags": {k: v for k, v in raw.items() if k.startswith("_")},
        "all_fields": raw,
    }
