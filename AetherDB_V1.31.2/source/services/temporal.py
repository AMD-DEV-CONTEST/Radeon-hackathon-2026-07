"""Partial-order temporal anchors and relations for authored story time."""

from __future__ import annotations

import hashlib
import json
import uuid

from services.audit_log import log_event
from services.db import get_db


class TemporalError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


def _main_timeline_id(book_id: str) -> str:
    digest = hashlib.sha256(book_id.encode("utf-8")).hexdigest()[:16].upper()
    return f"TL_MAIN_{digest}"


def _ensure_book_and_timeline(db, book_id: str, timeline_id: str | None = None) -> str:
    if not db.execute("SELECT 1 FROM books WHERE book_id=?", (book_id,)).fetchone():
        raise TemporalError("BOOK_NOT_FOUND", "Target book does not exist")
    if timeline_id:
        row = db.execute(
            "SELECT id FROM timelines WHERE id=? AND book_id=? AND status!='deleted'",
            (timeline_id, book_id),
        ).fetchone()
        if not row:
            raise TemporalError("TIMELINE_NOT_FOUND", "Timeline does not belong to the target book")
        return timeline_id
    timeline_id = _main_timeline_id(book_id)
    db.execute(
        "INSERT OR IGNORE INTO timelines(id,book_id,name,status,is_default) VALUES(?,?,'Main timeline','active',1)",
        (timeline_id, book_id),
    )
    return timeline_id


def create_timeline(payload: dict) -> dict:
    db = get_db(payload["database_id"])
    try:
        _ensure_book_and_timeline(db, payload["book_id"])
        parent_id = payload.get("parent_timeline_id")
        if parent_id:
            _ensure_book_and_timeline(db, payload["book_id"], parent_id)
            _scope_anchor(
                db,
                payload["divergence_anchor_id"],
                payload["book_id"],
                parent_id,
                None,
            )
        timeline_id = f"TL_{uuid.uuid4().hex[:24].upper()}"
        db.execute(
            "INSERT INTO timelines(id,book_id,name,parent_timeline_id,divergence_anchor_id,status,is_default) "
            "VALUES(?,?,?,?,?,?,0)",
            (
                timeline_id,
                payload["book_id"],
                payload["name"],
                parent_id,
                payload.get("divergence_anchor_id"),
                payload.get("status", "active"),
            ),
        )
        db.commit()
        return dict(db.execute("SELECT * FROM timelines WHERE id=?", (timeline_id,)).fetchone())
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_timelines(database_id: str, book_id: str):
    db = get_db(database_id)
    try:
        _ensure_book_and_timeline(db, book_id)
        db.commit()
        rows = db.execute(
            "SELECT * FROM timelines WHERE book_id=? AND status!='deleted' ORDER BY is_default DESC,created_at,id",
            (book_id,),
        ).fetchall()
        return {"timelines": [dict(row) for row in rows]}
    finally:
        db.close()


