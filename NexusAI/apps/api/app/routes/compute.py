from fastapi import APIRouter
from nexus.embeddings import get_embedding_provider
from nexus.embeddings.device import detect_device
router=APIRouter(prefix="/compute",tags=["compute"])
@router.get("/health")
async def compute_health():
    d=detect_device();p=get_embedding_provider()
    return {"accelerator":{"available":d.accelerator_available,"backend":d.backend,"device_name":d.device_name,"torch_version":d.torch_version,"hip_version":d.hip_version},"embedding_provider":p.health()}
