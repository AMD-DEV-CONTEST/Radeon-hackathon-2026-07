"""Local-only JSON API for the React ClaimCourt frontend.

The API deliberately delegates parsing, retrieval, redaction, court validation,
and export formatting to ``core.py``. It never calls a hosted model provider.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from core import (
    Evidence,
    LocalOllama,
    LocalRetriever,
    LocalVLLM,
    assess_file_matches,
    compile_intent,
    is_file_inventory_request,
    markdown_brief,
    redact_sensitive_text,
    route_workspace_request,
    run_court,
    scan_workspace,
    summarize_artifact,
    local_runtime_status,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("CLAIMCOURT_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
INDEX_FILE = Path(os.getenv("CLAIMCOURT_INDEX_FILE", str(DATA_DIR / "workspace_index.json"))).expanduser().resolve()
ACTIVE_WORKSPACE_FILE = DATA_DIR / "active_workspace.json"
DEMO_DIR = ROOT / "demo_corpus"
DEFAULT_MODEL_ENDPOINT = os.getenv("CLAIMCOURT_MODEL_ENDPOINT", "http://127.0.0.1:8000/v1")
DEFAULT_MODEL = os.getenv("CLAIMCOURT_MODEL", "Qwen3-14B")
DEFAULT_ROUTER_ENDPOINT = os.getenv("CLAIMCOURT_ROUTER_ENDPOINT", DEFAULT_MODEL_ENDPOINT)
DEFAULT_ROUTER_MODEL = os.getenv("CLAIMCOURT_ROUTER_MODEL", "")
MAX_REQUEST_BYTES = 35 * 1024 * 1024
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
SUPPORTED_UPLOADS = {".pdf", ".doc", ".docx", ".pptx", ".txt", ".md", ".eml"}


class AppState:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.retriever = LocalRetriever(INDEX_FILE)
        self.cases: dict[str, dict[str, Any]] = {}
        indexed_paths = [str(path.resolve()) for path in self.retriever.paths]
        fallback_root = os.path.commonpath(indexed_paths) if indexed_paths else ""
        try:
            saved_workspace = json.loads(ACTIVE_WORKSPACE_FILE.read_text(encoding="utf-8"))
            self.workspace_root = str(saved_workspace.get("workspace", "")) or fallback_root
        except (OSError, ValueError, TypeError):
            self.workspace_root = fallback_root
        self.last_scan: dict[str, Any] | None = None


STATE = AppState()
_RUNTIME_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_RUNTIME_CACHE_LOCK = threading.Lock()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _page_number(locator: str) -> int:
    match = re.search(r"(?:page|slide)\s+(\d+)", locator, flags=re.IGNORECASE)
    return int(match.group(1)) if match else 1


def _status_for_source(source: str) -> str:
    lowered = source.casefold()
    if any(token in lowered for token in ("draft", "草稿", "讨论稿")):
        return "draft"
    if any(token in lowered for token in ("signed", "正式", "签署")):
        return "signed"
    return "internal"


def _evidence_item(item: Evidence) -> dict[str, Any]:
    return {
        "id": item.citation,
        "filename": item.source,
        "sourcePath": item.source_path,
        "status": _status_for_source(item.source),
        "page": _page_number(item.locator),
        "section": item.locator,
        "score": round(float(item.score), 3),
        "hashVerified": bool(item.source_sha256 and item.evidence_sha256),
        "sha256": item.source_sha256,
        "evidenceSha256": item.evidence_sha256,
        "content": redact_sensitive_text(item.text),
        "matchReasons": list(item.match_reasons),
        "locator": item.locator,
        "parentId": item.parent_id,
        "contextText": redact_sensitive_text(item.context_text),
    }


def _security_item(item: Any) -> dict[str, Any]:
    return {
        "file": item.source,
        "sourcePath": item.source_path,
        "line": int(re.search(r"(\d+)$", item.locator).group(1)) if re.search(r"(\d+)$", item.locator) else 0,
        "type": item.kind,
        "maskedValue": item.redacted_preview,
        "fingerprint": item.fingerprint,
        "score": item.score,
        "matchReasons": item.match_reasons,
    }


def _trajectory(query: str, plan: Any, route: str) -> list[dict[str, str]]:
    topics = ", ".join(plan.topics) or "none"
    artifact = ", ".join(plan.artifact_types) or "document"
    relations = ", ".join(plan.relations) or "none"
    return [
        {"label": "Human Query", "val": query},
        {"label": "Semantic Extraction", "val": f"Topics: [{topics}] | Artifact: [{artifact}]"},
        {"label": "Compiled Route", "val": f"{route} | Relations: [{relations}]"},
    ]


def _intent_payload(query: str, plan: Any, route: str, compiler_mode: str) -> dict[str, Any]:
    return {
        "fuzzyText": query,
        "intentType": plan.intent,
        "topics": list(plan.topics),
        "artifact": ", ".join(plan.artifact_types) or "document",
        "artifactTypes": list(plan.artifact_types),
        "entities": list(plan.entities),
        "timeHints": list(plan.time_hints),
        "memoryClues": ", ".join(plan.memory_signals) or "explicit user request",
        "relation": ", ".join(plan.relations) or "none detected",
        "confidence": round(float(plan.confidence) * 100),
        "trajectory": _trajectory(query, plan, route),
        "expandedTerms": list(plan.expanded_terms),
        "searchScope": list(plan.search_scope),
        "clarificationNeeded": bool(plan.clarification_needed),
        "clarificationQuestion": plan.clarification_question,
        "compiler": compiler_mode,
    }


def _empty_courtroom(status: str, title: str, subtitle: str, next_action: str = "", confidence: int = 0) -> dict[str, Any]:
    return {
        "verdictStatus": status,
        "verdictTitle": title,
        "verdictSubtitle": subtitle,
        "confidence": confidence,
        "prosecution": [],
        "defense": [],
        "citedEvidence": [],
        "timeline": [],
        "missingEvidence": [],
        "nextAction": next_action,
    }


def _courtroom_payload(verdict: dict[str, Any], prosecution: dict[str, Any], defense: dict[str, Any]) -> dict[str, Any]:
    status_map = {
        "supported": "CLAIM CONFIRMED",
        "contradicted": "CLAIM REFUTED",
        "insufficient_evidence": "INSUFFICIENT EVIDENCE",
    }
    timeline = []
    for event in verdict.get("timeline_events", []):
        timeline.append({
            "date": event.get("date", "Undated"),
            "event": event.get("event", ""),
            "status": "CONDITIONAL" if event.get("conditional") else "VALID",
            "citation": event.get("citation", ""),
        })
    return {
        "verdictStatus": status_map.get(verdict.get("verdict"), "INSUFFICIENT EVIDENCE"),
        "verdictCode": verdict.get("verdict", "insufficient_evidence"),
        "verdictTitle": verdict.get("reasoning", ""),
        "verdictSubtitle": verdict.get("reasoning", ""),
        "confidence": round(float(verdict.get("confidence", 0)) * 100),
        "prosecution": [prosecution.get("position", "")] + list(prosecution.get("observations", [])),
        "defense": [defense.get("position", "")] + list(defense.get("observations", [])),
        "citedEvidence": list(verdict.get("evidence_citations", [])),
        "timeline": timeline,
        "missingEvidence": list(verdict.get("missing_evidence", [])),
        "nextAction": verdict.get("recommended_next_action", ""),
    }


def _runtime_payload() -> dict[str, Any]:
    now = time.monotonic()
    cached = _RUNTIME_CACHE.get("value")
    if isinstance(cached, dict) and now < float(_RUNTIME_CACHE.get("expires_at", 0)):
        return dict(cached)
    with _RUNTIME_CACHE_LOCK:
        cached = _RUNTIME_CACHE.get("value")
        if isinstance(cached, dict) and now < float(_RUNTIME_CACHE.get("expires_at", 0)):
            return dict(cached)
        payload = local_runtime_status("vLLM ROCm", DEFAULT_MODEL_ENDPOINT, DEFAULT_MODEL)
        # Keep the configured target visible even when the local endpoint is down.
        payload.setdefault("model", DEFAULT_MODEL)
        # This API only permits loopback model endpoints. Expose the boundary as
        # telemetry rather than making the frontend infer it from a static label.
        payload.setdefault("external_calls", 0)
        _RUNTIME_CACHE["value"] = dict(payload)
        _RUNTIME_CACHE["expires_at"] = time.monotonic() + 30.0
        return payload


def _make_llm() -> Any | None:
    endpoint = DEFAULT_MODEL_ENDPOINT
    model = DEFAULT_MODEL
    try:
        status = local_runtime_status("vLLM ROCm", endpoint, model)
    except Exception:
        return None
    if not status.get("available") or not status.get("model_loaded"):
        return None
    return LocalVLLM(endpoint, model)


def _make_router_llm() -> Any | None:
    if not DEFAULT_ROUTER_MODEL:
        return None
    try:
        status = local_runtime_status("vLLM ROCm", DEFAULT_ROUTER_ENDPOINT, DEFAULT_ROUTER_MODEL)
    except Exception:
        return None
    if not status.get("available") or not status.get("model_loaded"):
        return None
    return LocalVLLM(DEFAULT_ROUTER_ENDPOINT, DEFAULT_ROUTER_MODEL)


def _scan_metadata(scan: Any) -> dict[str, Any]:
    return {
        "root": scan.root,
        "scannedEntries": scan.scanned_entries,
        "files": len(scan.files),
        "totalBytes": scan.total_bytes,
        "skipped": sum(scan.skip_counts.values()),
        "skipCounts": scan.skip_counts,
        "fileLimitReached": scan.file_limit_reached,
        "truncatedDiagnostics": scan.truncated_diagnostics,
        "diagnostics": [asdict(item) for item in scan.skipped[:100]],
    }


def _active_index_counts() -> tuple[int, int]:
    """Return source and chunk counts scoped to the selected workspace."""
    if not STATE.workspace_root:
        return 0, 0
    root = Path(STATE.workspace_root).expanduser().resolve()
    active = []
    for item in STATE.retriever.evidence:
        if not item.source_path:
            continue
        try:
            Path(item.source_path).expanduser().resolve().relative_to(root)
        except (OSError, ValueError):
            continue
        active.append(item)
    return len({item.source_path for item in active}), len(active)


def _can_accumulate_workspace(workspace: str) -> bool:
    """Accumulate only when the loaded evidence is isolated to this workspace."""
    if not STATE.workspace_root:
        return False
    root = Path(workspace).expanduser().resolve()
    try:
        if Path(STATE.workspace_root).expanduser().resolve() != root:
            return False
    except OSError:
        return False
    for item in STATE.retriever.evidence:
        if not item.source_path:
            return False
        try:
            Path(item.source_path).expanduser().resolve().relative_to(root)
        except (OSError, ValueError):
            return False
    return True


def _persist_active_workspace() -> None:
    temporary = ACTIVE_WORKSPACE_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"workspace": STATE.workspace_root}), encoding="utf-8")
    temporary.replace(ACTIVE_WORKSPACE_FILE)
    try:
        os.chmod(ACTIVE_WORKSPACE_FILE, 0o600)
    except OSError:
        pass


def _index_request(payload: dict[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source", "workspace"))
    with STATE.lock:
        if source == "demo":
            paths = list(DEMO_DIR.glob("*"))
            scan = scan_workspace(DEMO_DIR)
            STATE.workspace_root = str(DEMO_DIR.resolve())
            count = STATE.retriever.index_paths(paths, accumulate=False)
        elif source == "uploads":
            # Uploads arrive as base64 payloads and do not have a user-selected
            # directory.  They are stored in the private data directory first,
            # then scanned again below so diagnostics describe the files that
            # were actually indexed.
            upload_root = str(UPLOAD_DIR.resolve())
            accumulate_uploads = _can_accumulate_workspace(upload_root)
            STATE.workspace_root = upload_root
            scan = scan_workspace(UPLOAD_DIR)
            count = 0
        else:
            workspace = str(payload.get("workspace", "")).strip()
            if not workspace:
                raise ValueError("Select a local workspace folder before indexing")
            scan = scan_workspace(Path(workspace))
            accumulate_workspace = _can_accumulate_workspace(scan.root)
            STATE.workspace_root = scan.root
            count = STATE.retriever.index_paths(scan.files, accumulate=accumulate_workspace)
        uploaded: list[str] = []
        for item in payload.get("files", []) or []:
            if not isinstance(item, dict):
                continue
            name = Path(str(item.get("name", ""))).name
            suffix = Path(name).suffix.casefold()
            if not name or suffix not in SUPPORTED_UPLOADS:
                raise ValueError(f"Unsupported upload type: {name or 'unnamed file'}")
            raw = base64.b64decode(str(item.get("contentBase64", "")), validate=True)
            if len(raw) > MAX_UPLOAD_BYTES:
                raise ValueError(f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB: {name}")
            destination = UPLOAD_DIR / f"{uuid.uuid4().hex}_{name}"
            destination.write_bytes(raw)
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
            uploaded.append(str(destination))
        if uploaded:
            count = STATE.retriever.index_paths(
                [Path(item) for item in uploaded],
                accumulate=accumulate_uploads if source == "uploads" else False,
            )
            if source == "uploads":
                scan = scan_workspace(UPLOAD_DIR)
        STATE.last_scan = _scan_metadata(scan) if source != "demo" else _scan_metadata(scan)
        _persist_active_workspace()
        indexed_sources, indexed_chunks = _active_index_counts()
        return {
            "indexedChunks": indexed_chunks,
            "indexedSources": indexed_sources,
            "workspace": STATE.workspace_root,
            "scan": STATE.last_scan,
            "ingestionErrors": STATE.retriever.ingestion_errors[-100:],
            "fts5Active": STATE.retriever.fts5_active,
        }


def _case_payload(query: str, plan: Any, compiler_mode: str, route: str, evidence: list[Evidence], **extra: Any) -> dict[str, Any]:
    case_id = f"case-{uuid.uuid4().hex[:8]}"
    indexed_sources, indexed_chunks = _active_index_counts()
    payload = {
        "id": case_id,
        "title": f"LOCAL INVESTIGATION / {route.upper()}",
        "query": query,
        "route": route,
        "intent": _intent_payload(query, plan, route, compiler_mode),
        "evidenceList": [_evidence_item(item) for item in evidence],
        "courtroom": _empty_courtroom("INSUFFICIENT EVIDENCE", "Awaiting local evidence analysis", "Evidence is available for inspection.", "Review the local evidence packet."),
        "runtime": _runtime_payload(),
        "workspace": STATE.workspace_root,
        "indexedSources": indexed_sources,
        "indexedChunks": indexed_chunks,
        "telemetry": {},
        "status": "ready",
        "securityRecords": [],
        "scan": STATE.last_scan,
    }
    payload.update(extra)
    STATE.cases[case_id] = payload
    return payload


def _investigate(payload: dict[str, Any]) -> dict[str, Any]:
    query = redact_sensitive_text(str(payload.get("query", "")).strip())
    if not query:
        raise ValueError("Query cannot be empty")
    with STATE.lock:
        if not STATE.retriever.evidence:
            raise ValueError("No indexed evidence. Select a workspace or load the demo corpus first.")
        llm = _make_llm() if payload.get("useLocalModel", True) else None
        router_llm = _make_router_llm() if payload.get("useLocalModel", True) else None
        plan, intent_telemetry, compiler_mode = compile_intent(query, router_llm)
        route = route_workspace_request(query, plan)
        if plan.clarification_needed:
            return _case_payload(
                query,
                plan,
                compiler_mode,
                route,
                [],
                status="clarification_needed",
                error=plan.clarification_question,
                courtroom=_empty_courtroom("NEEDS CLARIFICATION", "The recollection is underspecified", plan.clarification_question, "Add a topic, time hint, format, or phrase from the file."),
                telemetry={"intent": intent_telemetry},
            )
        if route == "sensitive_record_scan":
            findings = STATE.retriever.scan_sensitive_records(query)
            case = _case_payload(
                query,
                plan,
                compiler_mode,
                route,
                [],
                status="security_scan",
                securityRecords=[_security_item(item) for item in findings],
                courtroom=_empty_courtroom("SECURITY ALERT", f"{len(findings)} sensitive record(s) located and redacted", "Only paths, line numbers, categories, fingerprints, and masked previews are returned.", "Rotate the credential and replace plaintext values with an environment secret."),
                telemetry={"intent": intent_telemetry, "findings": len(findings)},
            )
            return case
        if route == "file_locator":
            matches = STATE.retriever.locate_files(
                query,
                limit=32 if is_file_inventory_request(query) else 8,
                intent_plan=plan,
            )
            decision = assess_file_matches(query, plan, matches)
            visible_matches = (
                matches
                if decision.status == "multiple_matches"
                else matches[:2]
                if decision.status == "ambiguous"
                else matches[:1]
                if decision.status == "confident"
                else []
            )
            evidence = [item for match in visible_matches for item in match.evidence]
            evidence = list({item.citation: item for item in evidence}.values())
            top = matches[0] if matches and decision.status == "confident" else None
            summary: dict[str, Any] | None = None
            summary_telemetry: dict[str, Any] = {}
            if top and llm:
                all_file_evidence = [item for item in STATE.retriever.evidence if item.source_path == top.source_path]
                try:
                    summary, summary_telemetry = summarize_artifact(query, top, all_file_evidence, llm)
                except (RuntimeError, ValueError, KeyError) as exc:
                    summary_telemetry = {"error": str(exc)}
            if top:
                subtitle = f"Best match: {top.source} ({top.confidence:.0%} confidence)."
                if summary is None:
                    subtitle += " Live local summarizer is unavailable; cited excerpts remain visible."
                courtroom = _empty_courtroom(
                    "FILE LOCATED",
                    f"Located {top.source}",
                    subtitle,
                    "Inspect the cited excerpts before opening or exporting the file.",
                    confidence=round(top.confidence * 100),
                )
            elif decision.status == "ambiguous":
                courtroom = _empty_courtroom(
                    "NEEDS CLARIFICATION",
                    "Several files plausibly match",
                    decision.reason,
                    decision.clarification_question,
                    confidence=round(decision.confidence * 100),
                )
            elif decision.status == "multiple_matches":
                courtroom = _empty_courtroom(
                    "MULTIPLE FILES LOCATED",
                    "A file series or comparison was requested",
                    decision.reason,
                    "Inspect the ranked, cited candidates instead of treating one file as the answer.",
                    confidence=round(decision.confidence * 100),
                )
            else:
                courtroom = _empty_courtroom(
                    "INSUFFICIENT EVIDENCE",
                    "No file satisfies all requested constraints",
                    decision.reason,
                    decision.clarification_question,
                )
            query_id = STATE.retriever.query_history[-1]["query_id"] if STATE.retriever.query_history else ""
            return _case_payload(
                query,
                plan,
                compiler_mode,
                route,
                evidence,
                fileMatches=[{
                    "source": match.source,
                    "sourcePath": match.source_path,
                    "family": match.file_family,
                    "score": match.score,
                    "confidence": match.confidence,
                    "reasons": list(match.reasons),
                    "duplicatePaths": list(match.duplicate_paths),
                    "evidenceIds": [item.citation for item in match.evidence],
                } for match in visible_matches],
                retrievalDecision=asdict(decision),
                retrievalQueryId=query_id,
                artifactSummary=summary,
                status={
                    "confident": "file_located",
                    "ambiguous": "clarification_needed",
                    "multiple_matches": "multiple_files_located",
                    "no_match": "no_match",
                }[decision.status],
                courtroom=courtroom,
                telemetry={"intent": intent_telemetry, "summary": summary_telemetry},
            )
        evidence = STATE.retriever.search(query, limit=8, intent_plan=plan)
        try:
            prosecution, defense, verdict, court_telemetry, mode = run_court(query, evidence, llm=llm, allow_fallback=False)
            courtroom = _courtroom_payload(verdict, prosecution, defense)
            status = "court_ready"
            error = ""
        except (RuntimeError, ValueError) as exc:
            courtroom = _empty_courtroom("MODEL UNAVAILABLE", "Evidence retrieved; local judge is unavailable", str(exc), "Start the local vLLM judge, then run the request again.")
            court_telemetry = {"error": str(exc)}
            mode = "unavailable"
            status = "evidence_ready"
            error = str(exc)
        case = _case_payload(
            query,
            plan,
            compiler_mode,
            route,
            evidence,
            status=status,
            error=error,
            courtroom=courtroom,
            runtime={
                **_runtime_payload(),
                "tokens_per_second": court_telemetry.get("tokens_per_second", 0),
                "first_token_latency_seconds": court_telemetry.get("first_token_latency_seconds", 0),
                "end_to_end_latency_seconds": court_telemetry.get("latency_seconds", 0),
                "completion_tokens": court_telemetry.get("completion_tokens", 0),
            },
            telemetry={"intent": intent_telemetry, "court": court_telemetry, "mode": mode},
        )
        if status == "court_ready":
            case["verdict"] = verdict
        return case


class ClaimCourtHandler(SimpleHTTPRequestHandler):
    server_version = "ClaimCourtLocal/1.0"

    @property
    def static_directory(self) -> Path | None:
        return getattr(self.server, "static_directory", None)

    def _headers(self, status: int, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(_json_safe(payload), ensure_ascii=False).encode("utf-8")
        self._headers(status)
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_REQUEST_BYTES:
            raise ValueError("Request exceeds the local API size limit")
        raw = self.rfile.read(length)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def do_OPTIONS(self) -> None:
        self._headers(204)

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/api/health":
                indexed_sources, indexed_chunks = _active_index_counts()
                self._send_json(200, {"success": True, "data": {"runtime": _runtime_payload(), "workspace": STATE.workspace_root, "indexedSources": indexed_sources, "indexedChunks": indexed_chunks}})
                return
            if path == "/api/index":
                indexed_sources, indexed_chunks = _active_index_counts()
                self._send_json(200, {"success": True, "data": {"workspace": STATE.workspace_root, "indexedSources": indexed_sources, "indexedChunks": indexed_chunks, "scan": STATE.last_scan}})
                return
            if self.static_directory:
                relative = path.lstrip("/") or "index.html"
                candidate = (self.static_directory / relative).resolve()
                if candidate.is_file() and str(candidate).startswith(str(self.static_directory.resolve())):
                    data = candidate.read_bytes()
                    self._headers(200, mimetypes.guess_type(str(candidate))[0] or "application/octet-stream")
                    self.wfile.write(data)
                    return
                index = self.static_directory / "index.html"
                if index.is_file():
                    self._headers(200, "text/html; charset=utf-8")
                    self.wfile.write(index.read_bytes())
                    return
            self._send_json(404, {"success": False, "error": "Not found"})
        except Exception as exc:
            self._send_json(500, {"success": False, "error": str(exc)})

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            payload = self._read_json()
            if path == "/api/index":
                result = _index_request(payload)
                self._send_json(200, {"success": True, "data": result})
                return
            if path == "/api/investigate":
                result = _investigate(payload)
                self._send_json(200, {"success": True, "data": result})
                return
            if path == "/api/feedback":
                case_id = str(payload.get("caseId", ""))
                case = STATE.cases.get(case_id)
                if not case or not case.get("retrievalQueryId"):
                    self._send_json(409, {"success": False, "error": "The case has no local retrieval query to review"})
                    return
                selected_source = str(payload.get("selectedSourcePath", "")).strip() or None
                relevant = payload.get("relevant")
                if not isinstance(relevant, bool):
                    raise ValueError("Feedback relevance must be true or false")
                feedback = STATE.retriever.record_feedback(
                    str(case["retrievalQueryId"]),
                    selected_source,
                    relevant,
                )
                self._send_json(200, {"success": True, "data": feedback})
                return
            if path == "/api/export":
                if payload.get("approved") is not True:
                    self._send_json(400, {"success": False, "error": "Explicit export approval is required"})
                    return
                case_id = str(payload.get("caseId", ""))
                case = STATE.cases.get(case_id)
                if not case or not case.get("verdict"):
                    self._send_json(409, {"success": False, "error": "Only a completed local court record can be exported"})
                    return
                evidence = [item for item in STATE.retriever.evidence if item.citation in set(case["verdict"].get("evidence_citations", []))]
                brief = markdown_brief(case["verdict"], evidence)
                destination = EXPORT_DIR / f"ClaimCourt_{case_id}_{uuid.uuid4().hex[:8]}.md"
                destination.write_text(brief, encoding="utf-8")
                try:
                    os.chmod(destination, 0o600)
                except OSError:
                    pass
                self._send_json(200, {"success": True, "data": {"path": str(destination), "content": brief}})
                return
            self._send_json(404, {"success": False, "error": "Not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"success": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"success": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[claimcourt-api] {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8503)
    parser.add_argument("--static", type=Path, default=None)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ClaimCourtHandler)
    server.static_directory = args.static.resolve() if args.static else None
    print(f"ClaimCourt local API listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
