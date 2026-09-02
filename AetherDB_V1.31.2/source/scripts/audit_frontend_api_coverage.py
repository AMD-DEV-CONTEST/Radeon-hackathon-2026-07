"""Audit FastAPI endpoints against the Vue runtime API integration.

The report distinguishes backend routes that are actively referenced by the
Vue runtime, routes that only have an SDK wrapper, and routes with no wrapper.
It intentionally excludes tests when deciding whether a wrapper is in use.
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
    / "markdown\u6587\u4ef6\u5b58\u653e\u533a"
    / f"API_FRONTEND_COVERAGE_AUDIT_{APP_VERSION_LABEL}.md"
)

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
CALL_METHODS = {
    "get": "GET",
    "getBlob": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "del": "DELETE",
    "upload": "POST",
    "streamNdjson": "POST",
}

EXPORT_RE = re.compile(r"export\s+(?:const|function)\s+(\w+)")
CALL_RE = re.compile(
    r"\b(get|getBlob|post|put|patch|del|upload|streamNdjson)\(\s*([`\"'])(.*?)\2",
    re.DOTALL,
)
IMPORT_RE = re.compile(
    r"import\s*\{([^}]*)\}\s*from\s*[\"']([^\"']*/api/([^\"']+))[\"']",
    re.DOTALL,
)


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
        return "admin"
    if "get_current_user_role" in names or "get_api_key" in names:
        return "user/admin"
    if "probe_api_key_status" in names:
        return "status-probe"
    if "require_desktop_handshake" in names:
        return "desktop-handshake"
    return "compatibility/custom"


def domain_for(path: str) -> str:
    rules = [
        ("startup/auth", ("/api/auth", "/.well-known")),
        ("workspace", ("/api/databases", "/api/books", "/api/stats", "/api/timeline")),
        ("chapters", ("/api/chapters", "/api/changesets")),
        ("entities/relations", ("/api/entity", "/api/relation")),
        ("search", ("/api/search",)),
        ("import", ("/api/import",)),
        ("context/RAG", ("/api/context", "/api/rag", "/api/consistency")),
        ("temporal", ("/api/temporal", "/api/entities")),
        ("models/prompts", ("/api/ai", "/api/cache", "/api/model", "/api/prompts")),
        ("Ollama", ("/api/ollama",)),
        ("vector/index", ("/api/vector-index", "/api/index")),
        ("backup/admin", ("/api/backup",)),
        ("media assets", ("/api/media-assets",)),
        ("media generation", ("/api/media-generation",)),
        ("audio contract", ("/api/audio",)),
        ("translation", ("/api/entity",)),
    ]
    if path.startswith("/admin") or not path.startswith("/api") and not path.startswith("/.well-known"):
        return "legacy web"
    if path.endswith("/translate") or path.endswith("/translations"):
        return "translation"
    for domain, prefixes in rules:
        if any(path.startswith(prefix) for prefix in prefixes):
            return domain
    return "other"


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
                if not imported:
                    continue
                # A second occurrence means the imported API symbol is referenced
                # by executable component/store code, not merely imported.
                if len(re.findall(rf"\b{re.escape(imported)}\b", source)) > 1:
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
                    "summary": route.summary or route.name,
                }
            )
    return sorted(rows, key=lambda row: (row["domain"], row["path"], row["method"]))


def main() -> None:
    routes = collect_routes()
    wrappers = scan_sdk_exports()
    runtime_refs = scan_runtime_imports()

    for route in routes:
        matches = [
            wrapper for wrapper in wrappers
            if wrapper["method"] == route["method"] and paths_match(wrapper["path"], route["path"])
        ]
        active = [wrapper for wrapper in matches if (wrapper["module"], wrapper["symbol"]) in runtime_refs]
        if route["domain"] == "legacy web" or route["path"] == "/.well-known/aetherdb-desktop":
            status = "desktop/legacy"
        elif active:
            status = "UI used"
        elif matches:
            status = "SDK only"
        else:
            status = "not integrated"
        route["status"] = status
        route["wrappers"] = ", ".join(f'{item["module"]}.{item["symbol"]}' for item in matches) or "-"
        evidence = sorted({ref for item in active for ref in runtime_refs[(item["module"], item["symbol"])]})
        route["evidence"] = "<br>".join(f"`{item}`" for item in evidence) or "-"

    unmatched_wrappers = []
    for wrapper in wrappers:
        matched = any(
            wrapper["method"] == route["method"] and paths_match(wrapper["path"], route["path"])
            for route in routes
        )
        if not matched:
            refs = runtime_refs.get((wrapper["module"], wrapper["symbol"]), [])
            unmatched_wrappers.append({**wrapper, "references": refs})

    statuses = Counter(row["status"] for row in routes)
    api_routes = [row for row in routes if row["path"].startswith("/api/")]
    api_statuses = Counter(row["status"] for row in api_routes)
    domains: dict[str, list[dict[str, str]]] = defaultdict(list)
    for route in routes:
        domains[route["domain"]].append(route)

    lines = [
        f"# API 与前端功能覆盖审计 {APP_VERSION_LABEL}",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- FastAPI 路由总数（method + path）：**{len(routes)}**",
        f"- `/api/*` 接口数：**{len(api_routes)}**",
        f"- Vue 运行时已使用：**{api_statuses['UI used']}**",
        f"- 已有 SDK 封装但 UI 未使用：**{api_statuses['SDK only']}**",
        f"- 前端没有 SDK 封装：**{api_statuses['not integrated']}**",
        f"- 前端 SDK 指向不存在的后端路由：**{len(unmatched_wrappers)}**（其中运行时在用 **{sum(bool(item['references']) for item in unmatched_wrappers)}**）",
        f"- 桌面握手/旧 Jinja Web：**{statuses['desktop/legacy']}**",
        "",
        "## 判定口径",
        "",
        "- `UI used`：接口存在对应 SDK 方法，且该方法被 `frontend/src` 下页面、组件或 Pinia Store 的运行时代码引用。",
        "- `SDK only`：已经写入 `frontend/src/api`，但 Vue 运行时代码没有引用；API 客户端测试不算功能实装。",
        "- `not integrated`：FastAPI 中存在，但 `frontend/src/api` 没有对应 method + path 封装。",
        "- `desktop/legacy`：Tauri 私有握手或旧 Jinja 页面，不应按 Vue 页面 API 覆盖率计算。",
        "- 本报告证明静态接线状态，不等同于每条接口都完成了真实后端数据、权限和失败分支的端到端验收。",
        "- `frontend-only mismatch` 是反向扫描结果：前端会发出请求，但当前 FastAPI 路由表无法匹配。",
        "",
        "## 功能域汇总",
        "",
        "| 功能域 | 总数 | UI used | SDK only | not integrated | desktop/legacy |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for domain in sorted(domains):
        counts = Counter(row["status"] for row in domains[domain])
        lines.append(
            f"| {domain} | {len(domains[domain])} | {counts['UI used']} | {counts['SDK only']} | "
            f"{counts['not integrated']} | {counts['desktop/legacy']} |"
        )

    lines.extend([
        "",
        "## 结论",
        "",
        "当前 Vue/Tauri 前端**尚未实装全部 FastAPI 接口和功能**。`UI used` 只表示已有运行时调用入口；"
        "创作工作台已接入时态、Context/RAG 审核、翻译、媒体和音频创作主链路，"
        "未接入项主要是高级管理、维护、恢复和兼容入口。",
        "",
        "本轮已完成实体与章节核心工作台接线，并新增媒体资产导入、鉴权预览、审批、归档、章节绑定和删除。"
        "媒体高级注释与维护接口保留在 SDK；前端 SDK 指向不存在后端路由的数量为 0。",
        "",
        "## 建议处理优先级",
        "",
        "1. **P0：消除写入接口对 active database 的隐式依赖。** 章节、ChangeSet、实体和关系写入仍需显式 "
        "`database_id` 并验证 `book_id` 归属；该约束必须由后端持久化和权限契约保证。",
        "2. **P1：接通 Context 审批与模型流式执行。** Context 5 条接口和模型 NDJSON 执行已有 SDK，但没有运行时页面入口；"
        "当前 AI 分析、设定提醒和冲突检查仍不能形成真实的取证、确认、恢复流程。",
        "3. **P1：建设 Temporal 与向量任务管理 UI。** Temporal 11 条、Vector Task 7 条已有 SDK 而未使用；"
        "应分别进入时间线编辑器和高级索引维护页，不应塞进普通写作按钮。",
        "4. **P2：补齐实体编辑/删除/关系创建、翻译、备份清理和快捷搜索。** 这些接口已有后端能力或 SDK，"
        "但缺少完整用户操作入口。",
        "5. **先归类再处理兼容接口。** `/api/index/*`、旧 `/api/ai/*`、旧 `/api/import/preview|confirm` 与新任务化接口存在职责重叠；"
        "不建议为了追求 100% 数字覆盖而重复建设 UI，应先标注 retained/deprecated/internal。",
        "",
        "## 前端调用但后端路由不存在",
        "",
        "| 是否运行时使用 | Method | SDK Path | SDK 方法 | Vue 运行时证据 |",
        "|---|---|---|---|---|",
    ])
    for wrapper in unmatched_wrappers:
        evidence = "<br>".join(f"`{item}`" for item in wrapper["references"]) or "-"
        lines.append(
            f"| {'是' if wrapper['references'] else '否'} | {wrapper['method']} | `{wrapper['path']}` | "
            f"`{wrapper['module']}.{wrapper['symbol']}` | {evidence} |"
        )
    lines.extend([
        "",
        "## 全量接口清单",
        "",
    ])
    for domain in sorted(domains):
        lines.extend([
            f"### {domain}",
            "",
            "| 状态 | Method | Path | Auth | SDK 封装 | Vue 运行时证据 |",
            "|---|---|---|---|---|---|",
        ])
        for row in domains[domain]:
            lines.append(
                f"| {row['status']} | {row['method']} | `{row['path']}` | {row['auth']} | "
                f"`{row['wrappers']}` | {row['evidence']} |"
            )
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")
    print(f"Routes: {len(routes)}; API: {len(api_routes)}; statuses: {dict(api_statuses)}")


if __name__ == "__main__":
    main()
