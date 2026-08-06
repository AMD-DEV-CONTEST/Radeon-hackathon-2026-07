"""Export backend API endpoints that are not used by the Vue runtime.

This script is intentionally separate from the broad coverage audit. Its output
is a planning document: each unused endpoint is grouped by product domain and
annotated with current frontend state, likely purpose, and recommended next use.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from fastapi.routing import APIRoute


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import app  # noqa: E402
from app.version import APP_VERSION_LABEL  # noqa: E402


API_DIR = ROOT / "frontend" / "src" / "api"
FRONTEND_SRC = ROOT / "frontend" / "src"
REPORT_PATH = (
    ROOT
    / "markdown文件存放区"
    / f"UNUSED_API_ENDPOINTS_EXPORT_{APP_VERSION_LABEL}.md"
)

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
CALL_METHODS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "del": "DELETE",
    "streamNdjson": "POST",
}

EXPORT_RE = re.compile(r"export\s+(?:const|function)\s+(\w+)")
CALL_RE = re.compile(r"\b(get|post|put|patch|del|streamNdjson)\(\s*([`\"'])(.*?)\2", re.DOTALL)
IMPORT_RE = re.compile(
    r"import\s*\{([^}]*)\}\s*from\s*[\"']([^\"']*/api/([^\"']+))[\"']",
    re.DOTALL,
)


DOMAIN_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("启动与认证", ("/api/auth",)),
    ("工作区与世界库", ("/api/databases", "/api/books", "/api/stats", "/api/timeline")),
    ("章节与设定变更", ("/api/chapters", "/api/changesets")),
    ("实体与关系", ("/api/entity", "/api/relation")),
    ("搜索", ("/api/search",)),
    ("导入", ("/api/import",)),
    ("Context/RAG 审核", ("/api/context", "/api/rag", "/api/consistency")),
    ("时态与时间线", ("/api/temporal", "/api/entities")),
    ("模型与 Prompt", ("/api/ai", "/api/cache", "/api/model", "/api/prompts")),
    ("Ollama 本地模型", ("/api/ollama",)),
    ("向量索引与硬件加速", ("/api/vector-index", "/api/index")),
    ("媒体资产", ("/api/media-assets",)),
    ("视觉检索", ("/api/media-vision",)),
    ("媒体生成", ("/api/media-generation",)),
    ("音频创作", ("/api/audio",)),
    ("备份与管理", ("/api/backup",)),
]


PURPOSE_RULES: list[tuple[str, str, str]] = [
    (r"/api/auth/status", "探测当前 API Key / 管理员凭据状态。", "启动页、设置页和降级提示可用它显示认证状态。"),
    (r"/api/backup/cleanup", "清理过期或多余的备份文件。", "放入设置页的备份维护区，作为管理员操作。"),
    (r"/api/chapters/\{chapter_id\}$", "删除指定章节。", "用于章节管理、回收站或危险操作确认流程。"),
    (r"/api/chapters/\{chapter_id\}/changeset/confirm", "确认当前章节最近一次设定变更集。", "可接入章节审核面板的一键确认，但需要避免绕过预览。"),
    (r"/api/chapters/\{chapter_id\}/temporal-context", "读取或写入章节绑定的时间线/锚点上下文。", "用于沉浸写作区的时态选择、章节时间定位和冲突检查。"),
    (r"/api/consistency/check", "对当前设定、关系或文本进行一致性检查。", "应进入 AI 辅助侧栏的冲突检查结果流。"),
    (r"/api/context/map", "生成 ContextMap 候选任务。", "用于模型调用前的取证范围构建，不应直接写库。"),
    (r"/api/context/tasks$", "列出 ContextMap 任务。", "用于 AI 辅助任务中心和失败恢复。"),
    (r"/api/context/tasks/\{task_id\}/candidates", "读取 ContextMap 候选证据。", "用于用户确认哪些资料可进入模型上下文。"),
    (r"/api/context/tasks/\{task_id\}/approval", "提交 ContextMap 候选批准结果。", "用于确认后生成可信上下文。"),
    (r"/api/context/tasks/\{task_id\}/evidence-pack", "生成 EvidencePack。", "用于模型执行前的证据包，不应暴露为普通技术页面。"),
    (r"/api/rag/context", "旧式或兼容型 RAG 上下文接口。", "先标记兼容/待归档，避免和 ContextMap 新流程重复。"),
    (r"/api/entity/\{entity_id\}$", "更新或删除实体。", "用于实体详情页、快速创建后的修订和世界库管理。"),
    (r"/api/relation$", "创建实体关系。", "用于图谱编辑器和快速创建后的关系补录。"),
    (r"/api/import/(preview|confirm)$", "旧式导入预览/确认。", "应和任务化导入接口合并职责，避免双流程。"),
    (r"/api/import/tasks/\{task_id\}/analyze", "触发导入任务分析。", "用于批量导入页的手动重新分析按钮。"),
    (r"/api/ai/config", "读取或保存旧 AI 配置。", "若仍保留，应迁移到 AI 设置与管理页或标记废弃。"),
    (r"/api/ai/local/check-runtime", "检查本地 AI 运行时。", "用于本地部署/高级设置的状态分支。"),
    (r"/api/ai/model-profiles", "旧模型画像列表接口。", "需要确认与 `/api/model-profiles` 是否重复。"),
    (r"/api/ai/status", "旧 AI 引擎状态接口。", "需要确认是否被 AI Management overview 替代。"),
    (r"/api/ai/test-(cloud|local)", "测试云端或本地模型连通性。", "应进入供应商配置弹窗或本地部署面板。"),
    (r"/api/cache/stats", "读取模型/向量/RAG 缓存统计。", "可放入高级设置或诊断页。"),
    (r"/api/model-profiles/\{profile_id\}$", "读取单个模型配置详情。", "用于模型配置详情抽屉，当前列表页可能只用批量数据。"),
    (r"/api/model-providers/\{provider_id\}$", "读取单个供应商详情。", "用于供应商详情抽屉或编辑前刷新。"),
    (r"/api/model-routing/execute-stream", "按任务路由执行模型，并以 NDJSON 流返回。", "用于 AI 辅助真实生成/分析流式输出。"),
    (r"/api/model-routing/recovery/\{ticket_id\}/confirm", "确认模型故障恢复候选。", "用于模型失败时让用户确认降级或切换模型。"),
    (r"/api/ollama/models$", "列出 Ollama 本地模型。", "用于本地模型列表；当前 store 未直接使用该 SDK。"),
    (r"/api/ollama/models/sync", "同步 Ollama 本地模型状态。", "用于本地部署页的刷新/同步按钮。"),
    (r"/api/prompts/profiles/\{pid\}$", "读取单个 Prompt Profile。", "用于模板详情、测试前预览或版本回滚。"),
    (r"/api/search/quick", "轻量快速搜索。", "可用于顶部命令栏、实体选择器和引用补全。"),
    (r"/api/entities/\{entity_id\}/resolved-state", "按时间锚点解析实体在某时刻的状态。", "用于读者百科、写作侧栏和时态图谱。"),
    (r"/api/entities/\{entity_id\}/state-history", "读取实体状态演化历史。", "用于角色成长线、状态变更审计和时间线页面。"),
    (r"/api/temporal/anchors", "创建或列出故事时间锚点。", "用于时间线编辑器和章节时间定位。"),
    (r"/api/temporal/timelines", "创建或列出时间线。", "用于世界设定中的主线/支线时间结构。"),
    (r"/api/temporal/relations", "创建或列出时序偏序关系。", "用于事件先后关系、冲突检查和图谱过滤。"),
    (r"/api/temporal/state-segments", "创建实体状态片段。", "用于记录人物年龄、身份、立场等随时间变化的状态。"),
    (r"/api/temporal/events/\{event_id\}/metadata", "读取或写入时间事件元数据。", "用于事件详情页和时间线维护。"),
    (r"/api/entity/\{entity_id\}/translate", "翻译实体内容。", "用于多语言设定库或导出。"),
    (r"/api/entity/\{entity_id\}/translations", "读取实体已有翻译。", "用于翻译管理和多语言阅读。"),
    (r"/api/index/(rebuild|status|sync)", "旧式全文/全局索引维护接口。", "需要确认与 `/api/vector-index/*` 的边界。"),
    (r"/api/vector-index/status", "读取指定数据库向量索引状态。", "用于高级索引维护和硬件加速诊断。"),
    (r"/api/vector-index/rebuild", "发起向量索引重建任务。", "用于数据库管理或索引维护页。"),
    (r"/api/vector-index/tasks", "创建或列出向量索引任务。", "用于后台任务中心和索引维护。"),
    (r"/api/vector-index/tasks/\{task_id\}/cancel", "取消正在执行的向量索引任务。", "用于索引任务详情页的停止操作。"),
    (r"/api/vector-index/tasks/\{task_id\}/retry-failed", "重试向量索引任务中的失败项。", "用于失败恢复，不需要重建全部索引。"),
    (r"/api/vector-index/tasks/\{task_id\}", "读取指定向量索引任务详情。", "用于任务详情、失败原因和进度展示。"),
    (r"/api/audio/tasks", "创建、列出或读取持久音频任务。", "用于创作工作台的 TTS 分段执行、取消、重试和结果恢复。"),
    (r"/api/audio/voice-profiles", "管理作品范围的声音配置。", "仅把已安装的 AetherDB TTS Worker 模型用于原生声音执行。"),
    (r"/api/audio/pronunciations", "管理作品发音词典。", "用于 TTS 分段前的服务端文本规范化。"),
    (r"/api/audio/results/.*/review", "审批或拒绝音频结果。", "审批后才允许作为正式媒体绑定到章节。"),
    (r"/api/books/\{book_id\}", "读取或删除指定作品/世界。", "用于世界管理详情页和危险操作确认。"),
    (r"/api/databases/\{database_id\}", "读取或删除指定数据库/分组。", "用于数据库管理详情页和危险操作确认。"),
    (r"/api/databases/\{database_id\}/validate", "校验数据库结构与可用性。", "用于数据库管理页的健康检查。"),
]


RECOMMENDATION_RULES: list[tuple[str, str]] = [
    (r"/api/context|/api/consistency|/api/rag|/api/model-routing/execute-stream|/api/model-routing/recovery", "P1：接入 AI 辅助的取证、审批、流式执行和故障恢复闭环。"),
    (r"/api/temporal|/api/entities/.*/.*state|/api/chapters/.*/temporal-context", "P1：建设时间线/时态编辑器，不要塞进普通写作按钮。"),
    (r"/api/vector-index|/api/index", "P1：进入高级索引维护与硬件加速诊断；旧 `/api/index/*` 先做兼容性归类。"),
    (r"/api/ollama/models", "P1：接入本地部署模型列表与同步能力，服务 AI 设置与管理页。"),
    (r"/api/audio", "P1：保持音频创作、持久任务、结果审批与章节绑定闭环；TTS 不走 Ollama。"),
    (r"/api/media-generation|/api/media-vision|/api/media-assets", "P1：保持多模态创作、检索、审批与正式绑定边界。"),
    (r"/api/chapters", "P1：接入章节管理、时态上下文和设定变更确认流程。"),
    (r"/api/search/quick", "P2：用于顶部命令栏、实体选择器和引用补全。"),
    (r"/api/entity/.*/translate|/api/entity/.*/translations", "P2：进入多语言实体管理或导出流程。"),
    (r"/api/entity|/api/relation", "P2：补齐实体详情编辑、删除和图谱关系创建。"),
    (r"/api/import/(preview|confirm)", "P2：确认是否废弃旧导入流程，避免和任务化导入重复。"),
    (r"/api/ai/config|/api/ai/status|/api/ai/model-profiles", "P2：和新版 AI Management 接口做去重/废弃标记。"),
    (r"/api/books|/api/databases", "P2：进入数据库/世界管理详情页，危险操作必须二次确认。"),
    (r"/api/backup/cleanup", "P2：放入备份维护区，默认只显示给高级/管理员用户。"),
]


def auth_for(route: APIRoute) -> str:
    names: set[str] = set()

    def collect(dependant) -> None:
        call = getattr(dependant, "call", None)
        if call:
            names.add(getattr(call, "__name__", ""))
        for child in getattr(dependant, "dependencies", []):
            collect(child)

    collect(route.dependant)
    if "require_admin" in names:
        return "管理员"
    if "get_current_user_role" in names or "get_api_key" in names:
        return "普通/管理员"
    if "probe_api_key_status" in names:
        return "状态探测"
    if "require_desktop_handshake" in names:
        return "桌面握手"
    return "兼容/自定义"


def domain_for(path: str) -> str:
    if path.endswith("/translate") or path.endswith("/translations"):
        return "翻译"
    for domain, prefixes in DOMAIN_RULES:
        if any(path.startswith(prefix) for prefix in prefixes):
            return domain
    if path.startswith("/api/"):
        return "其他 API"
    return "旧 Web/桌面"


def normalize_sdk_path(path: str) -> str:
    path = path.split("${buildQuery", 1)[0]
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]+\}", "{}", path)
    return "/api" + path if path.startswith("/") else "/api/" + path


def paths_match(sdk_path: str, route_path: str) -> bool:
    left = sdk_path.strip("/").split("/")
    right = route_path.strip("/").split("/")
    if len(left) != len(right):
        return False
    return all(a == b or (a.startswith("{") and b.startswith("{")) for a, b in zip(left, right))


def scan_sdk_exports() -> list[dict[str, str]]:
    wrappers: list[dict[str, str]] = []
    for file in sorted(API_DIR.glob("*.js")):
        if file.name == "client.js":
            continue
        source = file.read_text(encoding="utf-8")
        exports = list(EXPORT_RE.finditer(source))
        for index, match in enumerate(exports):
            end = exports[index + 1].start() if index + 1 < len(exports) else len(source)
            block = source[match.start():end]
            for call in CALL_RE.finditer(block):
                wrappers.append(
                    {
                        "module": file.stem,
                        "symbol": match.group(1),
                        "method": CALL_METHODS[call.group(1)],
                        "path": normalize_sdk_path(call.group(3)),
                    }
                )
    return wrappers


def scan_runtime_imports() -> dict[tuple[str, str], list[str]]:
    references: dict[tuple[str, str], list[str]] = defaultdict(list)
    for file in sorted(FRONTEND_SRC.rglob("*")):
        if file.suffix not in {".js", ".ts", ".vue"} or API_DIR in file.parents:
            continue
        source = file.read_text(encoding="utf-8")
        for match in IMPORT_RE.finditer(source):
            module = Path(match.group(3)).stem
            for raw_name in match.group(1).split(","):
                imported = raw_name.strip().split(" as ", 1)[0].strip()
                if imported and len(re.findall(rf"\b{re.escape(imported)}\b", source)) > 1:
                    references[(module, imported)].append(file.relative_to(ROOT).as_posix())
    return references


def collect_routes() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted((route.methods or set()) & HTTP_METHODS):
            rows.append(
                {
                    "method": method,
                    "path": route.path,
                    "auth": auth_for(route),
                    "domain": domain_for(route.path),
                    "name": route.name,
                    "summary": route.summary or "",
                }
            )
    return sorted(rows, key=lambda row: (row["domain"], row["path"], row["method"]))


def purpose_for(path: str, method: str, name: str) -> tuple[str, str]:
    key = f"{method} {path}"
    for pattern, meaning, usage in PURPOSE_RULES:
        if re.search(pattern, path):
            return meaning, usage
    if method == "GET":
        return f"读取 `{name}` 相关数据。", "适合接入详情页、选择器、诊断面板或后台任务页。"
    if method == "POST":
        return f"创建、触发或提交 `{name}` 操作。", "适合接入明确的用户操作按钮，并补充成功/失败反馈。"
    if method == "PUT":
        return f"更新 `{name}` 相关资源。", "适合接入编辑表单，提交前需要保留用户确认和错误提示。"
    if method == "DELETE":
        return f"删除 `{name}` 相关资源。", "适合接入危险操作区，需要二次确认和可恢复策略。"
    return f"`{name}` 后端能力。", "需要先明确产品入口再接入。"


def recommendation_for(path: str) -> str:
    for pattern, recommendation in RECOMMENDATION_RULES:
        if re.search(pattern, path):
            return recommendation
    return "待规划：先确认是否属于正式能力、兼容接口或内部接口。"


def main() -> None:
    routes = collect_routes()
    wrappers = scan_sdk_exports()
    runtime_refs = scan_runtime_imports()

    for route in routes:
        matches = [
            wrapper
            for wrapper in wrappers
            if wrapper["method"] == route["method"] and paths_match(wrapper["path"], route["path"])
        ]
        active = [wrapper for wrapper in matches if (wrapper["module"], wrapper["symbol"]) in runtime_refs]
        if route["path"].startswith("/api/"):
            if active:
                status = "UI used"
            elif matches:
                status = "SDK only"
            else:
                status = "not integrated"
        else:
            status = "legacy/desktop"
        route["status"] = status
        route["wrappers"] = ", ".join(f"{item['module']}.{item['symbol']}" for item in matches) or "-"
        meaning, usage = purpose_for(route["path"], route["method"], route["name"])
        route["meaning"] = meaning
        route["usage"] = usage
        route["recommendation"] = recommendation_for(route["path"])

    unused_api = [row for row in routes if row["path"].startswith("/api/") and row["status"] != "UI used"]
    by_domain: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in unused_api:
        by_domain[row["domain"]].append(row)

    api_routes = [row for row in routes if row["path"].startswith("/api/")]
    counts = Counter(row["status"] for row in api_routes)
    domain_counts = {
        domain: Counter(row["status"] for row in rows)
        for domain, rows in by_domain.items()
    }

    lines = [
        f"# 未被前端使用的 API Endpoint 导出 {APP_VERSION_LABEL}",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- FastAPI `/api/*` endpoint 总数：**{len(api_routes)}**",
        f"- Vue/Tauri 运行时已使用：**{counts['UI used']}**",
        f"- 未被运行时使用合计：**{len(unused_api)}**",
        f"- 已有前端 SDK 但页面未调用：**{counts['SDK only']}**",
        f"- 后端存在但前端没有 SDK 封装：**{counts['not integrated']}**",
        "",
        "## 口径说明",
        "",
        "- 本文中的“端口”按项目语境理解为后端 API endpoint，不是 TCP 监听端口。",
        "- `SDK only`：`frontend/src/api` 已封装，但 Vue 页面、组件或 Pinia store 运行时代码没有调用。",
        "- `not integrated`：FastAPI 已暴露接口，但前端没有对应 SDK 封装，也没有页面入口。",
        "- 旧 Jinja Web 路由和 Tauri 桌面握手不计入未使用 API 数量。",
        "- 该报告是静态接线审查，不等价于完整端到端验收；后续接入时仍需补权限、失败分支和 UI 状态。",
        "",
        "## 汇总",
        "",
        "| 功能域 | 未使用合计 | SDK only | not integrated | 主要处理方向 |",
        "|---|---:|---:|---:|---|",
    ]
    for domain in sorted(by_domain):
        counter = domain_counts[domain]
        direction = recommendation_for(by_domain[domain][0]["path"])
        lines.append(
            f"| {domain} | {len(by_domain[domain])} | {counter['SDK only']} | "
            f"{counter['not integrated']} | {direction} |"
        )

    lines.extend(
        [
            "",
            "## 详细清单",
            "",
        ]
    )

    for domain in sorted(by_domain):
        lines.extend(
            [
                f"### {domain}",
                "",
                "| 状态 | Method | Endpoint | 权限 | SDK | 具体含义 | 作用/后续入口 | 建议 |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for row in by_domain[domain]:
            lines.append(
                f"| {row['status']} | {row['method']} | `{row['path']}` | {row['auth']} | "
                f"`{row['wrappers']}` | {row['meaning']} | {row['usage']} | {row['recommendation']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 优先级整理",
            "",
            "1. P1：优先处理报告中仍为 `SDK only` 或 `not integrated` 的恢复、维护和高级诊断接口；核心 Context、时态、向量与多模态链路已有 UI。",
            "2. P2：实体编辑/删除、关系创建、世界/数据库详情与危险操作、备份清理、快速搜索。这些属于管理体验补齐。",
            "3. P2：旧 `/api/ai/*`、旧 `/api/index/*`、旧导入 preview/confirm 需要先标注 retained/deprecated/internal，再决定是否继续做 UI。",
            "4. P3：翻译接口和缓存统计可以等待多语言导出、诊断中心或高级设置页规划明确后接入。",
            "",
            "## 对后续规划的直接影响",
            "",
            "- 不建议追求 100% 接口全部上页面。先把兼容接口、内部接口和新版正式接口分层，否则 UI 会重复且维护成本上升。",
            "- 写作主链路已接入 ContextMap -> EvidencePack -> Model streaming -> ChangeSet preview/confirm；后续重点是失败恢复和体验验证。",
            "- 音频创作必须保持 AetherDB 唯一路由 -> Audio Worker -> temporary media -> 审批绑定，不能改走 Ollama。",
            "- 知识图谱和时间线后续要复用 Temporal 与 relation 接口，图谱页继续保持数据模型和渲染层解耦。",
            "- 向量索引任务、ROCm 状态和本地模型部署应放在 AI 设置与管理/高级维护区，避免干扰普通创作入口。",
        ]
    )

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")
    print(
        f"API={len(api_routes)} UI used={counts['UI used']} "
        f"SDK only={counts['SDK only']} not integrated={counts['not integrated']} unused={len(unused_api)}"
    )


if __name__ == "__main__":
    main()
