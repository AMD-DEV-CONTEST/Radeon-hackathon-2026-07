"""Requirement → local app configuration for all specialist modes.

Mirrors the workflow builder pattern for productivity / enterprise / rag / developer / multi.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.config import resolve_data_path


def app_config_dir() -> Path:
    return resolve_data_path("data/app_configs")


def app_export_dir() -> Path:
    return resolve_data_path("data/exports/apps")


_CONFIG_HINTS = (
    "配置",
    "生成配置",
    "自动配置",
    "搭建",
    "初始化",
    "setup",
    "configure",
    "生成助手",
    "创建助手",
)


def wants_app_config(query: str) -> bool:
    return any(h in query.lower() or h in query for h in _CONFIG_HINTS)


def _slug(text: str, prefix: str) -> str:
    raw = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text.strip().lower())
    raw = re.sub(r"_+", "_", raw).strip("_")[:32] or "default"
    ascii_id = re.sub(r"[^a-z0-9_]+", "", raw)
    if len(ascii_id) >= 2:
        return f"{prefix}_{ascii_id}"[:48]
    return f"{prefix}_{abs(hash(text)) % 10_000_000}"


@dataclass
class AppBuildResult:
    app: str
    config_id: str
    path: Path
    export_paths: dict[str, str]
    summary: str


def _write_exports(app: str, config_id: str, payload: dict[str, Any]) -> dict[str, str]:
    base = app_export_dir() / app / config_id
    base.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    yml = base / "config.yaml"
    js = base / "config.json"
    yml.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    js.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    written["yaml"] = str(yml)
    written["json"] = str(js)
    # Dify-like app manifest
    dify = {
        "kind": "dify_app_manifest_like",
        "name": payload.get("title") or config_id,
        "mode": app,
        "model_config": payload.get("model") or {},
        "features": payload.get("features") or {},
        "source_engine": "PrivateLocalAgent",
    }
    dify_path = base / "dify_app.yaml"
    dify_path.write_text(yaml.safe_dump(dify, allow_unicode=True, sort_keys=False), encoding="utf-8")
    written["dify"] = str(dify_path)
    # LangChain-like agent spec
    lc = {
        "kind": "langchain_agent_spec_like",
        "agent_type": app,
        "tools": payload.get("tools") or [],
        "memory": payload.get("memory") or {},
        "retriever": payload.get("retriever") or {},
        "prompt": payload.get("system_prompt") or "",
        "source_engine": "PrivateLocalAgent",
    }
    lc_path = base / "langchain_agent.yaml"
    lc_path.write_text(yaml.safe_dump(lc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    written["langchain"] = str(lc_path)
    return written


def _save_native(app: str, config_id: str, payload: dict[str, Any]) -> Path:
    folder = app_config_dir() / app
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{config_id}.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def build_productivity_config(requirement: str) -> AppBuildResult:
    cid = _slug(requirement, "prod")
    payload = {
        "app": "productivity",
        "id": cid,
        "title": "个人生产力助手配置",
        "requirement": requirement,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "features": {"memory": True, "notes": True, "preferences": True},
        "memory": {
            "seed_facts": [f"用户需求：{requirement[:120]}"],
            "style": "简洁中文" if "中文" in requirement or "简洁" in requirement else "默认",
        },
        "tools": ["save_fact", "write_note", "recall_memory"],
        "system_prompt": "你是个人生产力助手，优先维护本地偏好与备忘，回答简洁可执行。",
        "model": {"backend": "local_transformers"},
    }
    path = _save_native("productivity", cid, payload)
    exports = _write_exports("productivity", cid, payload)
    summary = _summarize("productivity", cid, path, exports, ["记忆种子", "偏好风格", "工具白名单"])
    return AppBuildResult("productivity", cid, path, exports, summary)


def build_enterprise_config(requirement: str) -> AppBuildResult:
    cid = _slug(requirement, "ent")
    packs = []
    for name, keys in {
        "hr": ["请假", "入职", "人事"],
        "it": ["账号", "VPN", "IT"],
        "security": ["涉密", "合规", "安全", "外发"],
        "legal": ["合同", "法务", "保密"],
    }.items():
        if any(k in requirement for k in keys):
            packs.append(name)
    if not packs:
        packs = ["security", "hr"]
    payload = {
        "app": "enterprise",
        "id": cid,
        "title": "企业副驾驶配置",
        "requirement": requirement,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "domain_packs": packs,
        "features": {"privacy_guard": True, "audit": True, "rag": True},
        "tools": ["kb_search", "write_note", "save_fact"],
        "policies": {
            "block_exfiltration": True,
            "prefer_local_only": True,
        },
        "system_prompt": "你是企业副驾驶：给可执行步骤、责任角色、风险提示；禁止建议外发机密到公网。",
        "model": {"backend": "local_transformers"},
    }
    path = _save_native("enterprise", cid, payload)
    exports = _write_exports("enterprise", cid, payload)
    summary = _summarize("enterprise", cid, path, exports, [f"领域包={packs}", "隐私护栏", "审计"])
    return AppBuildResult("enterprise", cid, path, exports, summary)


def build_rag_config(requirement: str) -> AppBuildResult:
    cid = _slug(requirement, "rag")
    payload = {
        "app": "rag",
        "id": cid,
        "title": "本地知识助理配置",
        "requirement": requirement,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "retriever": {
            "top_k": 4,
            "collection": "private_kb",
            "must_ground": True,
            "ingest_plan": ["data/sample_docs", "data/uploads"],
        },
        "tools": ["kb_search", "kb_stats", "list_files"],
        "features": {"force_kb_search": True},
        "system_prompt": "你是本地 RAG 助理：答案必须 grounded 在检索证据，不编造制度。",
        "model": {"backend": "local_transformers"},
    }
    path = _save_native("rag", cid, payload)
    exports = _write_exports("rag", cid, payload)
    summary = _summarize("rag", cid, path, exports, ["强制检索", "ingest 计划", "top_k=4"])
    return AppBuildResult("rag", cid, path, exports, summary)


def build_developer_config(requirement: str) -> AppBuildResult:
    cid = _slug(requirement, "dev")
    skills = ["scaffold_private_agent_mini", "scaffold_fastapi_service"]
    if "ingest" in requirement.lower() or "知识库" in requirement:
        skills.append("scaffold_ingest_pipeline")
    if "仪表盘" in requirement or "dashboard" in requirement.lower():
        skills.append("scaffold_static_dashboard")
    payload = {
        "app": "developer",
        "id": cid,
        "title": "开发者生产力代理配置",
        "requirement": requirement,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tools": ["list_files", "kb_stats", "list_skills", "run_skill", "kb_search"],
        "skills_enabled": skills,
        "features": {"rocm_hints": True, "scaffold": True},
        "output_dir": "data/generated_projects",
        "system_prompt": "你是开发者生产力代理：结合 ROCm/本地推理与仓库约定，可运行技能生成真实项目。",
        "model": {"backend": "local_transformers"},
    }
    path = _save_native("developer", cid, payload)
    exports = _write_exports("developer", cid, payload)
    summary = _summarize("developer", cid, path, exports, [f"技能={skills}", "ROCm 指引"])
    return AppBuildResult("developer", cid, path, exports, summary)


def build_multi_config(requirement: str) -> AppBuildResult:
    cid = _slug(requirement, "multi")
    payload = {
        "app": "multi",
        "id": cid,
        "title": "多代理路由配置",
        "requirement": requirement,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "routing_rules": [
            {"when": ["工作流", "自动化"], "route": "workflow"},
            {"when": ["记住", "备忘", "偏好"], "route": "productivity"},
            {"when": ["合规", "涉密", "企业"], "route": "enterprise"},
            {"when": ["ROCm", "技能", "脚手架"], "route": "developer"},
            {"when": ["政策", "知识库", "FAQ"], "route": "rag"},
            {"when": ["默认"], "route": "chat"},
        ],
        "tools": ["kb_search", "run_workflow", "list_skills", "recall_memory"],
        "features": {"auto_route": True},
        "system_prompt": "你是多代理编排器：按规则路由到专家代理，并汇总结果。",
        "model": {"backend": "local_transformers"},
    }
    path = _save_native("multi", cid, payload)
    exports = _write_exports("multi", cid, payload)
    summary = _summarize("multi", cid, path, exports, ["自动路由规则", "专家协同"])
    return AppBuildResult("multi", cid, path, exports, summary)


def build_for_app(app: str, requirement: str) -> AppBuildResult:
    app = (app or "").strip().lower()
    if app in {"productivity", "个人生产力助手"}:
        return build_productivity_config(requirement)
    if app in {"enterprise", "企业副驾驶"}:
        return build_enterprise_config(requirement)
    if app in {"rag", "本地知识助理"}:
        return build_rag_config(requirement)
    if app in {"developer", "开发者生产力代理"}:
        return build_developer_config(requirement)
    if app in {"multi", "多代理系统"}:
        return build_multi_config(requirement)
    if app in {"workflow", "工作流自动化代理"}:
        # redirect callers to workflow_builder; keep a stub config pointer
        from src.agent.workflow_builder import build_workflow_from_requirement

        wf, path, exports = build_workflow_from_requirement(requirement, auto_export=True)
        summary = (
            f"已配置工作流 `{wf['id']}` → `{path}`\n"
            + "\n".join(f"- {k}: {v}" for k, v in exports.items())
        )
        return AppBuildResult("workflow", wf["id"], Path(path), exports, summary)
    return build_multi_config(requirement)


def _summarize(app: str, cid: str, path: Path, exports: dict[str, str], highlights: list[str]) -> str:
    lines = [
        f"已根据需求完成本地【{app}】应用配置。",
        f"- config_id: `{cid}`",
        f"- 配置文件: `{path}`",
        f"- 要点: {', '.join(highlights)}",
        "",
        "多格式导出（通用 YAML/JSON + Dify-like + LangChain-like）：",
    ]
    for k, p in exports.items():
        lines.append(f"- {k}: `{p}`")
    lines.append("")
    lines.append("之后可直接在该模式下使用；配置均保存在本地 data/ 目录，不上传公网。")
    return "\n".join(lines)
