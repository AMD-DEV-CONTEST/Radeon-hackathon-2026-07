"""Persistent workflow registry — load/save YAML under data/workflows/."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.agent.workflow_schema import normalize_workflow
from src.config import resolve_data_path


def workflows_dir() -> Path:
    return resolve_data_path("data/workflows")

# Built-in office templates (seeded to disk on first ensure)
BUILTIN_WORKFLOWS: dict[str, dict[str, Any]] = {
    "leave_request": {
        "id": "leave_request",
        "title": "请假办理工作流",
        "description": "检索请假政策与远程约束，写入办理备忘",
        "keywords": ["请假办理", "办理请假", "请假流程", "leave workflow", "办理请假流程"],
        "steps": [
            {"id": "kb_policy", "label": "检索请假政策", "tool": "kb_search", "args": {"query": "请假提前几天 年假 审批"}},
            {"id": "kb_remote", "label": "核对远程办公约束", "tool": "kb_search", "args": {"query": "远程办公 一周几天"}},
            {"id": "memory", "label": "写入办理备忘", "tool": "write_note", "args": {"note": "用户正在办理请假，需按政策提前申请并完成审批。"}},
        ],
    },
    "it_onboarding": {
        "id": "it_onboarding",
        "title": "入职 IT 开通工作流",
        "description": "VPN/许可证/文档位置一键办理指引",
        "keywords": ["入职", "开通账号", "onboarding", "IT开通", "入职IT"],
        "steps": [
            {"id": "vpn", "label": "VPN / 账号指引", "tool": "kb_search", "args": {"query": "VPN 密码 MFA"}},
            {"id": "license", "label": "软件许可证申请", "tool": "kb_search", "args": {"query": "软件许可证 ServiceDesk"}},
            {"id": "docs", "label": "文档存放位置", "tool": "kb_search", "args": {"query": "设计文档 Projects/Design"}},
            {"id": "fact", "label": "记录入职清单", "tool": "save_fact", "args": {"fact": "入职IT清单：VPN、许可证、知识库权限"}},
        ],
    },
    "security_selfcheck": {
        "id": "security_selfcheck",
        "title": "涉密与 AI 合规自检工作流",
        "description": "允许的 AI 工具与数据外发约束自检",
        "keywords": ["安全自检", "合规自检", "涉密自检"],
        "steps": [
            {"id": "ai", "label": "允许的 AI 工具", "tool": "kb_search", "args": {"query": "涉密文档 AI 工具 PrivateLocalAgent"}},
            {"id": "privacy", "label": "数据外发约束", "tool": "kb_search", "args": {"query": "客户名单 微信 明文密码"}},
            {"id": "note", "label": "写入合规备忘", "tool": "write_note", "args": {"note": "已完成涉密/AI合规自检：仅本地 Agent，禁止公网粘贴机密。"}},
        ],
    },
    "dev_handoff": {
        "id": "dev_handoff",
        "title": "开发者交接工作流",
        "description": "ROCm/文件/知识库状态交接",
        "keywords": ["开发交接", "环境交接", "dev handoff"],
        "steps": [
            {"id": "gpu", "label": "GPU/ROCm 要求", "tool": "kb_search", "args": {"query": "GPU ROCm Track 2 推理"}},
            {"id": "files", "label": "查看上传/工作文件", "tool": "list_files", "args": {}},
            {"id": "stats", "label": "知识库状态", "tool": "kb_stats", "args": {}},
            {"id": "fact", "label": "记录交接要点", "tool": "save_fact", "args": {"fact": "开发交接：本地 ROCm 推理 + 私有 RAG + demo notebook"}},
        ],
    },
}


class WorkflowRegistry:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or workflows_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] | None = None

    def ensure_seeded(self) -> None:
        for wid, meta in BUILTIN_WORKFLOWS.items():
            path = self.directory / f"{wid}.yaml"
            if not path.exists():
                self.save(normalize_workflow(meta, wid))

    def invalidate(self) -> None:
        self._cache = None

    def all(self) -> dict[str, dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        self.ensure_seeded()
        out: dict[str, dict[str, Any]] = {}
        for path in sorted(self.directory.glob("*.yaml")) + sorted(self.directory.glob("*.yml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not isinstance(data, dict):
                    continue
                wf = normalize_workflow(data, path.stem)
                out[wf["id"]] = wf
            except Exception:  # noqa: BLE001
                continue
        # builtins fill gaps
        for wid, meta in BUILTIN_WORKFLOWS.items():
            out.setdefault(wid, normalize_workflow(meta, wid))
        self._cache = out
        return out

    def get(self, workflow_id: str) -> dict[str, Any] | None:
        return self.all().get(workflow_id)

    def save(self, workflow: dict[str, Any]) -> Path:
        from src.security.paths import is_under, sanitize_id

        wf = normalize_workflow(workflow, str(workflow.get("id") or "custom"))
        wf["id"] = sanitize_id(str(wf["id"]), "custom")
        path = (self.directory / f"{wf['id']}.yaml").resolve()
        if not is_under(path, self.directory):
            raise ValueError("invalid workflow id path")
        path.write_text(
            yaml.safe_dump(wf, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        self.invalidate()
        return path

    def path_for(self, workflow_id: str) -> Path:
        return self.directory / f"{workflow_id}.yaml"


_REGISTRY: WorkflowRegistry | None = None


def get_registry() -> WorkflowRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = WorkflowRegistry()
    return _REGISTRY
