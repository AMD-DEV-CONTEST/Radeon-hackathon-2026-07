from __future__ import annotations

import base64
from pathlib import Path
import json
from typing import Any

from langchain_core.messages import HumanMessage

from agent_factory.artifact_system import ArtifactStore
from agent_factory.models.image_generation import ImageGenerationRequest, ImageInput
from agent_factory.models.image_generation.service import image_input_from_path
from agent_factory.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime_tool = resources.get("model_tool")
    if not isinstance(runtime_tool, dict):
        raise ValueError("model_tool runtime resource is missing")
    capability = str(runtime_tool.get("capability") or "")
    if capability in {"image_output", "image_edit"}:
        return _run_image_generation_tool(
            arguments,
            runtime_tool,
            capability=capability,
            workspace_root=resources.get("workspace_root"),
        )
    if capability not in {"image_input", "audio_input", "audio_output"}:
        raise ValueError(f"unsupported local model tool capability: {capability}")
    model = runtime_tool.get("model")
    if model is None or not hasattr(model, "invoke"):
        raise ValueError("model_tool runtime resource has no runnable model")
    message = HumanMessage(content=_message_content(capability=capability, arguments=arguments, runtime_tool=runtime_tool))
    response = model.invoke([message])
    content, artifacts, raw_content = _project_response_content(getattr(response, "content", response))
    profile_id = str(runtime_tool.get("profile_id") or "")
    output = {
        "capability": capability,
        "profile_id": profile_id,
        "content": content,
        "artifacts": artifacts,
        "raw_content": raw_content,
        "metadata": {
            "tool_id": str(runtime_tool.get("tool_id") or ""),
            "model": str(runtime_tool.get("model_name") or ""),
            "provider": str(runtime_tool.get("provider") or ""),
            "model_source": str(runtime_tool.get("model_source") or ""),
        },
    }
    summary = content[:240] if content else f"{capability} model tool completed."
    return tool_envelope(
        output,
        evidence={"model_tool": {"tool_id": output["metadata"]["tool_id"], "profile_id": profile_id, "capability": capability}},
        summary=summary,
    )


def _run_image_generation_tool(
    arguments: dict[str, Any],
    runtime_tool: dict[str, Any],
    *,
    capability: str,
    workspace_root: Any,
) -> dict[str, Any]:
    service = runtime_tool.get("image_generation_service")
    if service is None or not hasattr(service, "generate"):
        raise ValueError("model_tool runtime resource has no image generation service")
    operation = "text_to_image" if capability == "image_output" else "edit"
    input_images = tuple(_image_inputs_from_arguments(arguments, runtime_tool))
    if capability == "image_edit" and not input_images:
        raise ValueError("image_edit requires at least one input image")
    request = ImageGenerationRequest(
        operation=operation,
        prompt=str(arguments.get("prompt") or ""),
        input_images=input_images,
        size=_optional_text(arguments.get("size")),
        aspect_ratio=_optional_text(arguments.get("aspect_ratio")),
        count=_bounded_count(arguments.get("count")),
        seed=_optional_int(arguments.get("seed")),
        negative_prompt=_optional_text(arguments.get("negative_prompt")),
        provider_options=dict(arguments.get("provider_options") or {}),
    )
    root = str(workspace_root or "").strip()
    if not root:
        raise ValueError("model_tool image generation requires the current session workspace_root")
    assets = service.generate(
        request,
        artifact_store=ArtifactStore(root=root, allowed_kinds=("artifact",)),
    )
    output = {
        "capability": capability,
        "profile_id": str(runtime_tool.get("profile_id") or ""),
        "assets": [asset.model_payload() for asset in assets],
        "metadata": {
            "tool_id": str(runtime_tool.get("tool_id") or ""),
            "model": str(runtime_tool.get("model_name") or ""),
            "provider": str(runtime_tool.get("provider") or ""),
            "model_source": str(runtime_tool.get("model_source") or ""),
        },
    }
    summary = f"Generated {len(assets)} image asset{'s' if len(assets) != 1 else ''}."
    return tool_envelope(
        output,
        evidence={"model_tool": {"tool_id": output["metadata"]["tool_id"], "profile_id": output["profile_id"], "capability": capability}},
        summary=summary,
    )


def _message_content(*, capability: str, arguments: dict[str, Any], runtime_tool: dict[str, Any]) -> Any:
    if capability == "image_input":
        return _image_input_content(arguments, runtime_tool)
    if capability == "audio_input":
        return _audio_input_content(arguments)
    if capability == "image_output":
        prompt = str(arguments.get("prompt") or "")
        details = _compact_json({key: arguments.get(key) for key in ("size", "style", "count") if arguments.get(key)})
        return prompt if not details else f"{prompt}\n\nGeneration constraints: {details}"
    if capability == "audio_output":
        text = str(arguments.get("text") or "")
        details = _compact_json({key: arguments.get(key) for key in ("voice", "format") if arguments.get(key)})
        return text if not details else f"{text}\n\nAudio constraints: {details}"
    return json.dumps(arguments, ensure_ascii=False)


