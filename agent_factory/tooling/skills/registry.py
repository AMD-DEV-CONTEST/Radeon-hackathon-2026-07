from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from agent_factory.tooling.skills.schema import SkillGatewayState, SkillLoadResult, SkillPackage


MAX_RESOURCE_READ_CHARS = 12000
MAX_INLINE_RESOURCE_CHARS = 6000
SKILL_REGISTRY_VERSION = "skill_registry.v1"


@dataclass(frozen=True, slots=True)
class _ReadableSkillSource:
    path: str
    kind: str
    purpose: str
    media_type: str
    size_bytes: int
    readable: bool
    target: Path
    content_ref: str


class SkillResourceFragmentNotFound(LookupError):
    def __init__(self, *, path: str, pointer: str, available_keys: list[str]) -> None:
        self.path = path
        self.pointer = pointer
        self.available_keys = available_keys
        key_text = ", ".join(available_keys[:20]) if available_keys else "none"
        super().__init__(
            f"skill resource fragment not found: path={path}; pointer={pointer}; available_top_level_keys={key_text}"
        )


class SkillRegistry:
    def __init__(self, skills: list[SkillPackage] | None = None, *, gateway_state: SkillGatewayState | None = None) -> None:
        self._skills: dict[str, SkillPackage] = {}
        self.gateway_state = gateway_state or SkillGatewayState()
        for skill in skills or []:
            self.register(skill)

    def register(self, skill: SkillPackage) -> None:
        if skill.name in self._skills:
            raise ValueError(f"duplicate skill name: {skill.name}")
        self._skills[skill.name] = skill

    def list_metadata(self) -> list[dict[str, Any]]:
        return [
            _candidate_view(skill)
            for skill in sorted(self._skills.values(), key=lambda item: item.name)
        ]

    def packages(self) -> list[SkillPackage]:
        return sorted(self._skills.values(), key=lambda item: item.name)

    def describe(self, name: str, *, current_system: str) -> dict[str, Any]:
        skill = self.get(name)
        system_state = self.gateway_state.system_state(_require_system(current_system))
        system_state.mark_described(name)
        return {
            "metadata": skill.metadata.model_dump(mode="json"),
            "resources": [item.model_dump(mode="json") for item in skill.resources],
            "scripts": [item.model_dump(mode="json") for item in skill.scripts],
            "loaded_content": False,
            "already_read_resources": [
                item.model_dump(mode="json")
                for item in system_state.read_resources
                if item.name == name
            ],
        }

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        terms = _query_terms(query)
        if not terms:
            return []
        matches: list[tuple[int, SkillPackage, list[str]]] = []
        for skill in self.packages():
            fields = _search_fields(skill)
            matched_fields = [
                label
                for label, value in fields
                if all(term in value.casefold() for term in terms)
            ]
            if not matched_fields:
                continue
            matches.append((len(matched_fields), skill, matched_fields))
        matches.sort(key=lambda item: (-item[0], item[1].name))
        return [
            {
                **_candidate_view(skill),
                "matched_fields": matched_fields,
            }
            for _score, skill, matched_fields in matches[: max(1, limit)]
        ]

    def get(self, name: str) -> SkillPackage:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(f"unknown skill: {name}") from exc

    def list_loaded(self, *, current_system: str) -> dict[str, Any]:
        state = self.gateway_state.system_state(_require_system(current_system))
        return state.model_dump(mode="json")

    def load(self, name: str, *, current_system: str, reason: str) -> SkillLoadResult:
        skill = self.get(name)
        system_state = self.gateway_state.system_state(_require_system(current_system))
        cleaned_reason = _require_reason(reason)
        if system_state.primary_skill and system_state.primary_skill != name and not system_state.has_seen(name):
            raise PermissionError(
                f"loading a second skill for system {current_system!r} requires describe(name={name!r}, current_system=...) first"
            )
        system_state.mark_loaded(name, reason=cleaned_reason)
        return SkillLoadResult(
            name=skill.name,
            metadata=skill.metadata,
            content=skill.body,
            resources=skill.resources,
            scripts=skill.scripts,
            resource_contents={},
        )

    def read_resource(
        self,
        name: str,
        path: str,
        *,
        current_system: str,
        mode: str = "outline",
        pointer: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        skill = self.get(name)
        system_state = self.gateway_state.system_state(_require_system(current_system))
        root = Path(skill.root).resolve()
        source = _readable_skill_source(skill, path, root=root)
        _assert_inside(root, source.target)
        if not source.target.is_file():
            raise FileNotFoundError(str(source.target))
        payload: dict[str, Any] = {
            "name": name,
            "path": source.path,
            "kind": source.kind,
            "purpose": source.purpose,
            "media_type": source.media_type,
            "size_bytes": source.size_bytes,
            "readable": source.readable,
            "truncated": False,
            "content": "",
            "mode": mode,
            "pointer": pointer,
            "content_ref": source.content_ref,
        }
        previous_read = system_state.resource_read_record(name, source.path, mode=mode, pointer=pointer)
        if not source.readable:
            payload["message"] = "Skill source is not text-readable; returning metadata only."
            payload["already_read"] = previous_read is not None
            payload["read_record"] = system_state.mark_resource_read(
                name,
                source.path,
                mode=mode,
                pointer=pointer,
                digest="",
            ).model_dump(mode="json")
            return payload
        content = source.target.read_text(encoding="utf-8")
        digest = sha256(content.encode("utf-8")).hexdigest()
        if mode == "outline":
            payload["outline"] = _resource_outline(source.path, content)
            payload["task_model_summary"] = _task_model_summary(source.path, content)
            return _with_read_record(
                payload,
                system_state=system_state,
                name=name,
                path=source.path,
                mode=mode,
                pointer=pointer,
                digest=digest,
                already_read=previous_read is not None,
            )
        if mode == "fragment":
            try:
                fragment = _json_pointer_fragment(content, pointer)
            except KeyError as exc:
                raise SkillResourceFragmentNotFound(
                    path=source.path,
                    pointer=pointer,
                    available_keys=_json_top_level_keys(content),
                ) from exc
            payload["fragment"] = fragment
            payload["task_model_summary"] = _fragment_summary(source.path, pointer, fragment)
            return _with_read_record(
                payload,
                system_state=system_state,
                name=name,
                path=source.path,
                mode=mode,
                pointer=pointer,
                digest=digest,
                already_read=previous_read is not None,
            )
        if mode != "content":
            raise ValueError("resource read mode must be one of: outline, fragment, content")
        is_schema = _is_schema_resource(source.path)
        if is_schema and not reason.strip():
            raise ValueError("full schema content requires reason; use mode=fragment for schema fields by default")
        payload["schema_read_level"] = "full" if is_schema else ""
        payload["read_reason"] = reason.strip()
        payload["task_model_summary"] = _task_model_summary(source.path, content)
        if is_schema or previous_read is not None or len(content) > MAX_INLINE_RESOURCE_CHARS:
            payload["content"] = ""
            payload["content_omitted"] = True
            payload["omission_reason"] = _content_omission_reason(
                is_schema=is_schema,
                already_read=previous_read is not None,
                chars=len(content),
            )
        elif len(content) > MAX_RESOURCE_READ_CHARS:
            payload["content"] = content[:MAX_RESOURCE_READ_CHARS]
            payload["truncated"] = True
            payload["content_omitted"] = False
        else:
            payload["content"] = content
            payload["content_omitted"] = False
        return _with_read_record(
            payload,
            system_state=system_state,
            name=name,
            path=source.path,
            mode=mode,
            pointer=pointer,
            digest=digest,
            already_read=previous_read is not None,
        )

    def to_resource_payload(self) -> dict[str, Any]:
        return {
            "version": SKILL_REGISTRY_VERSION,
            "skills": [
                skill.model_dump(mode="json")
                for skill in sorted(self._skills.values(), key=lambda item: item.name)
            ],
            "gateway_state": self.gateway_state.model_dump(mode="json"),
        }

    @classmethod
    def from_resource_payload(cls, payload: dict[str, Any]) -> "SkillRegistry":
        if payload.get("version") != SKILL_REGISTRY_VERSION:
            raise ValueError(f"unsupported skill registry payload version: {payload.get('version')!r}")
        skills = [
            SkillPackage.model_validate(item)
            for item in payload.get("skills", [])
            if isinstance(item, dict)
        ]
        gateway_state = SkillGatewayState.model_validate(payload.get("gateway_state") or {})
        return cls(skills, gateway_state=gateway_state)


def _assert_inside(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Skill resource path escapes skill root: {path}") from exc


def _readable_skill_source(skill: SkillPackage, path: str, *, root: Path) -> _ReadableSkillSource:
    resource = next((item for item in skill.resources if item.path == path), None)
    if resource is not None:
        return _ReadableSkillSource(
            path=resource.path,
            kind=resource.kind,
            purpose=_resource_purpose(resource.path),
            media_type=resource.media_type,
            size_bytes=resource.size_bytes,
            readable=resource.readable,
            target=(root / resource.path).resolve(),
            content_ref=f"skill://{skill.name}/{resource.path}",
        )
    script = next((item for item in skill.scripts if item.path == path), None)
    if script is not None:
        return _ReadableSkillSource(
            path=script.path,
            kind="script",
            purpose="script_source",
            media_type=_source_media_type(script.path),
            size_bytes=script.size_bytes,
            readable=_is_text_source_path(script.path),
            target=(root / script.path).resolve(),
            content_ref=script.script_ref,
        )
    raise KeyError(f"unknown skill resource or script: {skill.name}/{path}")


def _query_terms(query: str) -> list[str]:
    return [term.casefold() for term in query.strip().split() if term.strip()]


def _search_fields(skill: SkillPackage) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = [
        ("name", skill.name),
        ("description", skill.metadata.description),
    ]
    for key, value in skill.metadata.metadata.items():
        if isinstance(value, str):
            fields.append((f"metadata.{key}", value))
        elif isinstance(value, (int, float, bool)):
            fields.append((f"metadata.{key}", str(value)))
    fields.extend(("resource", item.path) for item in skill.resources)
    fields.extend(("script", item.path) for item in skill.scripts)
    return fields


def _candidate_view(skill: SkillPackage) -> dict[str, Any]:
    load_when = skill.metadata.metadata.get("load_when")
    return {
        "name": skill.name,
        "description": skill.metadata.description,
        "loaded_content": False,
        "applicable_systems": _applicable_systems(load_when),
        "loading_cost": {
            "skill_body_chars": len(skill.body),
            "resource_count": len(skill.resources),
            "script_count": len(skill.scripts),
        },
    }


def _applicable_systems(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _require_system(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError("current_system must be a non-empty string")
    return cleaned


def _require_reason(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError("reason must be a non-empty string")
    return cleaned


def _resource_outline(path: str, content: str) -> dict[str, Any]:
    if not path.endswith(".json"):
        return {
            "format": "text",
            "chars": len(content),
            "preview": content[:600],
            "purpose": _resource_purpose(path),
        }
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {
            "format": "json",
            "parseable": False,
            "chars": len(content),
            "preview": content[:600],
            "purpose": _resource_purpose(path),
        }
    if not isinstance(payload, dict):
        return {"format": "json", "json_type": type(payload).__name__, "chars": len(content)}
    properties = payload.get("properties")
    property_index = []
    if isinstance(properties, dict):
        for name, spec in sorted(properties.items()):
            if isinstance(spec, dict):
                property_index.append(
                    {
                        "name": name,
                        "type": spec.get("type"),
                        "ref": spec.get("$ref"),
                        "title": spec.get("title"),
                        "description": spec.get("description"),
                    }
                )
            else:
                property_index.append({"name": name, "type": type(spec).__name__})
    defs = payload.get("$defs")
    return {
        "format": "json_schema" if "$schema" in payload or "properties" in payload else "json",
        "purpose": _resource_purpose(path),
        "title": payload.get("title"),
        "type": payload.get("type"),
        "required": payload.get("required", []),
        "properties": property_index,
        "defs": sorted(defs) if isinstance(defs, dict) else [],
        "chars": len(content),
        "hint": "Use mode=fragment with a JSON pointer for a specific subtree, or mode=content only when raw content is necessary.",
    }


def _resource_purpose(path: str) -> str:
    if path.startswith("scripts/"):
        return "script_source"
    if path.startswith("examples/"):
        return "capability_example"
    if path.endswith(".repair_hints.md") or path.endswith(".common_errors.md") or path.endswith(".validator_scope.md"):
        return "repair_hint"
    if path.endswith(".schema.json"):
        return "schema_fragment"
    if path.startswith("guidance/") or path.endswith(".guidance.md"):
        return "guidance"
    return "reference"


def _source_media_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return "text/x-python"
    if suffix in {".sh", ".bash", ".zsh"}:
        return "text/x-shellscript"
    if suffix in {".md", ".txt"}:
        return "text/markdown" if suffix == ".md" else "text/plain"
    if suffix == ".json":
        return "application/json"
    if suffix in {".yaml", ".yml"}:
        return "application/yaml"
    if suffix == ".csv":
        return "text/csv"
    return "text/plain" if _is_text_source_path(path) else "application/octet-stream"


def _is_text_source_path(path: str) -> bool:
    return Path(path).suffix.lower() in {
        "",
        ".bash",
        ".cfg",
        ".conf",
        ".csv",
        ".ini",
        ".json",
        ".md",
        ".py",
        ".sh",
        ".sql",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
        ".zsh",
    }


def _is_schema_resource(path: str) -> bool:
    return path.endswith(".schema.json")


def _content_omission_reason(*, is_schema: bool, already_read: bool, chars: int) -> str:
    if is_schema:
        return "schema content is summarized; use mode=fragment with a JSON pointer for exact fields"
    if already_read:
        return "resource content was already read for this focus/mode/pointer"
    return f"resource is large ({chars} chars); summary returned instead"


def _task_model_summary(path: str, content: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "resource_path": path,
        "purpose": _resource_purpose(path),
        "chars": len(content),
        "digest": sha256(content.encode("utf-8")).hexdigest(),
        "writable_targets": _writable_targets_from_text(content),
        "required_fields": [],
        "object_shapes": [],
        "recommended_next_action": _recommended_next_action(path),
    }
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        summary["preview"] = " ".join(content.split())[:500]
        return summary
    summary["json_type"] = type(payload).__name__
    if isinstance(payload, dict):
        summary["top_level_keys"] = sorted(str(key) for key in payload.keys())[:40]
        required = payload.get("required")
        if isinstance(required, list):
            summary["required_fields"] = [str(item) for item in required[:40]]
        properties = payload.get("properties")
        if isinstance(properties, dict):
            summary["object_shapes"] = [
                {
                    "name": str(name),
                    "type": spec.get("type") if isinstance(spec, dict) else type(spec).__name__,
                    "ref": spec.get("$ref") if isinstance(spec, dict) else None,
                }
                for name, spec in list(sorted(properties.items()))[:40]
            ]
    return summary


def _fragment_summary(path: str, pointer: str, fragment: Any) -> dict[str, Any]:
    return {
        "resource_path": path,
        "purpose": "schema_fragment" if _is_schema_resource(path) else _resource_purpose(path),
        "pointer": pointer,
        "json_type": type(fragment).__name__,
        "required_fields": fragment.get("required", []) if isinstance(fragment, dict) else [],
        "top_level_keys": sorted(str(key) for key in fragment.keys())[:40] if isinstance(fragment, dict) else [],
        "recommended_next_action": "Use this fragment to fill or repair only the targeted object; do not audit scaffold files.",
    }


def _writable_targets_from_text(content: str) -> list[str]:
    targets: list[str] = []
    for token in (
        "agent_package.json",
        "assembly_spec.json",
        "resources.json",
        "contracts/",
        "tools/",
        "nodes/",
        "knowledge/",
        "prompts/",
    ):
        if token in content:
            targets.append(token)
    return targets


def _recommended_next_action(path: str) -> str:
    purpose = _resource_purpose(path)
    if purpose == "script_source":
        return "Inspect this source to understand the skill implementation; execution still requires a registered ToolSpec or dedicated allowed execution tool."
    if purpose == "capability_example":
        return "Adapt this capability example to the current empty package, then stop tool calls so validation can run."
    if purpose == "schema_fragment":
        return "Use mode=fragment for the exact schema path needed by validator evidence or missing example fields."
    if purpose == "repair_hint":
        return "Use only after validator evidence identifies the matching repair target."
    return "Use this guidance to decide whether the current capability should edit this surface."


def _json_pointer_fragment(content: str, pointer: str) -> Any:
    if not pointer:
        raise ValueError("pointer is required when mode=fragment")
    try:
        value: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("fragment mode requires a JSON resource") from exc
    if pointer == "/":
        return value
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with '/'")
    for raw_part in pointer.lstrip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[part]
        elif isinstance(value, list):
            value = value[int(part)]
        else:
            raise KeyError(f"cannot descend into {type(value).__name__} at {part!r}")
    return value


def _json_top_level_keys(content: str) -> list[str]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        return sorted(str(key) for key in payload.keys())
    if isinstance(payload, list):
        return [str(index) for index in range(min(len(payload), 20))]
    return []


def _with_read_record(
    payload: dict[str, Any],
    *,
    system_state: Any,
    name: str,
    path: str,
    mode: str,
    pointer: str,
    digest: str,
    already_read: bool,
) -> dict[str, Any]:
    payload["already_read"] = already_read
    payload["digest"] = digest
    payload["read_record"] = system_state.mark_resource_read(
        name,
        path,
        mode=mode,
        pointer=pointer,
        digest=digest,
    ).model_dump(mode="json")
    if already_read:
        payload["message"] = "This resource was already read for the same current_system, mode, and pointer."
    return payload
