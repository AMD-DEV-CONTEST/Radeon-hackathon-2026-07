from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent_factory.runtime_kernel.errors import RuntimeKernelError


TraceFailureDomain = Literal["agent_package", "runtime_kernel"]


@dataclass(frozen=True, slots=True)
class TraceFailureClassification:
    domain: TraceFailureDomain
    reason: str


class AgentPackageExecutionError(RuntimeKernelError):
    """Raised when package-owned code fails during RuntimeKernel execution."""


def classify_node_failure(*, node_impl: str, error: BaseException) -> TraceFailureClassification:
    if isinstance(error, AgentPackageExecutionError) or node_impl.startswith("package."):
        return TraceFailureClassification(domain="agent_package", reason="package_node_failure")
    if _looks_like_model_contract_error(error):
        return TraceFailureClassification(domain="runtime_kernel", reason="model_contract_failure")
    if _looks_like_runtime_infrastructure_error(error):
        return TraceFailureClassification(domain="runtime_kernel", reason="runtime_infrastructure_failure")
    if isinstance(error, RuntimeKernelError):
        return TraceFailureClassification(domain="agent_package", reason="package_runtime_contract_failure")
    return TraceFailureClassification(domain="runtime_kernel", reason="unclassified_runtime_failure")


def _looks_like_model_contract_error(error: BaseException) -> bool:
    text = _error_text(error)
    markers = (
        "structured model operation failed",
        "response_format",
        "structured_output",
        "with_structured_output",
        "model is not configured",
        "invalid_request_error",
    )
    return any(marker in text for marker in markers)


def _looks_like_runtime_infrastructure_error(error: BaseException) -> bool:
    text = _error_text(error)
    markers = (
        "checkpoint",
        "checkpointer",
        "runtime graph ended before a terminal node",
        "incomplete tool call history",
        "sandbox dependency initialization failed",
    )
    return any(marker in text for marker in markers)


def _error_text(error: BaseException) -> str:
    parts: list[str] = [type(error).__name__, str(error)]
    cause = getattr(error, "__cause__", None)
    context = getattr(error, "__context__", None)
    if cause is not None:
        parts.extend([type(cause).__name__, str(cause)])
    if context is not None and context is not cause:
        parts.extend([type(context).__name__, str(context)])
    return " ".join(parts).lower()
