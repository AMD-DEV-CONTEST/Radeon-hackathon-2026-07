from __future__ import annotations

import json

from agent_factory.tooling.providers.base import ToolProviderContext, ToolProviderResult, diagnostic
from agent_factory.tooling.package_tool_spec import PACKAGE_TOOLS_DIR, validate_package_tool_entrypoint
from agent_factory.tooling.spec import ToolSpec


class PackageToolProvider:
    provider_id = "package"

    def discover(self, context: ToolProviderContext) -> ToolProviderResult:
        if context.package_root is None:
            return ToolProviderResult(
                diagnostics=[diagnostic(self.provider_id, "warning", "package_root is not configured")]
            )
        package_root = context.package_root.resolve()
        tools_root = package_root / PACKAGE_TOOLS_DIR
        if not tools_root.exists():
            return ToolProviderResult()
        result = ToolProviderResult()
        for manifest_path in sorted(tools_root.glob("*/manifest.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                tool_id = str(payload.get("id") or "").strip()
                if tool_id != manifest_path.parent.name:
                    raise ValueError(
                        f"package tool id must match its directory name: id={tool_id}, directory={manifest_path.parent.name}"
                    )
                validate_package_tool_entrypoint(tool_id, str(payload.get("entrypoint") or ""))
                result.tool_specs.append(ToolSpec.model_validate(payload))
            except Exception as exc:
                result.diagnostics.append(
                    diagnostic(
                        self.provider_id,
                        "error",
                        "failed to load package tool manifest",
                        manifest_path=str(manifest_path),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return result
