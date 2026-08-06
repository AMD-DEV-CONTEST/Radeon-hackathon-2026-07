from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.repository import WorldRepository
from app.schemas import WorldBlueprintRequest, WorldCreate
from app.services.blueprint_service import BlueprintService
from nexus.world import World, WorldBlueprint

router = APIRouter(prefix="/worlds", tags=["worlds"])

@router.get("", response_model=list[World])
async def list_worlds(db: Session = Depends(get_db)):
    return WorldRepository(db).list()

@router.post("", response_model=World, status_code=status.HTTP_201_CREATED)
async def create_world(payload: WorldCreate, db: Session = Depends(get_db)):
    world = World(**payload.model_dump())
    return WorldRepository(db).create(world)

@router.get("/{world_id}", response_model=World)
async def get_world(world_id: UUID, db: Session = Depends(get_db)):
    world = WorldRepository(db).get(world_id)
    if world is None:
        raise HTTPException(status_code=404, detail="World not found")
    return world

@router.post("/{world_id}/blueprint", response_model=WorldBlueprint)
async def generate_world_blueprint(
    world_id: UUID,
    payload: WorldBlueprintRequest,
    db: Session = Depends(get_db),
):
    world = WorldRepository(db).get(world_id)
    if world is None:
        raise HTTPException(status_code=404, detail="World not found")

    try:
        return BlueprintService().generate(payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
