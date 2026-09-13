from pydantic import BaseModel


class RunbookIngestRequest(BaseModel):
    title: str
    content: str
    metadata: dict = {}


class RunbookIngestResponse(BaseModel):
    title: str
    chunks_ingested: int
