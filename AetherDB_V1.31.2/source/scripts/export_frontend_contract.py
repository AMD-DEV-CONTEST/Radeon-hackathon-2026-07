"""Export the live FastAPI contract and a UI-planning endpoint guide."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import app
from app.version import APP_VERSION, APP_VERSION_LABEL


OUTPUT_DIR = ROOT / "markdown\u6587\u4ef6\u5b58\u653e\u533a"
OPENAPI_PATH = OUTPUT_DIR / f"openapi_v{APP_VERSION}_frontend.json"
GUIDE_PATH = OUTPUT_DIR / f"API_UI_DESIGN_CONTRACT_{APP_VERSION_LABEL}.md"

FRONTEND_API_DIR = ROOT / "frontend" / "src" / "api"
API_CALL_RE = re.compile(
    r"\b(get|getBlob|post|put|patch|del|upload|streamNdjson)"
    r"\(\s*(`[^`]+`|\"[^\"]+\"|'[^']+')"
)

DOMAIN_ORDER = [
    "startup-auth",
    "workspace",
    "entities-relations",
    "search",
    "books-chapters",
    "import",
    "context-rag",
    "temporal",
    "models-prompts",
    "ollama",
    "vector-index",
    "media-assets",
    "media-generation",
    "audio-contract",
    "backup-admin",
    "legacy-web",
    "other",
]

DOMAIN_RULES = [
    ("startup-auth", ("/api/auth/",)),
    ("workspace", ("/api/databases", "/api/books", "/api/stats", "/api/timeline")),
    ("entities-relations", ("/api/entity", "/api/relation")),
    ("search", ("/api/search",)),
    ("books-chapters", ("/api/chapters", "/api/books/{book_id}/chapters", "/api/changesets")),
    ("import", ("/api/import", "/admin/import")),
    ("context-rag", ("/api/context", "/api/rag", "/api/consistency")),
    ("temporal", ("/api/temporal", "/api/entities/{entity_id}/", "/api/chapters/{chapter_id}/temporal-context")),
    ("models-prompts", ("/api/ai", "/api/model", "/api/prompts", "/api/cache")),
    ("ollama", ("/api/ollama",)),
    ("vector-index", ("/api/vector-index", "/api/index")),
    ("media-assets", ("/api/media-assets",)),
    ("media-generation", ("/api/media-generation",)),
    ("audio-contract", ("/api/audio",)),
    ("backup-admin", ("/api/backup", "/admin")),
]

MODULE_DESCRIPTIONS = {
    "auth.js": "startup credential status and reconnect checks",
    "settings.js": "workspace, active database/book, stats, timeline",
    "chapters.js": "chapter CRUD, autosave, versions, analysis and localization",
    "entities.js": "entity CRUD and relation CRUD",
    "search.js": "keyword, quick, semantic and global search",
    "import.js": "legacy preview/confirm and durable import tasks",
    "changesets.js": "durable ImportChangeSet review and confirmation",
    "context.js": "ContextMap tasks, approvals and EvidencePack",
    "models.js": "providers, model profiles, routing bindings and NDJSON execution",
    "prompts.js": "prompt profile CRUD, activation and test",
    "ollama.js": "Ollama runtime, install operations and model operations",
    "modelRuntime.js": "resource snapshots, policy, admissions, leases, workers and durable jobs",
    "vectorIndex.js": "embedding/vector index status, rebuild and task recovery",
    "backup.js": "backup list/create/restore/cleanup settings",
    "temporal.js": "timelines, anchors, relations, state segments and chapter context",
    "mediaAssets.js": "media import, preview, lifecycle, binding, annotation and cleanup",
    "mediaVision.js": "immutable visual spaces, indexing, migrations and retrieval",
    "mediaGeneration.js": "durable image generation tasks, events, streaming, cancellation and retry",
    "audioContract.js": "AetherDB-routed TTS tasks, voice profiles, pronunciation, waveform, review and binding",
    "modelPackages.js": "trusted model package catalog, license and install operations",
    "client.js": "shared base URL, X-API-Key header, JSON errors and ordered NDJSON stream",
}

UI_SURFACES = {
    "startup-auth": "启动页 / 连接状态 / API Key 输入与有效性提示",
    "workspace": "工作区总览 / 世界库列表 / 当前作品切换 / 统计卡片",
    "entities-relations": "实体编辑器 / 快速创建 / 关系面板 / 删除确认",
    "search": "全局搜索页 / 快速搜索弹层 / 语义搜索结果",
    "books-chapters": "阅读与创作页 / 章节树 / 自动保存 / 分析与变更确认",
    "import": "导入向导 / 预览差异 / 候选选择 / 任务队列",
    "context-rag": "上下文候选审核 / 证据包面板 / 一致性检查",
    "temporal": "时间线设计器 / 事件锚点 / 实体状态历史 / 章节时间上下文",
    "models-prompts": "AI 设置 / 模型供应商 / 模型路由 / Prompt Profile / 流式生成控制台",
    "ollama": "本地模型管理 / 安装任务 / 模型拉取加载卸载",
    "vector-index": "向量索引状态 / 重建任务 / 全局索引维护",
    "media-assets": "媒体资产列表 / 导入 / 预览 / 审批 / 绑定 / 注释 / 清理",
    "media-generation": "创作工作台 / 图像生成任务 / 事件 / 取消 / 重试 / 审批",
    "audio-contract": "创作工作台 / 音频创作 / TTS 路由 / 播放导出 / 审批绑定",
    "backup-admin": "备份管理 / 恢复确认 / 管理员维护工具",
    "legacy-web": "旧 Jinja 页面，仅保留兼容与调试入口",
    "other": "尚未归入稳定 UI 域的接口",
}


def _auth_for(route) -> str:
    names = set()

    def collect(dependant):
        call = getattr(dependant, "call", None)
        if call:
            names.add(getattr(call, "__name__", ""))
        for child in getattr(dependant, "dependencies", []):
            collect(child)

    collect(route.dependant)
    if "require_admin" in names:
        return "admin"
    if "get_current_user_role" in names:
        return "user/admin"
    if "probe_api_key_status" in names:
        return "status-probe"
    return "compatibility/custom"


def _schema_name(operation: dict) -> str:
    body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
    ref = body.get("$ref", "")
    if ref:
        return ref.rsplit("/", 1)[-1]
    return "inline" if body else "-"


def _responses(operation: dict) -> str:
    codes = sorted(operation.get("responses", {}).keys(), key=str)
    return ", ".join(codes) if codes else "-"


def _operation_summary(operation: dict) -> str:
    return operation.get("summary") or operation.get("operationId") or "-"


def _domain_for(path: str) -> str:
    if not path.startswith("/api/") and not path.startswith("/admin"):
        return "legacy-web"
    for domain, prefixes in DOMAIN_RULES:
        if any(path.startswith(prefix) for prefix in prefixes):
            return domain
    return "other"


def _frontend_calls() -> dict[str, list[dict[str, str]]]:
    method_names = {
        "get": "GET",
        "getBlob": "GET",
        "post": "POST",
        "put": "PUT",
        "patch": "PATCH",
        "del": "DELETE",
        "upload": "POST",
        "streamNdjson": "STREAM",
    }
    calls: dict[str, list[dict[str, str]]] = {}
    if not FRONTEND_API_DIR.exists():
        return calls
    for file in sorted(FRONTEND_API_DIR.glob("*.js")):
        if file.name == "client.js":
            calls[file.name] = []
            continue
        module_calls = []
        text = file.read_text(encoding="utf-8")
        for match in API_CALL_RE.finditer(text):
            method, literal = match.groups()
            path = literal[1:-1]
            if not path.startswith("/"):
                continue
            if "${" in path or "buildQuery(" in path or "encodeURIComponent(" in path:
                path = path.split("${", 1)[0] + "{...}"
            module_calls.append({"method": method_names[method], "path": path})
        calls[file.name] = module_calls
    return calls


def _route_rows(schema: dict) -> list[dict[str, str]]:
    route_auth = {
        (method, route.path): _auth_for(route)
        for route in app.routes
        if hasattr(route, "methods") and hasattr(route, "dependant")
        for method in route.methods
    }
    rows = []
    for path, methods in sorted(schema["paths"].items()):
        for method, operation in sorted(methods.items()):
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            rows.append(
                {
                    "domain": _domain_for(path),
                    "method": method.upper(),
                    "path": path,
                    "auth": route_auth.get((method.upper(), path), "unknown"),
                    "tags": ", ".join(operation.get("tags", [])) or "-",
                    "body": _schema_name(operation),
                    "responses": _responses(operation),
                    "summary": _operation_summary(operation),
                }
            )
    return rows


def _write_markdown(schema: dict, rows: list[dict[str, str]], frontend_calls: dict[str, list[dict[str, str]]]) -> None:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["domain"]].append(row)

    auth_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        auth_counts[row["auth"]] += 1

    lines = [
        f"# API 接口定义与前端 UI 规划资料 {APP_VERSION_LABEL}",
        "",
        f"- 导出时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- OpenAPI 标题：{schema['info']['title']}",
        f"- OpenAPI 版本：{schema['info']['version']}",
        f"- OpenAPI paths：{len(schema['paths'])}",
        f"- OpenAPI schemas：{len(schema.get('components', {}).get('schemas', {}))}",
        f"- 接口行数：{len(rows)}",
        f"- 机器可读接口文件：`{OPENAPI_PATH.name}`",
        "- 数据来源：当前 `main.py` 导入后的 FastAPI `app.openapi()`，并交叉引用 `frontend/src/api/*.js`。",
        "",
        "## 1. 前端设计总约束",
        "",
        "- 所有受保护接口使用 `X-API-Key` header；UI 不应把 key 放入 URL、日志、导出文件或可分享状态。",
        "- `admin` 接口需要管理员态；`user/admin` 可用于普通工作流；`status-probe` 只用于无敏感回显的连接检查。",
        "- `compatibility/custom` 多为 legacy Jinja 或兼容入口，不作为新 Vue 页面优先接口。",
        "- 前端请求基址由 `frontend/src/api/client.js` 控制：默认 `/api`，桌面端只允许动态 `127.0.0.1:<port>/api`。",
        "- 流式模型执行使用 NDJSON，UI 需要支持取消、超时、乱序事件缓冲和部分结果保留。",
        "- 409 表示工作流冲突，422 表示输入校验错误，401/403 表示认证或权限状态，5xx 只在接口语义允许时重试。",
        "",
        "## 2. 权限统计",
        "",
        "| Auth | Count | UI 含义 |",
        "|---|---:|---|",
    ]
    auth_meaning = {
        "admin": "管理员设置、破坏性操作、索引/备份/模型管理",
        "user/admin": "普通创作、浏览、查询、上下文与部分章节操作",
        "status-probe": "启动连接状态检查",
        "compatibility/custom": "旧 Web 页面或自定义兼容认证",
        "unknown": "需要人工复核",
    }
    for auth, count in sorted(auth_counts.items()):
        lines.append(f"| `{auth}` | {count} | {auth_meaning.get(auth, '需要人工复核')} |")

    lines.extend(
        [
            "",
            "## 3. 前端 API 模块映射",
            "",
            "| Module | 职责 | 已封装调用 |",
            "|---|---|---|",
        ]
    )
    for module, calls in sorted(frontend_calls.items()):
        sample = ", ".join(f"{call['method']} `{call['path']}`" for call in calls[:6])
        if len(calls) > 6:
            sample += f", ... 共 {len(calls)} 个"
        if not sample:
            sample = "-"
        lines.append(f"| `{module}` | {MODULE_DESCRIPTIONS.get(module, '-')} | {sample} |")

    lines.extend(
        [
            "",
            "## 4. UI 功能域与接口清单",
            "",
        ]
    )
    for domain in DOMAIN_ORDER:
        domain_rows = grouped.get(domain, [])
        if not domain_rows:
            continue
        lines.extend(
            [
                f"### {domain}",
                "",
                f"- UI 规划入口：{UI_SURFACES.get(domain, '-')}",
                f"- 接口数量：{len(domain_rows)}",
                "",
                "| Method | Path | Auth | Body | Responses | Summary |",
                "|---|---|---|---|---|---|",
            ]
        )
        for row in domain_rows:
            lines.append(
                f"| {row['method']} | `{row['path']}` | {row['auth']} | {row['body']} | {row['responses']} | {row['summary']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 5. 关键工作流契约",
            "",
            "### 5.1 启动与认证",
            "",
            "1. UI 启动后读取本地会话中的 API key。",
            "2. 调用 `GET /api/auth/status` 获取最小化状态。",
            "3. 对 401/403 做前端状态切换，不将 key 写入 URL 或长期可同步存储。",
            "",
            "### 5.2 工作区选择",
            "",
            "1. `GET /api/databases` 获取世界库列表。",
            "2. `GET /api/databases/active` 与 `GET /api/books/active` 确定当前上下文。",
            "3. 新建/初始化/删除数据库属于 admin 操作，UI 需要确认与禁用态。",
            "",
            "### 5.3 实体、关系与搜索",
            "",
            "1. 实体创建走 `POST /api/entity`，关系创建走 `POST /api/relation`。",
            "2. 快速搜索走 `GET /api/search/quick`；完整关键词搜索走 `POST /api/search`。",
            "3. 语义和全局搜索应在 UI 上标注数据源、database/book 范围和可能的索引状态。",
            "",
            "### 5.4 章节创作闭环",
            "",
            "1. 章节树来自 `GET /api/books/{book_id}/chapters`。",
            "2. 编辑态使用 autosave/save/version/analyze/changeset/confirm 分步呈现。",
            "3. 不改 ChapterAnalysis v2 与 ImportChangeSet v2 数据结构；UI 只做展示、选择与确认。",
            "",
            "### 5.5 导入向导",
            "",
            "1. 新 UI 优先使用 `/api/import/tasks*` durable task 流程。",
            "2. `/api/import/preview` 与 `/api/import/confirm` 保留兼容，但不作为长期主流程。",
            "3. 确认动作需要 preview hash / selected candidates 一致性校验，UI 需要展示冲突和重试路径。",
            "",
            "### 5.6 模型、Prompt 与生成",
            "",
            "1. Provider/Profile/Binding 分三层管理。",
            "2. 生成使用 `POST /api/model-routing/execute-stream`，前端按 NDJSON event 更新状态。",
            "3. Prompt Profile 更新、激活需要 admin；测试可由 user/admin 调用。",
            "",
            "### 5.7 Context/RAG/Temporal",
            "",
            "1. ContextMap 生成后进入候选审核，再生成 EvidencePack。",
            "2. Temporal 上下文由 timeline、anchor、relation、state segment 与 chapter context 共同决定。",
            "3. UI 需要明确时间点、分支、是否排除未来知识。",
            "",
            "### 5.8 音频创作",
            "",
            "1. TTS 先由唯一模型路由解析到已安装的 AetherDB 原生 TTS Model Profile。",
            "2. Ollama 不属于 TTS 执行后端；权重仅在独立 Audio Worker 中加载。",
            "3. 整章朗读使用持久分段任务，结果先生成媒体资产，再审批并绑定章节。",
            "",
            "### 5.9 管理后台",
            "",
            "1. Backup、Ollama、Vector Index、Global Index 都属于高风险或耗时操作。",
            "2. UI 必须显示任务状态、取消/重试、最后错误和影响范围。",
            "3. Restore/delete/rebuild 类操作需要二次确认。",
            "",
            "## 6. 当前 UI 规划风险",
            "",
            "- legacy Jinja 页面仍存在，不要直接删除；新 Vue UI 规划时保留兼容入口。",
            "- 浏览器访问凭据只保留在 sessionStorage；桌面 Owner 凭据只在进程内存中覆盖，不进入 localStorage。",
            "- BGE-M3 已有 AMD ROCm 实测；可选视觉、图像和 TTS 模型仍需按模型分别取得硬件与质量证据。",
            "- Windows 前端生产构建已通过；`frontend/dist/` 仍是生成物，不纳入 Git。",
            "- 当前工作区仍有较多未提交修改，接口文档用于设计规划，不代表已进入 release candidate。",
            "",
            "## 7. 推荐页面/组件拆分",
            "",
            "| UI 区域 | 主要接口域 | 建议状态模型 |",
            "|---|---|---|",
            "| 顶栏/启动连接 | startup-auth, workspace | authStatus, activeDatabase, activeBook |",
            "| 世界库管理 | workspace, backup-admin | databaseList, activeDatabase, registryHealth |",
            "| 实体工作台 | entities-relations, search, temporal | selectedEntity, relationGraph, temporalState |",
            "| 搜索页 | search, context-rag | query, filters, resultGroups, indexStatus |",
            "| 创作/阅读页 | books-chapters, context-rag, temporal, models-prompts | chapterTree, draft, analysis, changeset, generationStream |",
            "| 多模态创作 | media-assets, media-generation, audio-contract | assets, generationTasks, audioTasks, reviewAndBinding |",
            "| 导入页 | import, changesets | importTask, preview, candidateSelection, confirmReceipt |",
            "| AI 设置 | models-prompts, ollama | providers, profiles, bindings, testResults |",
            "| 管理维护 | backup-admin, vector-index, ollama | operations, cooldowns, auditRelevantActions |",
            "",
            "## 8. 禁止事项",
            "",
            "- 不要为了 UI 规划改 V1.31.2 已冻结的创作闭环数据契约。",
            "- 不要改 ChapterAnalysis v2 / ImportChangeSet v2 结构。",
            "- 不要重构认证系统。",
            "- 不要删除 legacy Jinja。",
            "- 不要把 API key 放入 query string、localStorage 新字段、日志或导出文档。",
            "- 不要提交 `config.local.yaml`、`.api_keys.json`、`.env`、`app_data/`、`logs/`、`frontend/node_modules/`、`frontend/dist/`。",
        ]
    )
    GUIDE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    OPENAPI_PATH.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = _route_rows(schema)
    frontend_calls = _frontend_calls()
    _write_markdown(schema, rows, frontend_calls)
    print(f"Exported {len(schema['paths'])} paths and {len(rows)} endpoint rows")
    print(f"OpenAPI: {OPENAPI_PATH}")
    print(f"Guide: {GUIDE_PATH}")


if __name__ == "__main__":
    export()
