from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RuntimeKind = Literal["cuda", "rocm", "cpu"]


class DeviceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    runtime: RuntimeKind
    vendor: str
    name: str
    index: int | None = None
    total_memory_mb: int | None = Field(default=None, ge=0)
    allocated_memory_mb: int | None = Field(default=None, ge=0)
    reserved_memory_mb: int | None = Field(default=None, ge=0)
    torch_version: str
    runtime_version: str | None = None
    architecture: str | None = None
    compute_units: int | None = Field(default=None, ge=0)
    capability: str | None = None
    migration_compatible: bool = True


class ComputeBackend(ABC):
    @property
    @abstractmethod
    def info(self) -> DeviceInfo:
        raise NotImplementedError

    @property
    @abstractmethod
    def torch_device(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def inference_context(self, *, mixed_precision: bool = True) -> AbstractContextManager[Any]:
        raise NotImplementedError

    @abstractmethod
    def synchronize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def empty_cache(self) -> None:
        raise NotImplementedError
