"""Shared API request/response schemas."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

T = TypeVar("T")


class MessageResponse(BaseModel):
    message: str


class PaginationParams(BaseModel):
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    skip: int
    limit: int
