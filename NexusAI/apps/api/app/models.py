from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class WorldResponse(BaseModel):
    id: str
    name: str
    description: str
    route: str
    status: str