def set_event_metadata(event_id: str, payload: dict) -> dict:
    db = get_db(payload["database_id"])
    try:
        _ensure_book_and_timeline(db, payload["book_id"], payload["timeline_id"])
        if not db.execute(
            "SELECT 1 FROM timeline_events WHERE CAST(id AS TEXT)=? AND book_id=?",
            (event_id, payload["book_id"]),
        ).fetchone():
            raise TemporalError("EVENT_NOT_FOUND", "Timeline event does not belong to the target book")
        if payload.get("world_anchor_id"):
            _scope_anchor(
                db,
                payload["world_anchor_id"],
                payload["book_id"],
                payload["timeline_id"],
                payload.get("branch_id"),
            )
        if payload.get("viewpoint_entity_id") and not db.execute(
            "SELECT 1 FROM entities WHERE entity_id=? AND book_id=? AND is_active=1",
            (payload["viewpoint_entity_id"], payload["book_id"]),
        ).fetchone():
            raise TemporalError("ENTITY_NOT_FOUND", "Viewpoint entity does not belong to the target book")
        if payload.get("causal_parent_event_id") and not db.execute(
            "SELECT 1 FROM timeline_events WHERE CAST(id AS TEXT)=? AND book_id=?",
            (payload["causal_parent_event_id"], payload["book_id"]),
        ).fetchone():
            raise TemporalError("EVENT_NOT_FOUND", "Causal parent event does not belong to the target book")
        db.execute(
            "INSERT INTO temporal_event_metadata("
            "event_id,book_id,timeline_id,branch_id,world_anchor_id,subjective_sequence,"
            "viewpoint_entity_id,causal_parent_event_id) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(event_id) DO UPDATE SET book_id=excluded.book_id,timeline_id=excluded.timeline_id,"
            "branch_id=excluded.branch_id,world_anchor_id=excluded.world_anchor_id,"
            "subjective_sequence=excluded.subjective_sequence,viewpoint_entity_id=excluded.viewpoint_entity_id,"
            "causal_parent_event_id=excluded.causal_parent_event_id,updated_at=CURRENT_TIMESTAMP",
            (
                event_id,
                payload["book_id"],
                payload["timeline_id"],
                payload.get("branch_id"),
                payload.get("world_anchor_id"),
                payload.get("subjective_sequence"),
                payload.get("viewpoint_entity_id"),
                payload.get("causal_parent_event_id"),
            ),
        )
        db.commit()
        return dict(db.execute("SELECT * FROM temporal_event_metadata WHERE event_id=?", (event_id,)).fetchone())
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_event_metadata(database_id: str, book_id: str, event_id: str):
    db = get_db(database_id)
    try:
        if not db.execute(
            "SELECT 1 FROM timeline_events WHERE CAST(id AS TEXT)=? AND book_id=?",
            (event_id, book_id),
        ).fetchone():
            raise TemporalError("EVENT_NOT_FOUND", "Timeline event does not belong to the target book")
        row = db.execute("SELECT * FROM temporal_event_metadata WHERE event_id=?", (event_id,)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def create_anchor(payload: dict) -> dict:
    db = get_db(payload["database_id"])
    try:
        timeline_id = _ensure_book_and_timeline(db, payload["book_id"], payload.get("timeline_id"))
        if payload.get("chapter_id") and not db.execute(
            "SELECT 1 FROM chapters WHERE chapter_id=? AND book_id=? AND is_active=1",
            (payload["chapter_id"], payload["book_id"]),
        ).fetchone():
            raise TemporalError("CHAPTER_NOT_FOUND", "Anchor chapter does not belong to the target book")
        if payload.get("event_id") and not db.execute(
            "SELECT 1 FROM timeline_events WHERE CAST(id AS TEXT)=? AND book_id=?",
            (payload["event_id"], payload["book_id"]),
        ).fetchone():
            raise TemporalError("EVENT_NOT_FOUND", "Anchor event does not belong to the target book")
        anchor_id = f"TA_{uuid.uuid4().hex[:24].upper()}"
        db.execute(
            "INSERT INTO temporal_anchors("
            "id,book_id,timeline_id,branch_id,anchor_type,label,chapter_id,event_id,phase_id,"
            "absolute_time,order_hint,confidence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                anchor_id,
                payload["book_id"],
                timeline_id,
                payload.get("branch_id"),
                payload["anchor_type"],
                payload["label"],
                payload.get("chapter_id"),
                payload.get("event_id"),
                payload.get("phase_id"),
                payload.get("absolute_time"),
                payload.get("order_hint"),
                payload.get("confidence", "confirmed"),
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM temporal_anchors WHERE id=?", (anchor_id,)).fetchone()
        log_event(
            db,
            "temporal.anchor.create",
            f"Temporal anchor {anchor_id} created",
            target=anchor_id,
            database_id=payload["database_id"],
            book_id=payload["book_id"],
        )
        return dict(row)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_anchors(database_id: str, book_id: str, timeline_id: str | None = None, branch_id: str | None = None):
    db = get_db(database_id)
    try:
        timeline_id = _ensure_book_and_timeline(db, book_id, timeline_id)
        db.commit()
        rows = db.execute(
            "SELECT * FROM temporal_anchors WHERE book_id=? AND timeline_id=? "
            "AND ((branch_id IS NULL AND ? IS NULL) OR branch_id=?) "
            "ORDER BY order_hint IS NULL,order_hint,created_at,id",
            (book_id, timeline_id, branch_id, branch_id),
        ).fetchall()
        return {"timeline_id": timeline_id, "branch_id": branch_id, "anchors": [dict(row) for row in rows]}
    finally:
        db.close()


def _edge(relation_type: str, source: str, target: str):
    if relation_type in {"before", "approximately_before"}:
        return source, target
    if relation_type in {"after", "approximately_after"}:
        return target, source
    return None


def _would_cycle(db, timeline_id: str, branch_id: str | None, edge: tuple[str, str]) -> bool:
    rows = db.execute(
        "SELECT source_anchor_id,relation_type,target_anchor_id FROM temporal_relations "
        "WHERE timeline_id=? AND ((branch_id IS NULL AND ? IS NULL) OR branch_id=?) "
        "AND review_status!='rejected' AND confidence!='conflicting'",
        (timeline_id, branch_id, branch_id),
    ).fetchall()
    graph: dict[str, set[str]] = {}
    for row in rows:
        existing = _edge(row["relation_type"], row["source_anchor_id"], row["target_anchor_id"])
        if existing:
            graph.setdefault(existing[0], set()).add(existing[1])
    graph.setdefault(edge[0], set()).add(edge[1])
    stack = [edge[1]]
    seen = set()
    while stack:
        current = stack.pop()
        if current == edge[0]:
            return True
        if current not in seen:
            seen.add(current)
            stack.extend(graph.get(current, ()))
    return False


def create_relation(payload: dict) -> dict:
    db = get_db(payload["database_id"])
    try:
        timeline_id = _ensure_book_and_timeline(db, payload["book_id"], payload["timeline_id"])
        if payload.get("source_chapter_id") and not db.execute(
            "SELECT 1 FROM chapters WHERE chapter_id=? AND book_id=? AND is_active=1",
            (payload["source_chapter_id"], payload["book_id"]),
        ).fetchone():
            raise TemporalError("CHAPTER_NOT_FOUND", "Source chapter does not belong to the target book")
        placeholders = (payload["source_anchor_id"], payload["target_anchor_id"])
        rows = db.execute(
            "SELECT * FROM temporal_anchors WHERE id IN (?,?)",
            placeholders,
        ).fetchall()
        anchors = {row["id"]: row for row in rows}
        if set(anchors) != set(placeholders):
            raise TemporalError("ANCHOR_NOT_FOUND", "One or more temporal anchors do not exist")
        for anchor in anchors.values():
            if (
                anchor["book_id"] != payload["book_id"]
                or anchor["timeline_id"] != timeline_id
                or anchor["branch_id"] != payload.get("branch_id")
            ):
                raise TemporalError("TEMPORAL_SCOPE_MISMATCH", "Temporal anchors must share the same book, timeline, and branch")
        edge = _edge(payload["relation_type"], *placeholders)
        conflict = bool(edge and _would_cycle(db, timeline_id, payload.get("branch_id"), edge))
        confidence = "conflicting" if conflict else payload.get("confidence", "confirmed")
        review_status = "pending" if conflict else "accepted"
        existing = db.execute(
            "SELECT * FROM temporal_relations WHERE timeline_id=? "
            "AND ((branch_id IS NULL AND ? IS NULL) OR branch_id=?) "
            "AND source_anchor_id=? AND relation_type=? AND target_anchor_id=?",
            (
                timeline_id,
                payload.get("branch_id"),
                payload.get("branch_id"),
                payload["source_anchor_id"],
                payload["relation_type"],
                payload["target_anchor_id"],
            ),
        ).fetchone()
        if existing:
            relation = dict(existing)
            relation["cycle_detected"] = relation["confidence"] == "conflicting"
            relation["requires_confirmation"] = relation["review_status"] == "pending"
            return relation
        relation_id = f"TR_{uuid.uuid4().hex[:24].upper()}"
        db.execute(
            "INSERT INTO temporal_relations("
            "id,book_id,timeline_id,branch_id,source_anchor_id,relation_type,target_anchor_id,"
            "confidence,source_chapter_id,review_status) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                relation_id,
                payload["book_id"],
                timeline_id,
                payload.get("branch_id"),
                payload["source_anchor_id"],
                payload["relation_type"],
                payload["target_anchor_id"],
                confidence,
                payload.get("source_chapter_id"),
                review_status,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM temporal_relations WHERE id=?", (relation_id,)).fetchone()
        log_event(
            db,
            "temporal.relation.create",
            f"Temporal relation {relation_id} created",
            target=relation_id,
            database_id=payload["database_id"],
            book_id=payload["book_id"],
            severity="warning" if conflict else "info",
        )
        relation = dict(row)
        relation["cycle_detected"] = conflict
        relation["requires_confirmation"] = conflict
        return relation
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_relations(database_id: str, book_id: str, timeline_id: str, branch_id: str | None = None):
    db = get_db(database_id)
    try:
        _ensure_book_and_timeline(db, book_id, timeline_id)
        rows = db.execute(
            "SELECT * FROM temporal_relations WHERE book_id=? AND timeline_id=? "
            "AND ((branch_id IS NULL AND ? IS NULL) OR branch_id=?) ORDER BY created_at,id",
            (book_id, timeline_id, branch_id, branch_id),
        ).fetchall()
        return {"timeline_id": timeline_id, "branch_id": branch_id, "relations": [dict(row) for row in rows]}
    finally:
        db.close()


def _scope_anchor(db, anchor_id: str, book_id: str, timeline_id: str, branch_id: str | None):
    row = db.execute("SELECT * FROM temporal_anchors WHERE id=?", (anchor_id,)).fetchone()
    if not row:
        raise TemporalError("ANCHOR_NOT_FOUND", "Temporal anchor does not exist")
    if row["book_id"] != book_id or row["timeline_id"] != timeline_id or row["branch_id"] != branch_id:
        raise TemporalError("TEMPORAL_SCOPE_MISMATCH", "Temporal anchor does not match the requested context")
    return row


def set_chapter_context(chapter_id: str, payload: dict) -> dict:
    db = get_db(payload["database_id"])
    try:
        chapter = db.execute(
            "SELECT * FROM chapters WHERE chapter_id=? AND book_id=? AND is_active=1",
            (chapter_id, payload["book_id"]),
        ).fetchone()
        if not chapter:
            raise TemporalError("CHAPTER_NOT_FOUND", "Chapter does not belong to the target book")
        timeline_id = _ensure_book_and_timeline(db, payload["book_id"], payload.get("timeline_id"))
        if payload.get("anchor_id"):
            _scope_anchor(db, payload["anchor_id"], payload["book_id"], timeline_id, payload.get("branch_id"))
        if payload.get("viewpoint_entity_id") and not db.execute(
            "SELECT 1 FROM entities WHERE entity_id=? AND book_id=? AND is_active=1",
            (payload["viewpoint_entity_id"], payload["book_id"]),
        ).fetchone():
            raise TemporalError("ENTITY_NOT_FOUND", "Viewpoint entity does not belong to the target book")
        db.execute(
            "INSERT INTO chapter_temporal_contexts("
            "chapter_id,book_id,timeline_id,branch_id,anchor_id,phase_id,viewpoint_entity_id,include_future_knowledge) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(chapter_id) DO UPDATE SET "
            "book_id=excluded.book_id,timeline_id=excluded.timeline_id,branch_id=excluded.branch_id,"
            "anchor_id=excluded.anchor_id,phase_id=excluded.phase_id,viewpoint_entity_id=excluded.viewpoint_entity_id,"
            "include_future_knowledge=excluded.include_future_knowledge,updated_at=CURRENT_TIMESTAMP",
            (
                chapter_id,
                payload["book_id"],
                timeline_id,
                payload.get("branch_id"),
                payload.get("anchor_id"),
                payload.get("phase_id"),
                payload.get("viewpoint_entity_id"),
                int(payload.get("include_future_knowledge", False)),
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM chapter_temporal_contexts WHERE chapter_id=?", (chapter_id,)).fetchone()
        result = dict(row)
        result["include_future_knowledge"] = bool(result["include_future_knowledge"])
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_chapter_context(database_id: str, book_id: str, chapter_id: str) -> dict:
    db = get_db(database_id)
    try:
        chapter = db.execute(
            "SELECT 1 FROM chapters WHERE chapter_id=? AND book_id=? AND is_active=1",
            (chapter_id, book_id),
        ).fetchone()
        if not chapter:
            raise TemporalError("CHAPTER_NOT_FOUND", "Chapter does not belong to the target book")
        row = db.execute("SELECT * FROM chapter_temporal_contexts WHERE chapter_id=?", (chapter_id,)).fetchone()
        if not row:
            timeline_id = _ensure_book_and_timeline(db, book_id)
            db.commit()
            return {
                "chapter_id": chapter_id,
                "book_id": book_id,
                "timeline_id": timeline_id,
                "branch_id": None,
                "anchor_id": None,
                "phase_id": None,
                "viewpoint_entity_id": None,
                "include_future_knowledge": False,
                "inferred_from_chapter_order": True,
            }
        result = dict(row)
        result["include_future_knowledge"] = bool(result["include_future_knowledge"])
        result["inferred_from_chapter_order"] = result["anchor_id"] is None
        return result
    finally:
        db.close()


def _order_graph(db, timeline_id: str, branch_id: str | None):
    graph: dict[str, set[str]] = {}
    rows = db.execute(
        "SELECT source_anchor_id,relation_type,target_anchor_id FROM temporal_relations "
        "WHERE timeline_id=? AND ((branch_id IS NULL AND ? IS NULL) OR branch_id=?) "
        "AND review_status='accepted' AND confidence!='conflicting'",
        (timeline_id, branch_id, branch_id),
    ).fetchall()
    for row in rows:
        edge = _edge(row["relation_type"], row["source_anchor_id"], row["target_anchor_id"])
        if edge:
            graph.setdefault(edge[0], set()).add(edge[1])
        elif row["relation_type"] == "simultaneous":
            graph.setdefault(row["source_anchor_id"], set()).add(row["target_anchor_id"])
            graph.setdefault(row["target_anchor_id"], set()).add(row["source_anchor_id"])
    return graph


def _reachable(graph: dict[str, set[str]], source: str | None, target: str | None) -> bool:
    if not source or not target:
        return False
    if source == target:
        return True
    stack = [source]
    seen = set()
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current not in seen:
            seen.add(current)
            stack.extend(graph.get(current, ()))
    return False


def anchor_visibility(db, timeline_id: str, branch_id: str | None, candidate_anchor_id: str, target_anchor_id: str):
    """Return True for past/present, False for future, and None when unordered."""
    graph = _order_graph(db, timeline_id, branch_id)
    if _reachable(graph, candidate_anchor_id, target_anchor_id):
        return True
    if _reachable(graph, target_anchor_id, candidate_anchor_id):
        return False
    return None


def create_state_segment(payload: dict) -> dict:
    db = get_db(payload["database_id"])
    try:
        timeline_id = _ensure_book_and_timeline(db, payload["book_id"], payload.get("timeline_id"))
        if not db.execute(
            "SELECT 1 FROM entities WHERE entity_id=? AND book_id=? AND is_active=1",
            (payload["entity_id"], payload["book_id"]),
        ).fetchone():
            raise TemporalError("ENTITY_NOT_FOUND", "Entity does not belong to the target book")
        start = payload.get("valid_from_anchor_id")
        end = payload.get("valid_to_anchor_id")
        if start:
            _scope_anchor(db, start, payload["book_id"], timeline_id, payload.get("branch_id"))
        if end:
            _scope_anchor(db, end, payload["book_id"], timeline_id, payload.get("branch_id"))
        if start and end:
            graph = _order_graph(db, timeline_id, payload.get("branch_id"))
            if _reachable(graph, end, start):
                raise TemporalError("INVALID_STATE_INTERVAL", "State interval ends before it starts")
            if not _reachable(graph, start, end):
                payload["confidence"] = "uncertain"
        if payload.get("source_chapter_id") and not db.execute(
            "SELECT 1 FROM chapters WHERE chapter_id=? AND book_id=? AND is_active=1",
            (payload["source_chapter_id"], payload["book_id"]),
        ).fetchone():
            raise TemporalError("CHAPTER_NOT_FOUND", "Source chapter does not belong to the target book")
        supersedes = payload.get("supersedes_segment_id")
        if supersedes:
            old = db.execute(
                "SELECT * FROM entity_state_segments WHERE id=? AND entity_id=? AND timeline_id=?",
                (supersedes, payload["entity_id"], timeline_id),
            ).fetchone()
            if not old or old["branch_id"] != payload.get("branch_id"):
                raise TemporalError("SEGMENT_NOT_FOUND", "Superseded state segment does not match this entity context")
            if old["superseded_by"]:
                raise TemporalError("SEGMENT_ALREADY_SUPERSEDED", "State segment was already superseded")
        segment_id = f"ES_{uuid.uuid4().hex[:24].upper()}"
        db.execute(
            "INSERT INTO entity_state_segments("
            "id,book_id,entity_id,timeline_id,branch_id,valid_from_anchor_id,valid_to_anchor_id,"
            "state_type,state_payload_json,source_chapter_id,source_event_id,confidence) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                segment_id,
                payload["book_id"],
                payload["entity_id"],
                timeline_id,
                payload.get("branch_id"),
                start,
                end,
                payload["state_type"],
                json.dumps(payload["state_payload"], ensure_ascii=False),
                payload.get("source_chapter_id"),
                payload.get("source_event_id"),
                payload.get("confidence", "confirmed"),
            ),
        )
        if supersedes:
            db.execute("UPDATE entity_state_segments SET superseded_by=? WHERE id=?", (segment_id, supersedes))
        db.commit()
        row = db.execute("SELECT * FROM entity_state_segments WHERE id=?", (segment_id,)).fetchone()
        result = dict(row)
        result["state_payload"] = json.loads(result.pop("state_payload_json"))
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def state_history(database_id: str, book_id: str, entity_id: str, timeline_id: str | None = None, branch_id: str | None = None):
    db = get_db(database_id)
    try:
        timeline_id = _ensure_book_and_timeline(db, book_id, timeline_id)
        db.commit()
        rows = db.execute(
            "SELECT * FROM entity_state_segments WHERE book_id=? AND entity_id=? AND timeline_id=? "
            "AND ((branch_id IS NULL AND ? IS NULL) OR branch_id=?) ORDER BY created_at,id",
            (book_id, entity_id, timeline_id, branch_id, branch_id),
        ).fetchall()
        segments = []
        for row in rows:
            item = dict(row)
            item["state_payload"] = json.loads(item.pop("state_payload_json"))
            segments.append(item)
        return {"entity_id": entity_id, "timeline_id": timeline_id, "branch_id": branch_id, "segments": segments}
    finally:
        db.close()


def resolve_entity_state(
    database_id: str,
    book_id: str,
    entity_id: str,
    timeline_id: str | None = None,
    branch_id: str | None = None,
    anchor_id: str | None = None,
    chapter_id: str | None = None,
    db=None,
):
    owns_connection = db is None
    db = db or get_db(database_id)
    try:
        timeline_id = _ensure_book_and_timeline(db, book_id, timeline_id)
        if chapter_id:
            context = db.execute(
                "SELECT * FROM chapter_temporal_contexts WHERE chapter_id=? AND book_id=?",
                (chapter_id, book_id),
            ).fetchone()
            if context:
                if context["timeline_id"] != timeline_id or context["branch_id"] != branch_id:
                    raise TemporalError("TEMPORAL_SCOPE_MISMATCH", "Chapter temporal context does not match the requested scope")
                anchor_id = anchor_id or context["anchor_id"]
        if anchor_id:
            _scope_anchor(db, anchor_id, book_id, timeline_id, branch_id)
        rows = db.execute(
            "SELECT * FROM entity_state_segments WHERE book_id=? AND entity_id=? AND timeline_id=? "
            "AND ((branch_id IS NULL AND ? IS NULL) OR branch_id=?) AND superseded_by IS NULL",
            (book_id, entity_id, timeline_id, branch_id, branch_id),
        ).fetchall()
        graph = _order_graph(db, timeline_id, branch_id)
        candidates: dict[str, list[tuple[dict, bool]]] = {}
        for raw in rows:
            row = dict(raw)
            uncertain = False
            if anchor_id:
                start, end = row["valid_from_anchor_id"], row["valid_to_anchor_id"]
                if start and _reachable(graph, anchor_id, start) and anchor_id != start:
                    continue
                if start and not _reachable(graph, start, anchor_id):
                    uncertain = True
                if end and (anchor_id == end or _reachable(graph, end, anchor_id)):
                    continue
                if end and not _reachable(graph, anchor_id, end):
                    uncertain = True
            elif row["valid_to_anchor_id"]:
                continue
            row["state_payload"] = json.loads(row.pop("state_payload_json"))
            candidates.setdefault(row["state_type"], []).append((row, uncertain))

        fields = {}
        warnings = []
        for state_type, values in candidates.items():
            definite = [row for row, uncertain in values if not uncertain]
            selected = definite or [row for row, _uncertain in values]
            if len(selected) == 1 and (definite or len(values) == 1):
                row = selected[0]
                confidence = row["confidence"] if definite else "uncertain"
                fields[state_type] = {
                    "value": row["state_payload"],
                    "confidence": confidence,
                    "source_segment_ids": [row["id"]],
                }
                if confidence == "uncertain":
                    warnings.append(f"{state_type} is not fully ordered at the requested context")
            else:
                fields[state_type] = {
                    "value": [row["state_payload"] for row in selected],
                    "confidence": "conflicting" if definite else "uncertain",
                    "source_segment_ids": [row["id"] for row in selected],
                }
                warnings.append(f"{state_type} has multiple possible states")
        return {
            "entity_id": entity_id,
            "context": {
                "timeline_id": timeline_id,
                "branch_id": branch_id,
                "chapter_id": chapter_id,
                "anchor_id": anchor_id,
            },
            "fields": fields,
            "warnings": warnings,
        }
    finally:
        if owns_connection:
            db.close()


def find_state_conflict_candidates(db, book_id: str | None = None, entity_id: str | None = None):
    sql = (
        "SELECT * FROM entity_state_segments WHERE superseded_by IS NULL "
        "AND confidence!='conflicting'"
    )
    params = []
    if book_id:
        sql += " AND book_id=?"
        params.append(book_id)
    if entity_id:
        sql += " AND entity_id=?"
        params.append(entity_id)
    rows = [dict(row) for row in db.execute(sql, params).fetchall()]
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (row["entity_id"], row["timeline_id"], row["branch_id"], row["state_type"])
        groups.setdefault(key, []).append(row)
    strict_types = {"physical", "realm", "location", "identity", "faction", "ownership", "relationship", "goal", "life_status"}
    conflicts = []
    for key, segments in groups.items():
        graph = _order_graph(db, key[1], key[2])
        for index, left in enumerate(segments):
            left_payload = json.loads(left["state_payload_json"])
            for right in segments[index + 1:]:
                right_payload = json.loads(right["state_payload_json"])
                exclusive = left_payload != right_payload and key[3] in strict_types
                if key[3] == "psychological":
                    exclusive = (
                        left_payload.get("dominant_state") is not None
                        and right_payload.get("dominant_state") is not None
                        and left_payload.get("dominant_state") != right_payload.get("dominant_state")
                    )
                if not exclusive:
                    continue
                separated = (
                    left["valid_to_anchor_id"]
                    and right["valid_from_anchor_id"]
                    and _reachable(graph, left["valid_to_anchor_id"], right["valid_from_anchor_id"])
                ) or (
                    right["valid_to_anchor_id"]
                    and left["valid_from_anchor_id"]
                    and _reachable(graph, right["valid_to_anchor_id"], left["valid_from_anchor_id"])
                )
                if not separated:
                    conflicts.append(
                        {
                            "entity_id": key[0],
                            "timeline_id": key[1],
                            "branch_id": key[2],
                            "state_type": key[3],
                            "segment_ids": [left["id"], right["id"]],
                        }
                    )
    return conflicts
