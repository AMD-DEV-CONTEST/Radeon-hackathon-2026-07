from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agent_factory.tooling.extension_registry import set_agent_extension_binding


class CreateAgentSkillHubRuntime:
    def __init__(
        self,
        *,
        runtime: Any,
        package_root: str | Path,
        on_skill_config_changed: Callable[[], None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._package_root = Path(package_root).expanduser().resolve()
        self._on_skill_config_changed = on_skill_config_changed

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip().lower()
        if action == "remove":
            skill_id = str(payload.get("skill") or payload.get("query") or "").strip()
            bindings = set_agent_extension_binding(
                self._package_root / "extensions",
                kind="skill",
                identifier=skill_id,
                enabled=False,
            )
            self._refresh_skill_config()
            return {
                "action": "remove",
                "status": "ok",
                "message": f"Skill unbound from package: {skill_id}",
                "removed_skill": {"skill_id": skill_id},
                "bindings": bindings.model_dump(mode="json"),
                "restart_required": True,
            }
        result = self._runtime.run(payload)
        if action == "install" and _skill_config_changed(result):
            installed = result.get("installed_skill") if isinstance(result, dict) else None
            skill_id = str(installed.get("skill_id") if isinstance(installed, dict) else "").strip()
            if skill_id:
                set_agent_extension_binding(
                    self._package_root / "extensions",
                    kind="skill",
                    identifier=skill_id,
                    enabled=True,
                )
            self._refresh_skill_config()
        return result

    def tool_resource_summary(self) -> dict[str, Any]:
        summary = (
            self._runtime.tool_resource_summary()
            if hasattr(self._runtime, "tool_resource_summary")
            else {}
        )
        return {
            **(summary if isinstance(summary, dict) else {}),
            "mode": "create_agent_managed",
            "package_root": str(self._package_root),
        }

    def _refresh_skill_config(self) -> None:
        if self._on_skill_config_changed is None:
            return
        self._on_skill_config_changed()


def wrap_create_agent_skillhub_runtime(
    runtime: Any,
    *,
    package_root: str | Path,
    on_skill_config_changed: Callable[[], None] | None = None,
) -> Any:
    if runtime is None:
        return None
    return CreateAgentSkillHubRuntime(
        runtime=runtime,
        package_root=package_root,
        on_skill_config_changed=on_skill_config_changed,
    )


def _skill_config_changed(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") != "ok":
        return False
    return bool(result.get("restart_required") or result.get("installed_skill") or result.get("removed_skill"))
