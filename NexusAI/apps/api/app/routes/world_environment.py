from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.repository import WorldRepository
from app.schemas import WorldBlueprintRequest
from app.services.blueprint_service import BlueprintService
from nexus.world.render_spec import EnvironmentRenderSpec, build_render_spec

router = APIRouter(prefix="/worlds", tags=["world-environment"])

@router.post("/{world_id}/render-spec", response_model=EnvironmentRenderSpec)
async def generate_environment_render_spec(
    world_id: UUID,
    payload: WorldBlueprintRequest,
    db: Session = Depends(get_db),
):
    if WorldRepository(db).get(world_id) is None:
        raise HTTPException(status_code=404, detail="World not found")

    blueprint = BlueprintService().generate(payload.text)
    return build_render_spec(blueprint)
