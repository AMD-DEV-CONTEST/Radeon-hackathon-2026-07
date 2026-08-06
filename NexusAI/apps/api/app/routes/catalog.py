from fastapi import APIRouter
from app.models import WorldResponse
from app.world_registry import WORLDS
router=APIRouter(tags=["catalog"])
@router.get("/world-catalog",response_model=list[WorldResponse])
async def catalog(): return [WorldResponse(**w) for w in WORLDS]
