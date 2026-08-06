from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from agent_factory.models.embedding_model import get_embedding_model
from agent_factory.paths import factory_artifact_path, system_package_root as default_system_package_root
from agent_factory.sqlite_runtime import initialize_sqlite_store, sqlite_session
from agent_factory.tooling.extension_registry import selected_registry_configs


AGENT_REGISTRY_DB_ENV = "AGENTFACTORY_AGENT_REGISTRY_DB"
DEFAULT_LIMIT = 5
MAX_LIMIT = 10
SQLITE_BUSY_TIMEOUT_MS = 10000
_REFRESH_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class AgentIndexDocument:
    package_id: str
    package_path: Path
    fingerprint: str
    agent_name: str
    description: str
    pattern_id: str
    agent_card: dict[str, Any]
    document_text: str


class AgentRegistryService:
    def __init__(
        self,
        *,
        package_root: str | Path | None = None,
        system_package_root: str | Path | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self.package_root = Path(package_root).expanduser() if package_root else factory_artifact_path("packages")
        self.system_package_root = (
            Path(system_package_root).expanduser()
            if system_package_root is not None
            else (default_system_package_root() if package_root is None else None)
        )
        self.db_path = Path(db_path).expanduser() if db_path else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        initialize_sqlite_store(
            self.db_path,
            self._ensure_schema,
            timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            wal=True,
        )

    def refresh_index(self) -> dict[str, Any]:
        with _REFRESH_LOCK:
            return self._refresh_index()

    def _refresh_index(self) -> dict[str, Any]:
        documents = _scan_package_documents(self._package_roots())
        embedding_model = _embedding_model_or_none()
        embedding_available = embedding_model is not None
        indexed = 0
        package_ids = {document.package_id for document in documents}
        with self._connect() as conn:
            existing_rows = conn.execute(
                "select package_id, fingerprint, embedding_json from agent_search_documents"
            ).fetchall()
        existing = {
            str(row["package_id"]): (
                str(row["fingerprint"] or ""),
                _embedding_from_json(row["embedding_json"]),
            )
            for row in existing_rows
        }
        indexed_documents: list[tuple[AgentIndexDocument, list[float] | None]] = []
        for document in documents:
            embedding = None
            if embedding_model is not None:
                cached_fingerprint, existing_embedding = existing.get(document.package_id, ("", None))
                if cached_fingerprint != document.fingerprint or not existing_embedding:
                    embedding = _embed_document(embedding_model, document.document_text)
                else:
                    embedding = existing_embedding
            indexed_documents.append((document, embedding))
        with self._connect() as conn:
            for document, embedding in indexed_documents:
                self._upsert_document(conn, document, embedding)
                indexed += 1
            if package_ids:
                placeholders = ", ".join("?" for _ in package_ids)
                conn.execute(
                    f"delete from agent_search_documents where package_id not in ({placeholders})",
                    tuple(sorted(package_ids)),
                )
            else:
                conn.execute("delete from agent_search_documents")
        return {
            "status": "completed",
            "indexed_count": indexed,
            "embedding_available": embedding_available,
            "updated_at": _now(),
        }

    def refresh_package(self, package_id: str) -> dict[str, Any]:
        package_id = _clean_text(package_id)
        if not package_id:
            return self.refresh_index()
        package_path = self._package_path(package_id)
        with self._connect() as conn:
            if package_path is None:
                conn.execute("delete from agent_search_documents where package_id = ?", (package_id,))
                return {"status": "removed", "package_id": package_id, "updated_at": _now()}
        return self.refresh_index()

    def _package_roots(self) -> list[Path]:
        roots = [self.package_root]
        if self.system_package_root is not None:
            roots.insert(0, self.system_package_root)
        return roots

    def _package_path(self, package_id: str) -> Path | None:
        for root in reversed(self._package_roots()):
            candidate = root / package_id
            if candidate.is_dir():
                return candidate
        return None

    def search(self, *, query: str, limit: int | None = None) -> dict[str, Any]:
        query = _clean_text(query)
        if not query:
            raise ValueError("agent_search query is required")
        self.refresh_index()
        limit = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))
        query_embedding = _query_embedding(query)
        rows = self._load_documents()
        candidates = [
            _score_candidate(row, query=query, query_embedding=query_embedding)
            for row in rows
        ]
        candidates = [candidate for candidate in candidates if float(candidate.get("score") or 0) > 0]
        candidates.sort(key=lambda item: item["score"], reverse=True)
        candidates = candidates[:limit]
        status = "matched" if candidates else "no_suitable_agent"
        output: dict[str, Any] = {
            "status": status,
            "query": query,
            "candidates": candidates,
            "embedding_used": query_embedding is not None,
            "message": _search_message(status, len(candidates)),
        }
        if status == "no_suitable_agent":
            output["manufacturing_recommendation"] = _manufacturing_recommendation(query=query)
        return output

    def list_agents(self, *, limit: int | None = None) -> dict[str, Any]:
        self.refresh_index()
        limit = max(1, min(100, int(limit or 100)))
        agents = [_agent_list_item(row) for row in self._load_documents()[:limit]]
        return {
            "status": "completed",
            "agents": agents,
            "count": len(agents),
            "message": f"列出 {len(agents)} 个已发布 Agent。",
        }

    def _load_documents(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                select * from agent_search_documents
                order by agent_name asc, package_id asc
                """
            ).fetchall()

    def _upsert_document(
        self,
        conn: sqlite3.Connection,
        document: AgentIndexDocument,
        embedding: list[float] | None,
    ) -> None:
        conn.execute(
            """
            insert into agent_search_documents (
              package_id, package_path, fingerprint, agent_name, description,
              pattern_id, agent_card_json, document_text, embedding_json, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(package_id) do update set
              package_path = excluded.package_path,
              fingerprint = excluded.fingerprint,
              agent_name = excluded.agent_name,
              description = excluded.description,
              pattern_id = excluded.pattern_id,
              agent_card_json = excluded.agent_card_json,
              document_text = excluded.document_text,
              embedding_json = excluded.embedding_json,
              updated_at = excluded.updated_at
            """,
            (
                document.package_id,
                str(document.package_path),
                document.fingerprint,
                document.agent_name,
                document.description,
                document.pattern_id,
                _json_dumps(document.agent_card),
                document.document_text,
                _json_dumps(embedding) if embedding else "",
                _now(),
            ),
        )

    def _ensure_schema(self) -> None:
        expected_columns = {
            "package_id",
            "package_path",
            "fingerprint",
            "agent_name",
            "description",
            "pattern_id",
            "agent_card_json",
            "document_text",
            "embedding_json",
            "updated_at",
        }
        with self._connect() as conn:
            existing = conn.execute("pragma table_info(agent_search_documents)").fetchall()
            if existing and {str(row["name"]) for row in existing} != expected_columns:
                conn.execute("drop table agent_search_documents")
            conn.execute(
                """
                create table if not exists agent_search_documents (
                  package_id text primary key,
                  package_path text not null,
                  fingerprint text not null,
                  agent_name text not null,
                  description text not null,
                  pattern_id text not null,
                  agent_card_json text not null,
                  document_text text not null,
                  embedding_json text not null,
                  updated_at text not null
                )
                """
            )

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return sqlite_session(self.db_path, timeout_ms=SQLITE_BUSY_TIMEOUT_MS)


def search_agents(arguments: dict[str, Any]) -> dict[str, Any]:
    return AgentRegistryService().search(
        query=str(arguments.get("query") or ""),
        limit=_optional_int(arguments.get("limit")),
    )


def list_agents(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    arguments = arguments or {}
    return AgentRegistryService().list_agents(limit=_optional_int(arguments.get("limit")))


def refresh_agent_registry_index(package_id: str | None = None) -> dict[str, Any]:
    service = AgentRegistryService()
    if package_id:
        return service.refresh_package(package_id)
    return service.refresh_index()


def _scan_package_documents(package_roots: list[Path]) -> list[AgentIndexDocument]:
    documents_by_id: dict[str, AgentIndexDocument] = {}
    for package_root in package_roots:
        if not package_root.is_dir():
            continue
        for package_path in sorted(path for path in package_root.iterdir() if path.is_dir()):
            document = _package_document(package_path)
            if document is not None:
                documents_by_id[document.package_id] = document
    return [documents_by_id[package_id] for package_id in sorted(documents_by_id)]


def _package_document(package_path: Path) -> AgentIndexDocument | None:
    manifest = _read_json(package_path / "agent_package.json")
    if not manifest:
        return None
    agent = manifest.get("agent") if isinstance(manifest.get("agent"), dict) else {}
    package_id = _clean_text(agent.get("id") or package_path.name)
    if not package_id or package_id == "factory_chat":
        return None
    assembly = _read_json(package_path / "assembly_spec.json")
    report = _read_json(package_path / "package_report.json")
    agent_name = _clean_text(agent.get("name") or package_id)
    description = _clean_text(agent.get("description") or "")
    pattern_id = _clean_text((manifest.get("runtime") or {}).get("pattern_id") if isinstance(manifest.get("runtime"), dict) else "")
    agent_card = _agent_card(
        package_id=package_id,
        agent_name=agent_name,
        description=description,
        pattern_id=pattern_id,
        tools=_tool_summaries(assembly),
        skills=_skill_summaries(package_path),
        mcp_servers=_mcp_summaries(package_path),
        knowledge_sources=[],
        report=report,
    )
    document_text = _agent_card_text(agent_card)
    return AgentIndexDocument(
        package_id=package_id,
        package_path=package_path,
        fingerprint=_package_fingerprint(package_path),
        agent_name=agent_name,
        description=description,
        pattern_id=pattern_id,
        agent_card=agent_card,
        document_text=document_text,
    )


def _agent_card(
    *,
    package_id: str,
    agent_name: str,
    description: str,
    pattern_id: str,
    tools: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    mcp_servers: list[dict[str, Any]],
    knowledge_sources: list[dict[str, Any]],
    report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "package_id": package_id,
        "name": agent_name,
        "description": description,
        "runtime": {"pattern_id": pattern_id},
        "skills": skills,
        "tools": tools,
        "mcp_servers": mcp_servers,
        "knowledge_sources": knowledge_sources,
        "report_summary": _report_summary(report),
    }


def _agent_card_text(agent_card: dict[str, Any]) -> str:
    return json.dumps(agent_card, ensure_ascii=False, sort_keys=True)


def _tool_summaries(assembly: dict[str, Any]) -> list[dict[str, Any]]:
    tools = assembly.get("tools") if isinstance(assembly.get("tools"), list) else []
    result: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        tool_id = _clean_text(tool.get("id") or tool.get("name"))
        if not tool_id:
            continue
        result.append(
            {
                "id": tool_id,
                "description": _clean_text(tool.get("description")),
            }
        )
    return result


def _skill_summaries(package_path: Path) -> list[dict[str, Any]]:
    _, skills, _ = selected_registry_configs([package_path / "extensions"])
    result: list[dict[str, Any]] = []
    for skill in skills.skills:
        skill_dir = Path(skill.path).expanduser().resolve()
        meta = _read_json(skill_dir / "_meta.json")
        skill_md = skill_dir / "SKILL.md"
        description = _clean_text(meta.get("description") if meta else "")
        if not description and skill_md.is_file():
            description = _skill_markdown_summary(skill_md)
        result.append(
            {
                "name": _clean_text(meta.get("name") if meta else "") or skill.skill_id,
                "description": description,
                "enabled": skill.enabled,
            }
        )
    return result


def _mcp_summaries(package_path: Path) -> list[dict[str, Any]]:
    mcp, _, _ = selected_registry_configs([package_path / "extensions"])
    result: list[dict[str, Any]] = []
    for server in mcp.servers:
        result.append(
            {
                "server_id": server.server_id,
                "tool_id_prefix": _clean_text(server.tool_id_prefix),
                "enabled": server.enabled,
            }
        )
    return result


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: report.get(key)
        for key in ("summary", "description", "validation", "created_at")
        if report.get(key)
    }


def _score_candidate(
    row: sqlite3.Row,
    *,
    query: str,
    query_embedding: list[float] | None,
) -> dict[str, Any]:
    embedding_score = 0.0
    has_candidate_embedding = False
    if query_embedding is not None:
        embedding = _embedding_from_json(row["embedding_json"])
        if embedding:
            has_candidate_embedding = True
            embedding_score = max(0.0, _cosine_similarity(query_embedding, embedding))
    text_score, reasons = _keyword_score(query, row["document_text"], row["agent_name"], row["description"])
    score = embedding_score if has_candidate_embedding else text_score
    agent_card = _json_loads(row["agent_card_json"], {})
    return {
        "package_id": row["package_id"],
        "agent_name": row["agent_name"],
        "description": row["description"],
        "score": round(min(1.0, score), 4),
        "match_reasons": reasons,
        "pattern_id": row["pattern_id"],
        "agent_card": agent_card,
    }


def _agent_list_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "package_id": row["package_id"],
        "agent_name": row["agent_name"],
        "description": row["description"],
        "pattern_id": row["pattern_id"],
        "agent_card": _json_loads(row["agent_card_json"], {}),
    }


def _keyword_score(query: str, document: str, name: str, description: str) -> tuple[float, list[str]]:
    query_terms = _query_terms(query)
    if not query_terms:
        return 0.0, []
    doc_text = _normalize_search_text(document)
    name_text = _normalize_search_text(name)
    description_text = _normalize_search_text(description)
    matched = [term for term in query_terms if term in doc_text]
    name_matches = [term for term in query_terms if term in name_text]
    description_matches = [term for term in query_terms if term in description_text]
    score = len(matched) / max(1, len(query_terms))
    reasons = []
    if name_matches:
        reasons.append("名称文本匹配：" + "、".join(name_matches[:4]))
    if description_matches:
        reasons.append("描述文本匹配：" + "、".join(description_matches[:4]))
    if matched and not reasons:
        reasons.append("Agent Card 文本匹配：" + "、".join(matched[:4]))
    return min(1.0, score), reasons


def _query_terms(query: str) -> list[str]:
    text = _normalize_search_text(query)
    return sorted(set(item for item in text.split(" ") if item))


def _search_message(status: str, count: int) -> str:
    if status == "matched":
        return f"召回 {count} 个 Agent Card 候选。"
    return "没有可检索的 Agent Card。"


def _manufacturing_recommendation(*, query: str) -> dict[str, Any]:
    return {
        "should_create_agent": True,
        "suggested_purpose": query,
        "required_brief_fields": [
            "agent_name",
            "purpose",
            "target_tasks",
            "delivery_standards",
            "reason_existing_agents_insufficient",
        ],
    }


def _query_embedding(query: str) -> list[float] | None:
    model = _embedding_model_or_none()
    if model is None:
        return None
    try:
        return [float(item) for item in model.embed_query(query)]
    except Exception:
        return None


def _embedding_model_or_none() -> Any:
    try:
        return get_embedding_model()
    except Exception:
        return None


def _embed_document(model: Any, document_text: str) -> list[float] | None:
    try:
        return [float(item) for item in model.embed_query(document_text)]
    except Exception:
        return None


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _package_fingerprint(package_path: Path) -> str:
    latest = 0
    size = 0
    for path in package_path.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        latest = max(latest, int(stat.st_mtime_ns))
        size += int(stat.st_size)
    return f"{latest}:{size}"


def _skill_markdown_summary(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = [line.strip("# \t") for line in text.splitlines() if line.strip()]
    return _clean_text(" ".join(lines[:4]))[:500]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except json.JSONDecodeError:
        return default


def _embedding_from_json(value: Any) -> list[float] | None:
    embedding = _json_loads(value, None)
    if not isinstance(embedding, list) or not embedding:
        return None
    try:
        return [float(item) for item in embedding]
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_search_text(value: str) -> str:
    return _clean_text(value).lower().replace("-", "_")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _default_db_path() -> Path:
    configured = os.getenv(AGENT_REGISTRY_DB_ENV)
    if configured:
        return Path(configured).expanduser()
    return factory_artifact_path("agent_registry", "agent_registry.sqlite")
