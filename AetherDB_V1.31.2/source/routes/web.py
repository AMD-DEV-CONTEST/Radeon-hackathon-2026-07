from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from app.dependencies.auth import get_current_user_role, require_admin

router = APIRouter()

def _get_main():
    from main import templates
    from services.db import get_db
    from app.config import ENTITY_TYPES
    return templates, get_db, ENTITY_TYPES

@router.get("/add", response_class=HTMLResponse)
def add_entity_page(request: Request):
    templates, _, ENTITY_TYPES = _get_main()
    return templates.TemplateResponse(
        "add.html",
        {"request": request, "entity_types": ENTITY_TYPES},
    )

@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    templates, _, ENTITY_TYPES = _get_main()
    return templates.TemplateResponse(
        "search.html",
        {"request": request, "entity_types": ENTITY_TYPES},
    )

@router.get("/timeline", response_class=HTMLResponse)
def timeline_page(request: Request):
    templates, get_db, ENTITY_TYPES = _get_main()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT timeline_era FROM entities WHERE timeline_era IS NOT NULL")
    eras = [r["timeline_era"] for r in cursor.fetchall()]
    return templates.TemplateResponse(
        "timeline.html",
        {"request": request, "eras": eras},
    )

@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    templates, get_db, ENTITY_TYPES = _get_main()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entities WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 50")
    entities = cursor.fetchall()
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "entities": entities,
            "entity_types": ENTITY_TYPES,
        },
    )

# ── Admin proxy: Delete entity ──────────────────────────────────────────────
@router.post("/admin/entity/{entity_id}/delete")
def admin_delete_entity(entity_id: str, request: Request, _: None = Depends(require_admin)):
    _, get_db, _ = _get_main()
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE entities SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE entity_id = ?", (entity_id,))
        conn.commit()
        return JSONResponse({"status": "ok"})
    except Exception as e:
        raise HTTPException(status_code=500, detail="Delete failed")

# ── Admin proxy: Quick search ───────────────────────────────────────────────
@router.get("/admin/search/quick")
def admin_search_quick(q: str = "", limit: int = 5, role: str = Depends(get_current_user_role)):
    _, get_db, _ = _get_main()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT entity_id, title, entity_type FROM entities WHERE is_active = 1 AND title LIKE ? LIMIT ?",
        (f"%{q}%", limit)
    )
    return JSONResponse([dict(r) for r in cursor.fetchall()])

# ── Admin proxy: Import preview (uses server-side ADMIN_KEY) ────────────────
@router.post("/admin/import/preview")
async def admin_import_preview(request: Request, _: None = Depends(require_admin)):
    """Server-side proxy: calls LLM extractor using env ADMIN_KEY."""
    from extractors import get_extractor
    try:
        body = await request.json()
        text = body.get("text", "")
        config = body.get("extractor_config") or {}
        extractor = get_extractor(config)
        result = extractor.extract(text)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"entities": [], "relations": [], "error": "Import preview failed"})

# ── Admin proxy: Import confirm (uses server-side ADMIN_KEY) ────────────────
@router.post("/admin/import/confirm")
async def admin_import_confirm(request: Request, _: None = Depends(require_admin)):
    """Server-side proxy: imports entities using env ADMIN_KEY."""
    from services.db import generate_entity_id
    _, get_db, _ = _get_main()
    try:
        body = await request.json()
        entities = body.get("entities", [])
        relations = body.get("relations", [])
    except:
        return JSONResponse({"success": False, "error": "Invalid JSON"}, status_code=400)

    conn = get_db()
    try:
        cursor = conn.cursor()
        entity_id_map = {}
        created_count = 0
        relation_count = 0

        for ent in entities:
            etype = ent.get("type", "concept")
            entity_id = generate_entity_id(etype, cursor)
            title = ent.get("title", "")
            content = ent.get("content", "")
            tags = ent.get("tags", [])
            importance = ent.get("importance", 3)
            tags_json = __import__("json").dumps(tags, ensure_ascii=False)
            cursor.execute(
                "INSERT INTO entities (entity_id, entity_type, title, content, tags, importance, ai_summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entity_id, etype, title, content, tags_json, importance, content[:500]),
            )
            for tag in tags:
                cursor.execute("INSERT INTO tag_index (entity_id, tag) VALUES (?, ?)", (entity_id, tag.strip()))
            entity_id_map[title] = entity_id
            created_count += 1

        for rel in relations:
            source_id = entity_id_map.get(rel.get("source", ""))
            target_id = entity_id_map.get(rel.get("target", ""))
            if not source_id or not target_id:
                continue
            cursor.execute(
                "INSERT INTO relations (source_id, target_id, relation_type, description) VALUES (?, ?, ?, ?)",
                (source_id, target_id, rel.get("relation_type", "related_to"), rel.get("description", "")),
            )
            relation_count += 1

        conn.commit()
        return JSONResponse({"success": True, "created_entities": created_count, "created_relations": relation_count})
    except Exception as e:
        conn.rollback()
        return JSONResponse({"success": False, "error": "Import confirm failed"}, status_code=500)
    finally:
        conn.close()

@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    templates, _, _ = _get_main()
    return templates.TemplateResponse("import.html", {"request": request})

@router.get("/", response_class=HTMLResponse)
def get_home(request: Request):
    templates, get_db, ENTITY_TYPES = _get_main()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM entities WHERE is_active = 1")
    total_entities = cursor.fetchone()[0]
    cursor.execute("SELECT entity_type, COUNT(*) as count FROM entities WHERE is_active = 1 GROUP BY entity_type")
    type_dist = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) FROM relations")
    total_relations = cursor.fetchone()[0]
    cursor.execute("SELECT entity_id, title, entity_type, importance, created_at FROM entities WHERE is_active = 1 ORDER BY created_at DESC LIMIT 10")
    recent_entities = cursor.fetchall()
    stats = {"total_entities": total_entities, "type_distribution": {ENTITY_TYPES.get(r["entity_type"], r["entity_type"]): r["count"] for r in type_dist}, "total_relations": total_relations}
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "recent_entities": recent_entities,
            "entity_types": ENTITY_TYPES,
        },
    )
