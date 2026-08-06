from pathlib import Path
from tempfile import NamedTemporaryFile
from fastapi import FastAPI, File, UploadFile, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from .models import QuestionRequest, RcaRequest, ProcessPathRequest, RcaExportRequest
from .extraction import extract_text, extract_entities, classify_document
from .index_store import store, chunk_pages
from .generation import generate_answer, generate_rca
from .docx_report import create_rca_docx
from .config import settings

app = FastAPI(
    title="IndusMind AI Service",
    version="1.0.0",
    description="Lightweight document intelligence, retrieval, citation, and RCA service.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


SUPPORTED_SUFFIXES = {
    ".pdf", ".txt", ".csv", ".docx",
    ".jpg", ".jpeg", ".png", ".tiff", ".bmp",
    ".xlsx", ".xls", ".pptx", ".md", ".json",
    ".xml", ".html", ".htm", ".eml", ".msg"
}


@app.get("/ai/health")
def health() -> dict:
    return {
        "status": "UP",
        "service": "ai-service",
        "vectorEngine": store.engine,
        "chunks": store.count(),
        "generationMode": "gemini" if settings.gemini_api_key else "offline-evidence",
        "ocrConfigured": bool(settings.tesseract_cmd),
    }


@app.post("/ai/documents/process")
async def process_document(
        file: UploadFile = File(...),
        document_id: str = "",
        original_name: str = "") -> dict:
    if not document_id or not original_name:
        raise HTTPException(400, "document_id and original_name are required")
    suffix = Path(original_name).suffix.lower()
    if suffix and suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, f"Unsupported document type: {suffix}")
    with NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(await file.read())
        temp_path = Path(handle.name)
    try:
        text, pages = extract_text(temp_path)
        if not text.strip():
            raise HTTPException(422, "No readable text was found. Install/configure Tesseract for scanned PDFs.")
        entities = extract_entities(text)
        doc_type = classify_document(original_name, text)
        chunks = chunk_pages(pages)
        store.add(document_id, original_name, chunks, entities, doc_type)
        return {
            "document_id": document_id,
            "document_type": doc_type,
            "asset_tags": entities["asset_tags"],
            "entities": entities,
            "chunks": len(chunks),
            "summary": f"Indexed {len(chunks)} evidence chunks and found {len(entities['asset_tags'])} asset tags.",
            "vector_engine": store.engine,
        }
    finally:
        temp_path.unlink(missing_ok=True)


@app.post("/ai/documents/process-path")
def process_document_path(request: ProcessPathRequest) -> dict:
    path = Path(request.file_path).resolve()
    suffix = Path(request.original_name).suffix.lower()
    if suffix and suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, f"Unsupported document type: {suffix}")
    if not path.is_file():
        raise HTTPException(404, "Uploaded file is not accessible to the AI service")
    text, pages = extract_text(path)
    if not text.strip():
        raise HTTPException(422, "No readable text was found. Install/configure Tesseract for scanned PDFs.")
    entities = extract_entities(text)
    doc_type = classify_document(request.original_name, text)
    chunks = chunk_pages(pages)
    store.add(request.document_id, request.original_name, chunks, entities, doc_type)
    return {
        "document_id": request.document_id,
        "document_type": doc_type,
        "asset_tags": entities["asset_tags"],
        "entities": entities,
        "chunks": len(chunks),
        "summary": f"Indexed {len(chunks)} evidence chunks and found {len(entities['asset_tags'])} asset tags.",
        "vector_engine": store.engine,
    }


@app.post("/ai/answer")
def answer(request: QuestionRequest) -> dict:
    import re as _re
    question = request.question.strip()

    # ── Handle greetings and conversational queries ──────────────────
    greeting_words = {"hi", "hello", "hey", "good morning", "good afternoon",
                      "good evening", "howdy", "greetings", "thanks", "thank you",
                      "bye", "goodbye", "ok", "okay", "yes", "no", "sure"}
    q_lower = question.lower().rstrip("!.,? ")
    if q_lower in greeting_words or len(q_lower) < 3:
        return {
            "answer": (
                "Hello! I'm IndusMind AI, your industrial intelligence assistant. "
                "You can ask me questions about your uploaded maintenance records, "
                "inspection reports, and equipment manuals. For example, try: "
                "'What maintenance was performed on P-101?' or "
                "'What are the common failure modes in our records?'"
            ),
            "mode": "assistant",
            "confidence": 1.0,
            "citations": [],
            "assetTag": "",
        }

    # ── Standard evidence search ────────────────────────────────────
    evidence = store.search(question, request.asset_tag, 5)

    # ── Filename-based fallback ─────────────────────────────────────
    file_pat = _re.compile(
        r'[\w\-\.]+\.(xlsx|xls|pdf|csv|docx|txt|pptx|json|xml|html|htm|md|eml|msg)',
        _re.IGNORECASE,
    )
    file_match = file_pat.search(question)
    if file_match:
        filename = file_match.group(0)
        source_results = store.search_by_source(filename, limit=5)
        if source_results and (not evidence or evidence[0]["score"] < 0.1):
            evidence = source_results
        elif source_results:
            seen = {
                (r["metadata"].get("document_id", ""), r["metadata"].get("page", 0))
                for r in source_results
            }
            for item in evidence:
                key = (item["metadata"].get("document_id", ""), item["metadata"].get("page", 0))
                if key not in seen:
                    source_results.append(item)
            evidence = source_results[:5]

    # Also try partial document-name matching (no extension)
    if not file_match and (not evidence or evidence[0]["score"] < 0.1):
        name_pat = _re.compile(r'[A-Za-z0-9][\w\-]{4,}[\w]')
        skip = {
            "about", "which", "where", "there", "their", "these", "those",
            "should", "would", "could", "maintenance", "performed",
            "inspection", "question", "tell", "what", "have", "been",
        }
        for name in name_pat.findall(question):
            if len(name) > 5 and name.lower() not in skip:
                source_results = store.search_by_source(name, limit=5)
                if source_results:
                    evidence = source_results
                    break

    answer_text, mode = generate_answer(
        question, evidence, getattr(request, "desired_format", "quick_answer"),
    )
    confidence = 0.0 if not evidence else min(
        0.94, 0.55 + len(evidence) * 0.035 + max(item["score"] for item in evidence) * 0.22,
    )
    citations = [
        {
            "source": item["metadata"]["source"],
            "page": item["metadata"]["page"],
            "documentType": item["metadata"].get("document_type", ""),
            "excerpt": item["text"][:360],
            "relevance": round(min(0.97, 0.5 + item["score"] * 0.45), 2),
        }
        for item in evidence
    ]
    return {
        "answer": answer_text,
        "mode": mode,
        "confidence": round(confidence, 2),
        "citations": citations,
        "assetTag": request.asset_tag.upper() if request.asset_tag else "",
    }