def _image_input_content(arguments: dict[str, Any], runtime_tool: dict[str, Any]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": str(arguments.get("prompt") or "")}]
    for image in _image_inputs_from_arguments(arguments, runtime_tool):
        if image.data is None:
            continue
        content.append(_image_input_part(mime_type=image.mime_type, data=image.data))
    image_url = str(arguments.get("image_url") or "").strip()
    image_base64 = str(arguments.get("image_base64") or "").strip()
    mime_type = str(arguments.get("mime_type") or "image/png").strip() or "image/png"
    if image_url:
        content.append({"type": "image_url", "image_url": {"url": image_url}})
    elif image_base64:
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}})
    if len(content) == 1:
        raise ValueError("image_input requires input_attachment_ids, input_paths, image_url, or image_base64")
    return content


def _image_input_part(*, mime_type: str, data: bytes) -> dict[str, Any]:
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"},
    }


def _image_inputs_from_arguments(arguments: dict[str, Any], runtime_tool: dict[str, Any]) -> list[ImageInput]:
    inputs: list[ImageInput] = []
    for path in _input_paths(arguments, runtime_tool):
        inputs.append(image_input_from_path(path))
    image_url = _optional_text(arguments.get("image_url"))
    if image_url:
        inputs.append(ImageInput(source=image_url, mime_type="image/png", url=image_url, filename="remote-image.png"))
    return inputs


def _input_paths(arguments: dict[str, Any], runtime_tool: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for value in _string_list(arguments.get("input_paths")):
        paths.append(_resolve_runtime_path(value, runtime_tool))
    attachment_ids = set(_string_list(arguments.get("input_attachment_ids")))
    if attachment_ids:
        for candidate in _discover_runtime_attachment_paths(runtime_tool):
            if candidate.stem in attachment_ids or any(part in attachment_ids for part in candidate.parts):
                paths.append(candidate)
    return _dedupe_paths(paths)


def _discover_runtime_attachment_paths(runtime_tool: dict[str, Any]) -> list[Path]:
    roots = [
        Path(str(runtime_tool.get("runtime_root") or "")) / "input_files",
        Path(str(runtime_tool.get("package_root") or "")) / ".agent_runtime" / "input_files",
    ]
    paths: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                paths.append(path)
    return paths


def _resolve_runtime_path(value: str, runtime_tool: dict[str, Any]) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    package_root = Path(str(runtime_tool.get("package_root") or ".")).resolve()
    runtime_root = Path(str(runtime_tool.get("runtime_root") or package_root / ".agent_runtime")).resolve()
    for base in (runtime_root, package_root):
        candidate = (base / raw).resolve()
        if candidate.exists():
            return candidate
    return (runtime_root / raw).resolve()


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _bounded_count(value: Any) -> int:
    if isinstance(value, int):
        return min(max(value, 1), 4)
    return 1


def _audio_input_content(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    prompt = str(arguments.get("prompt") or "")
    language = str(arguments.get("language") or "").strip()
    if language:
        prompt = f"{prompt}\n\nLanguage hint: {language}"
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    audio_url = str(arguments.get("audio_url") or "").strip()
    audio_base64 = str(arguments.get("audio_base64") or "").strip()
    mime_type = str(arguments.get("mime_type") or "audio/mpeg").strip() or "audio/mpeg"
    if audio_url:
        content.append({"type": "input_audio", "input_audio": {"url": audio_url}})
    elif audio_base64:
        audio_format = mime_type.rsplit("/", 1)[-1] if "/" in mime_type else mime_type
        content.append({"type": "input_audio", "input_audio": {"data": audio_base64, "format": audio_format}})
    return content


def _project_response_content(value: Any) -> tuple[str, list[dict[str, Any]], Any]:
    if isinstance(value, str):
        return value, [], value
    if isinstance(value, list):
        text_parts: list[str] = []
        artifacts: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, str):
                text_parts.append(item)
                continue
            if not isinstance(item, dict):
                artifacts.append({"type": "unknown", "value": item})
                continue
            item_type = str(item.get("type") or "")
            text = item.get("text")
            if item_type in {"text", "output_text"} and isinstance(text, str):
                text_parts.append(text)
            else:
                artifacts.append(dict(item))
        return "\n".join(part for part in text_parts if part), artifacts, value
    if isinstance(value, dict):
        text = value.get("text") or value.get("content") or value.get("output_text")
        artifacts = value.get("artifacts") if isinstance(value.get("artifacts"), list) else []
        return str(text or ""), [dict(item) for item in artifacts if isinstance(item, dict)], value
    return str(value or ""), [], value


def _compact_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value else ""
