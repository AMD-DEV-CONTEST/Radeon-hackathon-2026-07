from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from app.rag.corpus import clean_legal_text, load_manifest, split_legal_text
from app.schemas.legal import LegalConclusion, LegalQuoteType
from scripts.audit_legal_quotes import compact


def test_manifest_has_versioned_authoritative_documents_and_unique_chunks():
    documents, chunks = load_manifest("data/laws/source_manifest.json")
    assert len(documents) >= 10
    assert len(chunks) >= 40
    assert len({item.document_id for item in documents}) == len(documents)
    assert len({item.content_hash for item in chunks}) == len(chunks)
    assert all(str(item.source_url).startswith("https://") for item in documents)
    assert all(item.version and item.effective_date for item in chunks)
    assert all(item.page_or_location and item.text for item in chunks)
    assert all(item.quote_type is LegalQuoteType.VERBATIM_EXCERPT for item in chunks)
    assert all(str(item.text_source_url).startswith("https://") for item in chunks)
    assert all(item.article_no != "标准状态" for item in chunks)


def test_known_legal_quotes_are_verbatim_and_not_summaries():
    _, chunks = load_manifest("data/laws/source_manifest.json")
    by_location = {
        (item.document_id, item.article_no, item.item_no): item.text for item in chunks
    }
    assert by_location[("CN-LAW-RTSA-2021", "第七十六条", None)].endswith(
        "按照下列规定承担赔偿责任："
    )
    procedure_74 = by_location[("CN-RULE-ACCIDENT-PROCEDURE-2017", "第七十四条", None)]
    assert "对下列内容进行审查" in procedure_74
    assert "（一）道路交通事故认定的事实是否清楚" in procedure_74
    assert "复核原则上采取书面审查的形式" in procedure_74
    assert "办理复核案件的交通警察不得少于二人" in procedure_74
    assert "在相应范围内依法承担责任" not in " ".join(item.text for item in chunks)


def test_manually_reviewed_quote_fingerprints_match_manifest():
    _, chunks = load_manifest("data/laws/source_manifest.json")
    entries = json.loads(
        open("data/laws/manual_quote_verification.json", encoding="utf-8").read()
    )["entries"]
    by_location = {(item.document_id, item.article_no): item for item in chunks}
    for entry in entries:
        chunk = by_location[(entry["document_id"], entry["article_no"])]
        digest = hashlib.sha256(compact(chunk.text).encode("utf-8")).hexdigest()
        assert digest == entry["quote_compact_sha256"]
        assert str(chunk.text_source_url) == entry["text_source_url"]


def test_reviewed_corpus_integrity_lock_matches_all_59_quotes():
    manifest = json.loads(
        open("data/laws/source_manifest.json", encoding="utf-8").read()
    )
    integrity = json.loads(
        open("data/laws/corpus_integrity.json", encoding="utf-8").read()
    )
    canonical = [
        {
            "document_id": document["document_id"],
            "version": document["version"],
            "text_source_url": document.get("text_source_url", document["source_url"]),
            "sections": document["sections"],
        }
        for document in manifest["documents"]
    ]
    serialized = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(manifest["documents"]) == integrity["document_count"] == 15
    assert (
        sum(len(item["sections"]) for item in manifest["documents"])
        == integrity["quote_count"]
        == integrity["official_quote_audit_passed"]
        == 59
    )
    assert (
        hashlib.sha256(serialized).hexdigest() == integrity["canonical_corpus_sha256"]
    )


def test_clean_and_article_paragraph_item_split():
    text = "\ufeff第一条\u3000第一款内容。\r\n（二）第二项内容。\r\n第二条 第二条内容。"
    assert "\r" not in clean_legal_text(text)
    sections = split_legal_text(text, page_or_location="正文")
    assert [item["article_no"] for item in sections] == [
        "第一条",
        "第一条",
        "第二条",
    ]
    assert sections[1]["paragraph_no"] == "第2款"
    assert sections[1]["item_no"] == "第二项"


def test_deterministic_legal_conclusion_requires_citation():
    with pytest.raises(ValidationError, match="requires at least one citation"):
        LegalConclusion(statement="确定结论", certainty="deterministic")
