from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.local_inference.implementation import LlamaImplementationId


KernelSymbolTarget = Literal["raw_symbol", "base_symbol"]
KernelSymbolMatchKind = Literal["exact", "prefix", "contains"]
_KERNEL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")


class KernelSymbolMatcher(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: KernelSymbolTarget
    kind: KernelSymbolMatchKind
    value: str

    @field_validator("value")
    @classmethod
    def _required_value(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("kernel symbol matcher value must not be empty")
        return text


class KernelDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kernel_id: str
    display_name: str
    family: str
    descriptions: dict[str, str]
    symbol_matchers: list[KernelSymbolMatcher] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

    @field_validator("kernel_id", "family")
    @classmethod
    def _identifier(cls, value: str) -> str:
        text = str(value or "").strip().lower()
        if not _KERNEL_ID_PATTERN.fullmatch(text):
            raise ValueError("kernel identifiers must use lowercase letters, numbers, dots, underscores, or hyphens")
        return text

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("kernel display_name must not be empty")
        return text

    @field_validator("descriptions")
    @classmethod
    def _descriptions(cls, value: dict[str, str]) -> dict[str, str]:
        normalized = {
            str(locale or "").strip(): str(description or "").strip()
            for locale, description in value.items()
            if str(locale or "").strip() and str(description or "").strip()
        }
        if "en-US" not in normalized:
            raise ValueError("kernel descriptions must include en-US")
        return normalized


class KernelCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    implementation: LlamaImplementationId
    kernels: list[KernelDescriptor] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_entries(self) -> "KernelCatalog":
        kernel_ids = [descriptor.kernel_id for descriptor in self.kernels]
        if len(kernel_ids) != len(set(kernel_ids)):
            raise ValueError("kernel catalog contains duplicate kernel_id values")
        matchers = [
            (matcher.target, matcher.kind, matcher.value)
            for descriptor in self.kernels
            for matcher in descriptor.symbol_matchers
        ]
        if len(matchers) != len(set(matchers)):
            raise ValueError("kernel catalog contains duplicate symbol matchers")
        return self

    def resolve(self, *, raw_symbol: str, base_symbol: str) -> KernelDescriptor | None:
        candidates: list[tuple[int, int, KernelDescriptor]] = []
        values = {"raw_symbol": raw_symbol, "base_symbol": base_symbol}
        match_rank: dict[KernelSymbolMatchKind, int] = {
            "exact": 2,
            "prefix": 1,
            "contains": 0,
        }
        for descriptor in self.kernels:
            for matcher in descriptor.symbol_matchers:
                target = values[matcher.target]
                matchers = {
                    "exact": target == matcher.value,
                    "prefix": target.startswith(matcher.value),
                    "contains": matcher.value in target,
                }
                matched = matchers[matcher.kind]
                if matched:
                    candidates.append(
                        (
                            match_rank[matcher.kind],
                            len(matcher.value),
                            descriptor,
                        )
                    )
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], item[1]))[2]

    def get(self, kernel_id: str) -> KernelDescriptor | None:
        normalized = str(kernel_id or "").strip().lower()
        return next(
            (descriptor for descriptor in self.kernels if descriptor.kernel_id == normalized),
            None,
        )


def load_kernel_catalog(
    *,
    path: str,
    expected_sha256: str,
    implementation: LlamaImplementationId,
) -> KernelCatalog:
    catalog_path = Path(path).expanduser().resolve()
    if not catalog_path.is_file():
        raise ValueError(f"kernel catalog is unavailable: {catalog_path}")
    content = catalog_path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if expected_sha256 and actual_sha256.lower() != expected_sha256.strip().lower():
        raise ValueError("kernel catalog checksum does not match the active build manifest")
    catalog = KernelCatalog.model_validate(json.loads(content))
    if catalog.implementation != implementation:
        raise ValueError("kernel catalog implementation does not match the active build")
    return catalog
