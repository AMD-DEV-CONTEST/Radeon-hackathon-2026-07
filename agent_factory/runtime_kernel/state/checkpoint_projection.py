from __future__ import annotations

from typing import Any, Literal

from agent_factory.runtime_kernel.state.schema import RuntimeState


RuntimeCheckpointMode = Literal["json", "python"]

_CHECKPOINT_TOOL_OBSERVATION_KEYS = {
    "type",
    "status",
    "tool_id",
    "tool_call_id",
    "message",
    "retryable",
    "execution_status",
    "contract_status",
    "output_ref",
    "output_summary",
    "output_truncated",
    "user_instruction",
    "errors",
}


def runtime_checkpoint_payload(state: RuntimeState, *, mode: RuntimeCheckpointMode) -> dict[str, Any]:
    """Return the RuntimeState representation that is safe to persist in LangGraph checkpoints.

    Checkpoints are the recovery surface, not the event log or raw tool-output store.
    Trace events keep flowing through observability/trace recorders, while checkpoint
    state keeps only the resumable runtime fields and lightweight tool observation refs.
    """

    return runtime_checkpoint_state(state).model_dump(mode=mode)


def runtime_checkpoint_state(state: RuntimeState) -> RuntimeState:
    projected = state.model_copy(deep=True)
    projected.observability.events = []
    projected.tools.tool_results = [
        _checkpoint_tool_observation(item)
        for item in projected.tools.tool_results
        if isinstance(item, dict)
    ]
    projected.tools.tool_failures = [
        _checkpoint_tool_observation(item)
        for item in projected.tools.tool_failures
        if isinstance(item, dict)
    ]
    if isinstance(projected.tools.last_tool_result, dict):
        projected.tools.last_tool_result = _checkpoint_tool_observation(projected.tools.last_tool_result)
    return projected


def _checkpoint_tool_observation(observation: dict[str, Any]) -> dict[str, Any]:
    compacted = {
        key: value
        for key, value in observation.items()
        if key in _CHECKPOINT_TOOL_OBSERVATION_KEYS and value is not None
    }
    output_ref = _output_ref_from_observation(observation)
    if output_ref is not None:
        compacted["output_ref"] = output_ref
    compact_output = _checkpoint_tool_output(observation.get("output"), output_ref=output_ref)
    if compact_output:
        compacted["output"] = compact_output
    return compacted


def _output_ref_from_observation(observation: dict[str, Any]) -> dict[str, Any] | None:
    output_ref = observation.get("output_ref")
    if isinstance(output_ref, dict):
        return output_ref
    output = observation.get("output")
    if not isinstance(output, dict):
        return None
    compacted = output.get("_tool_output_compacted")
    if not isinstance(compacted, dict):
        return None
    nested_ref = compacted.get("output_ref")
    return nested_ref if isinstance(nested_ref, dict) else None


def _checkpoint_tool_output(output: Any, *, output_ref: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    compacted: dict[str, Any] = {}
    output_id = str(output.get("output_id") or "")
    if not output_id and isinstance(output_ref, dict):
        output_id = str(output_ref.get("id") or "")
    if output_id:
        compacted["output_id"] = output_id
    read_hint = str(output.get("raw_output_read_hint") or "")
    if read_hint:
        compacted["raw_output_read_hint"] = read_hint
    metadata = output.get("_tool_output_compacted")
    if isinstance(metadata, dict):
        compacted["_tool_output_compacted"] = {
            key: value
            for key, value in metadata.items()
            if key != "compressed_output" and value is not None
        }
    return compacted
