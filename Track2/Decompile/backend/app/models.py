from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl

StageState = Literal["queued", "running", "complete", "failed"]

class ProjectCreate(BaseModel):
    url: str = Field(min_length=10, max_length=2048)

class LogLine(BaseModel):
    timestamp: datetime
    message: str

class Stage(BaseModel):
    id: str
    label: str
    state: StageState = "queued"
    duration_seconds: int | None = None

class Agent(BaseModel):
    id: str
    name: str
    role: str
    state: StageState = "queued"
    output: str | None = None

class Artifact(BaseModel):
    path: str
    label: str
    ready: bool = False

class Project(BaseModel):
    id: str
    source_url: str
    title: str = "Untitled source"
    status: StageState = "queued"
    created_at: datetime
    updated_at: datetime
    stages: list[Stage]
    agents: list[Agent]
    artifacts: list[Artifact]
    logs: list[LogLine] = []

class SearchResult(BaseModel):
    project_id: str
    title: str
    score: float
    excerpt: str
