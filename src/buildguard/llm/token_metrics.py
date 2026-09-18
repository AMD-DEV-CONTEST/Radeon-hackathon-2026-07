"""Inference timing records without hidden reasoning content."""

from pydantic import BaseModel, Field


class TokenMetrics(BaseModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    # A non-streaming response cannot expose an observed first-token timestamp.
    # Keep it null instead of mislabelling total request latency as TTFT.
    ttft_seconds: float | None = Field(default=None, ge=0)
    total_seconds: float = Field(ge=0)
    tokens_per_second: float = Field(ge=0)
    thinking_mode: bool


class ChatResponse(BaseModel):
    content: str
    metrics: TokenMetrics
