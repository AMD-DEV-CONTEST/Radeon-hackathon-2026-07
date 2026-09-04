"""Verify curated legal excerpts against downloaded official-source snapshots.

Whitespace introduced by HTML/PDF layout extraction is ignored.  Every other
character, including punctuation, list markers, and legally meaningful words,
must occur in the official snapshot in the same order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def compact(text: str) -> str:
    """Ignore layout whitespace and compatibility-only typography variants."""

    normalized = unicodedata.normalize("NFKC", text).replace("\ufeff", "")
    return re.sub(r"\s+", "", normalized)


def extract_html(path: Path) -> str:
    parser = _VisibleTextParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return " ".join(parser.parts)


def extract_pdf(path: Path) -> str:
    try:
        import fitz

        with fitz.open(path) as pdf:
            return "\n".join(page.get_text("text") for page in pdf)
    except ImportError:
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError(
                "PDF quote audit requires the evidence extra (PyMuPDF) or pdfplumber."
            ) from exc
        with pdfplumber.open(path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)


def extract_snapshot(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return extract_pdf(path)
    return extract_html(path)


def audit(
    manifest_path: Path,
    verification_path: Path,
    manual_verification_path: Path | None = None,
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    sources = {
        item["document_id"]: item
        for item in verification.get("results", [])
        if item.get("verified") and item.get("snapshot")
    }
    manual_path = manual_verification_path or (
        manifest_path.parent / "manual_quote_verification.json"
    )
    manual_entries: dict[tuple[str, str], dict[str, object]] = {}
    if manual_path.exists():
        manual = json.loads(manual_path.read_text(encoding="utf-8"))
        manual_entries = {
            (item["document_id"], item["article_no"]): item
            for item in manual.get("entries", [])
        }
    results: list[dict[str, object]] = []
    for document in manifest["documents"]:
        document_id = document["document_id"]
        source = sources.get(document_id)
        if source is None:
            snapshot_dir = verification_path.parent / "snapshots"
            cached = next(
                (
                    candidate
                    for suffix in (".html", ".pdf")
                    if (candidate := snapshot_dir / f"{document_id}{suffix}").exists()
                ),
                None,
            )
            if cached is not None:
                source = {
                    "snapshot": str(cached),
                    "sha256": hashlib.sha256(cached.read_bytes()).hexdigest(),
                    "cached_official_snapshot": True,
                }
        if source is None:
            for section in document["sections"]:
                results.append(
                    {
                        "document_id": document_id,
                        "article_no": section["article_no"],
                        "verified": False,
                        "error": "no verified official snapshot",
                    }
                )
            continue
        snapshot = Path(source["snapshot"])
        try:
            official_text = compact(extract_snapshot(snapshot))
        except Exception as exc:
            for section in document["sections"]:
                manual_entry = manual_entries.get((document_id, section["article_no"]))
                snapshot_hash = (
                    source.get("sha256")
                    or hashlib.sha256(snapshot.read_bytes()).hexdigest()
                )
                manual_match = False
                if manual_entry is not None:
                    quote_hash = hashlib.sha256(
                        compact(section["text"]).encode("utf-8")
                    ).hexdigest()
                    expected_snapshot_hash = manual_entry.get("source_snapshot_sha256")
                    manual_match = (
                        quote_hash == manual_entry["quote_compact_sha256"]
                        and expected_snapshot_hash == snapshot_hash
                    )
                results.append(
                    {
                        "document_id": document_id,
                        "article_no": section["article_no"],
                        "paragraph_no": section.get("paragraph_no"),
                        "item_no": section.get("item_no"),
                        "quote_type": section.get("quote_type"),
                        "text_source_url": document.get(
                            "text_source_url", document["source_url"]
                        ),
                        "snapshot": str(snapshot),
                        "snapshot_sha256": snapshot_hash,
                        "live_source_verified": not bool(
                            source.get("cached_official_snapshot")
                        ),
                        "verification_method": (
                            manual_entry["verification_method"]
                            if manual_match and manual_entry is not None
                            else "failed"
                        ),
                        "verified": manual_match,
                        "error": (
                            None if manual_match else f"{type(exc).__name__}: {exc}"
                        ),
                    }
                )
            continue
        for section in document["sections"]:
            quote = compact(section["text"])
            direct_match = quote in official_text
            manual_entry = manual_entries.get((document_id, section["article_no"]))
            manual_match = False
            if manual_entry is not None:
                quote_hash = hashlib.sha256(quote.encode("utf-8")).hexdigest()
                expected_snapshot_hash = manual_entry.get("source_snapshot_sha256")
                manual_match = quote_hash == manual_entry["quote_compact_sha256"] and (
                    expected_snapshot_hash is None
                    or expected_snapshot_hash == source.get("sha256")
                )
            results.append(
                {
                    "document_id": document_id,
                    "article_no": section["article_no"],
                    "paragraph_no": section.get("paragraph_no"),
                    "item_no": section.get("item_no"),
                    "quote_type": section.get("quote_type"),
                    "text_source_url": document.get(
                        "text_source_url", document["source_url"]
                    ),
                    "snapshot": str(snapshot),
                    "snapshot_sha256": source.get("sha256"),
                    "live_source_verified": not bool(
                        source.get("cached_official_snapshot")
                    ),
                    "verification_method": (
                        "official_snapshot_substring"
                        if direct_match
                        else (
                            manual_entry["verification_method"]
                            if manual_match and manual_entry is not None
                            else "failed"
                        )
                    ),
                    "verified": direct_match or manual_match,
                }
            )
    passed = sum(bool(item["verified"]) for item in results)
    automatic = sum(
        item.get("verification_method") == "official_snapshot_substring"
        for item in results
    )
    return {
        "manifest_schema_version": manifest["schema_version"],
        "documents": len(manifest["documents"]),
        "quotes": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "automatic_snapshot_matches": automatic,
        "audited_fingerprint_matches": passed - automatic,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/laws/source_manifest.json")
    )
    parser.add_argument(
        "--verification",
        type=Path,
        default=Path("data/laws/source_verification.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/laws/quote_audit.json"),
    )
    parser.add_argument(
        "--manual-verification",
        type=Path,
        default=Path("data/laws/manual_quote_verification.json"),
    )
    args = parser.parse_args()
    report = audit(args.manifest, args.verification, args.manual_verification)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "documents",
                    "quotes",
                    "passed",
                    "failed",
                    "automatic_snapshot_matches",
                    "audited_fingerprint_matches",
                )
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
