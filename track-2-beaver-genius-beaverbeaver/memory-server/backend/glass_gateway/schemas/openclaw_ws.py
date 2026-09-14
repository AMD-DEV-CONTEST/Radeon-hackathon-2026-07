from typing import Any, Literal
from pydantic import BaseModel


class OpenClawHello(BaseModel):
    type: Literal["openclaw.hello"]
    client: str = "openclaw"
    protocol: int = 1


class OpenClawHelloOk(BaseModel):
    type: Literal["openclaw.hello.ok"] = "openclaw.hello.ok"
    gateway: str = "glass-gateway"
    protocol: int = 1
    status: str = "placeholder"
    caps: list[str] = [
        "device.list",
        "display.render.placeholder",
        "voice.ask.placeholder",
        "camera.snap.placeholder",
    ]


class OpenClawCommand(BaseModel):
    type: Literal["command"]
    command: str
    device_id: str | None = None
    payload: dict[str, Any] = {}


class OpenClawCommandResult(BaseModel):
    type: Literal["command.result"] = "command.result"
    command: str
    status: Literal["not_implemented"] = "not_implemented"
