from pydantic import BaseModel, Field


class StoryRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    pages: int = Field(default=5, ge=1, le=10)


class StoryResponse(BaseModel):
    status: str
    story: dict