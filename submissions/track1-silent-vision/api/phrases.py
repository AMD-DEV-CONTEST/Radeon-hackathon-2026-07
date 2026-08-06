from fastapi import APIRouter, Request

from command.catalog import catalog_records

router = APIRouter()


@router.get("/api/phrases")
async def get_phrases(request: Request) -> dict[str, list[dict[str, object]]]:
    return {"phrases": catalog_records(request.app.state.phrase_catalog)}