@app.get("/ai/assets/{tag}")
def asset(tag: str) -> dict:
    evidence = store.asset(tag)
    if not evidence:
        raise HTTPException(404, f"No indexed evidence found for {tag.upper()}")
    sources, failures, actions, dates, measurements = set(), set(), set(), set(), set()
    events = []
    for item in evidence:
        meta = item["metadata"]
        sources.add(meta["source"])
        failures.update(filter(None, meta.get("failures", "").split(",")))
        actions.update(filter(None, meta.get("actions", "").split(",")))
        dates.update(filter(None, meta.get("dates", "").split(",")))
        measurements.update(filter(None, meta.get("measurements", "").split(",")))
        if meta.get("dates"):
            events.append({
                "date": meta["dates"].split(",")[0],
                "source": meta["source"],
                "summary": item["text"][:220],
            })
    return {
        "tag": tag.upper(),
        "sources": sorted(sources),
        "failures": sorted(failures),
        "maintenanceActions": sorted(actions),
        "dates": sorted(dates),
        "measurements": sorted(measurements),
        "timeline": events[:12],
        "evidenceChunks": len(evidence),
    }


@app.post("/ai/rca")
def rca(request: RcaRequest) -> dict:
    evidence = store.asset(request.asset_tag)
    if not evidence:
        raise HTTPException(404, f"No indexed evidence found for {request.asset_tag.upper()}")
    result = generate_rca(request.asset_tag, evidence)
    result["citations"] = [
        {"source": item["metadata"]["source"], "page": item["metadata"]["page"], "excerpt": item["text"][:280]}
        for item in evidence[:5]
    ]
    return result


@app.get("/ai/rca/export-docx/{tag}")
def export_rca_docx(tag: str):
    evidence = store.asset(tag)
    if not evidence:
        raise HTTPException(404, f"No indexed evidence found for {tag.upper()}")
    result = generate_rca(tag, evidence)
    result["citations"] = [
        {"source": item["metadata"]["source"], "page": item["metadata"]["page"], "excerpt": item["text"][:280]}
        for item in evidence[:5]
    ]
    docx_bytes = create_rca_docx(result)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="RCA_{tag.upper()}.docx"'}
    )


@app.post("/ai/rca/export")
def export_rca(request: RcaExportRequest):
    return export_rca_docx(request.asset_tag)


@app.get("/ai/analytics")
def analytics() -> dict:
    records = store.all_records()
    total_chunks = len(records)
    assets_map = {}
    failure_counts = {}
    action_counts = {}

    for item in records:
        meta = item.get("metadata", {})
        tags = filter(None, meta.get("asset_tags", "").split(","))
        failures = list(filter(None, meta.get("failures", "").split(",")))
        actions = list(filter(None, meta.get("actions", "").split(",")))

        for f in failures:
            f_clean = f.strip()
            if f_clean:
                failure_counts[f_clean] = failure_counts.get(f_clean, 0) + 1
        for a in actions:
            a_clean = a.strip()
            if a_clean:
                action_counts[a_clean] = action_counts.get(a_clean, 0) + 1

        for t in tags:
            tag_clean = t.strip().upper()
            if not tag_clean:
                continue
            if tag_clean not in assets_map:
                assets_map[tag_clean] = {"failures": [], "docs": set()}
            assets_map[tag_clean]["failures"].extend(failures)
            assets_map[tag_clean]["docs"].add(meta.get("document_id", ""))

    top_failure_modes = [
        {"failure": k, "count": v}
        for k, v in sorted(failure_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]
    top_actions = [
        {"action": k, "count": v}
        for k, v in sorted(action_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    assets_ranked = []
    for tag, info in assets_map.items():
        f_list = [f.strip() for f in info["failures"] if f.strip()]
        top_f = max(set(f_list), key=f_list.count) if f_list else None
        assets_ranked.append({
            "assetTag": tag,
            "failureEvents": len(f_list),
            "topFailure": top_f,
            "documentCount": len(info["docs"])
        })
    assets_ranked.sort(key=lambda x: x["failureEvents"], reverse=True)

    return {
        "totalChunks": total_chunks,
        "totalAssets": len(assets_map),
        "topFailureModes": top_failure_modes,
        "topActions": top_actions,
        "assetsRankedByRisk": assets_ranked,
    }


@app.delete("/ai/documents/{id}")
def delete_doc(id: str) -> dict:
    store.delete(id)
    return {"status": "ok", "id": id}

