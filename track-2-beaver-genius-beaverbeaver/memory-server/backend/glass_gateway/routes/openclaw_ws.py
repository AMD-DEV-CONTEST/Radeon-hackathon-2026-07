from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from glass_gateway.schemas.openclaw_ws import (
    OpenClawCommand,
    OpenClawCommandResult,
    OpenClawHelloOk,
)

router = APIRouter()


@router.websocket("/v1/openclaw/ws")
async def openclaw_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            if message_type == "openclaw.hello":
                await websocket.send_json(OpenClawHelloOk().model_dump(mode="json"))
            elif message_type == "ping":
                await websocket.send_json({"type": "pong", "seq": message.get("seq")})
            elif message_type == "command":
                command = OpenClawCommand.model_validate(message)
                result = OpenClawCommandResult(command=command.command)
                await websocket.send_json(result.model_dump(mode="json"))
            else:
                await websocket.send_json(
                    {"type": "error", "code": "unknown_message", "message": message_type}
                )
    except WebSocketDisconnect:
        return
