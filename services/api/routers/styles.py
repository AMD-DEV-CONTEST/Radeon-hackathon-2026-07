from fastapi import APIRouter

from agents.styles import list_styles
from shared.schemas.style import StyleTemplateResponse

router = APIRouter(prefix="/styles", tags=["styles"])


@router.get("", response_model=list[StyleTemplateResponse])
def list_available_styles():
    return [StyleTemplateResponse.model_validate(s) for s in list_styles()]
