from fastapi import APIRouter
from app.models import HealthResponse

router = APIRouter(tags=["system"])

@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="healthy", service="nexus-api", version="0.8.0")
