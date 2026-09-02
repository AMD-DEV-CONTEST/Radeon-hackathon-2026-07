from fastapi import APIRouter, Request, Depends
from typing import List, Optional
from pydantic import BaseModel
from services.consistency import run_check
from app.dependencies.auth import require_admin

router = APIRouter(tags=["consistency"])


class ConsistencyCheckRequest(BaseModel):
    scope: str = "full"  # "full" or "entity:CHR_0001"
    check_types: List[str] = ["timeline", "character", "rule", "faction"]
    book_id: Optional[str] = None


@router.post("/api/consistency/check")
async def consistency_check(req: ConsistencyCheckRequest, request: Request, _: None = Depends(require_admin)):
    entity_id = None
    scope = req.scope
    if scope.startswith("entity:"):
        entity_id = scope.split(":", 1)[1]
        scope = "entity"

    # Use the database path from the vector store or default
    db_path = getattr(request.app.state, "db_path", "novel_world_zh.db")

    results, summary = run_check(
        db_path=db_path,
        scope=scope,
        check_types=req.check_types,
        entity_id=entity_id,
        book_id=req.book_id
    )

    return {
        "checks": [
            {
                "type": r.type,
                "status": r.status,
                "conflicts": [
                    {
                        "severity": c.severity,
                        "description": c.description,
                        "involved_entities": c.involved_entities,
                        "suggestion": c.suggestion,
                        "location": c.location
                    }
                    for c in r.conflicts
                ]
            }
            for r in results
        ],
        "summary": summary
    }
