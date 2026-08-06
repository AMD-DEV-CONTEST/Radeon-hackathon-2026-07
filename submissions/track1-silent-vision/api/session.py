from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/api/sessions")
async def create_session(request: Request) -> dict[str, object]:
    created = request.app.state.session_manager.create_pending_session()
    return {"sessionId": created.session_id, "expiresInSeconds": created.expires_in_seconds}
