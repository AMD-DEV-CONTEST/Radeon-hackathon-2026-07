"""Regenerate project_context.md from the live repository.

This script is intentionally read-only except for project_context.md. It is used
as the periodic sync point for GPT/Codex project context, so it should discover
current modules instead of relying on a hand-maintained V1.24-era list.
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "project_context.md"

EXCLUDED_DIRS = {
    ".agents",
    ".cache",
    ".claude",
    ".codex",
    ".codex-remote-attachments",
    ".git",
    ".pnpm-store",
    ".pytest_cache",
    ".venv",
    ".vite",
    ".vite-temp",
    "__pycache__",
    "app_data",
    "backup",
    "backups",
    "build",
    "dist",
    "frontend/node_modules",
    "frontend/dist",
    "frontend/.vite-check-dist",
    "frontend/src-tauri/backend/generated",
    "local_agent_runs",
    "logs",
    "node_modules",
    "restore_test",
    "venv",
    "备份内容",
}

SOURCE_AREAS = [
    "main.py",
    "api",
    "routes",
    "services",
    "app",
    "extractors",
    "alembic/versions",
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_excluded(path: Path) -> bool:
    try:
        relative = rel(path)
    except ValueError:
        return True
    parts = relative.split("/")
    for i in range(len(parts)):
        prefix = "/".join(parts[: i + 1])
        if prefix in EXCLUDED_DIRS or parts[i] in EXCLUDED_DIRS:
            return True
    return False


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def iter_files(paths: list[str], suffixes: tuple[str, ...] | None = None) -> list[Path]:
    found: list[Path] = []
    for item in paths:
        path = ROOT / item
        if not path.exists() or is_excluded(path):
            continue
        if path.is_file():
            if suffixes is None or path.name.endswith(suffixes):
                found.append(path)
            continue
        for child in path.rglob("*"):
            if child.is_file() and not is_excluded(child):
                if suffixes is None or child.name.endswith(suffixes):
                    found.append(child)
    return sorted(found, key=lambda p: rel(p).lower())


def list_dir(path: str, suffix: str | None = None, recursive: bool = False) -> list[str]:
    root = ROOT / path
    if not root.exists():
        return []
    pattern = "**/*" if recursive else "*"
    entries = []
    for item in root.glob(pattern):
        if is_excluded(item):
            continue
        if suffix and not item.name.endswith(suffix):
            continue
        if item.is_file():
            entries.append(rel(item))
    return sorted(entries, key=str.lower)


def first_existing(paths: list[str]) -> Path | None:
    for item in paths:
        path = ROOT / item
        if path.exists():
            return path
    return None


def detect_version() -> str:
    version_py = ROOT / "app" / "version.py"
    if version_py.exists():
        match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', read_text(version_py))
        if match:
            return "v" + match.group(1).lstrip("vV")
    main_py = ROOT / "main.py"
    if main_py.exists():
        match = re.search(r"v\d+\.\d+\.\d+", read_text(main_py), re.IGNORECASE)
        if match:
            return match.group(0)
    package_json = ROOT / "frontend" / "package.json"
    if package_json.exists():
        try:
            return "v" + json.loads(read_text(package_json)).get("version", "unknown")
        except json.JSONDecodeError:
            pass
    return "unknown"


def parse_requirements(path: str) -> list[str]:
    req_path = ROOT / path
    if not req_path.exists():
        return []
    deps = []
    for line in read_text(req_path).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            deps.append(stripped)
    return deps


def parse_package_json() -> dict:
    path = ROOT / "frontend" / "package.json"
    if not path.exists():
        return {}
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError:
        return {}


def parse_cargo_package() -> dict:
    path = ROOT / "frontend" / "src-tauri" / "Cargo.toml"
    if not path.exists():
        return {}
    data = {}
    in_package = False
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped == "[package]":
            in_package = True
            continue
        if stripped.startswith("[") and stripped != "[package]":
            in_package = False
        if in_package and "=" in stripped:
            key, value = stripped.split("=", 1)
            data[key.strip()] = value.strip().strip('"')
    return data


def parse_tables_and_indexes(py_files: list[Path]) -> tuple[set[str], set[str]]:
    tables: set[str] = set()
    indexes: set[str] = set()
    for path in py_files:
        code = read_text(path)
        tables.update(re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w]*)", code, re.I))
        indexes.update(re.findall(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w]*)", code, re.I))
    return tables, {idx for idx in indexes if len(idx) > 2}


def literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def parse_router_prefix(tree: ast.AST) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "APIRouter":
            for kw in node.keywords:
                if kw.arg == "prefix":
                    return literal_string(kw.value) or ""
    return ""


def parse_routes(py_files: list[Path]) -> list[tuple[str, str, str]]:
    routes: list[tuple[str, str, str]] = []
    methods = {"get", "post", "put", "patch", "delete", "options", "head"}
    for path in py_files:
        code = read_text(path)
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        prefix = parse_router_prefix(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr not in methods:
                    continue
                owner = getattr(func.value, "id", "")
                if owner not in {"app", "router"}:
                    continue
                if not decorator.args:
                    continue
                route_path = literal_string(decorator.args[0])
                if route_path is None:
                    continue
                if owner == "router" and prefix and not route_path.startswith(prefix):
                    route_path = prefix.rstrip("/") if route_path == "" else prefix.rstrip("/") + "/" + route_path.lstrip("/")
                routes.append((func.attr.upper(), route_path or "/", rel(path)))
    return sorted(set(routes), key=lambda item: (item[1], item[0], item[2]))


def parse_models(py_files: list[Path]) -> list[tuple[str, str, str]]:
    models: list[tuple[str, str, str]] = []
    for path in py_files:
        code = read_text(path)
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)
            if any(base in {"BaseModel", "Enum", "str", "Protocol"} for base in bases):
                models.append((node.name, ", ".join(bases) or "-", rel(path)))
    return sorted(set(models), key=lambda item: (item[2], item[0]))


def module_tree(path: str) -> list[str]:
    files = list_dir(path, ".py", recursive=True)
    return [item[:-3] for item in files if not item.endswith("/__init__.py")]


def markdown_files() -> list[str]:
    docs = []
    for item in ["CODEX_PROJECT_CONTEXT.md", "AGENT_WORKSPACE_INDEX.md", "SECURITY_AUDIT.md", "DECISION_LOG.md", "README.md", "README_CN.md"]:
        if (ROOT / item).exists():
            docs.append(item)
    docs.extend(list_dir("markdown文件存放区", ".md", recursive=False))
    return sorted(set(docs), key=str.lower)


def frontend_summary() -> dict:
    package = parse_package_json()
    src_files = list_dir("frontend/src", recursive=True)
    return {
        "package": package,
        "views": [p for p in src_files if "/views/" in p and p.endswith(".vue")],
        "components": [p for p in src_files if "/components/" in p and p.endswith(".vue")],
        "stores": [p for p in src_files if "/stores/" in p],
        "api": [p for p in src_files if "/api/" in p],
        "tests": list_dir("frontend/tests", recursive=True),
        "tauri": parse_cargo_package(),
        "tauri_files": list_dir("frontend/src-tauri/src", recursive=True),
    }


def write_section(lines: list[str], title: str) -> None:
    lines.append("")
    lines.append(title)
    lines.append("")


def bullet_list(lines: list[str], items: list[str], empty: str = "- none detected") -> None:
    if not items:
        lines.append(empty)
        return
    for item in items:
        lines.append(f"- `{item}`")


def plain_list(lines: list[str], items: list[str], empty: str = "- none detected") -> None:
    if not items:
        lines.append(empty)
        return
    for item in items:
        lines.append(f"- {item}")


def main() -> None:
    version = detect_version()
    py_files = iter_files(SOURCE_AREAS, (".py",))
    route_files = iter_files(["main.py", "api", "routes"], (".py",))
    tables, indexes = parse_tables_and_indexes(py_files)
    routes = parse_routes(route_files)
    models = parse_models(py_files)
    frontend = frontend_summary()

    lines: list[str] = []
    lines.append("# Project Context")
    lines.append("")
    lines.append("> Auto-generated by `scripts/generate_context.py` from the live repository.")
    lines.append("")

    write_section(lines, "## 1. Project Summary")
    lines.append(f"- Version detected: `{version}`")
    lines.append("- Product shape: FastAPI + SQLite backend with a Vue/Tauri desktop frontend.")
    lines.append("- Current scope: local-first worldview database, creative workspace, model routing/runtime, import pipeline, media/RAG, translation, deployment reservations, security tests.")
    lines.append("- Runtime data and credentials are intentionally excluded from this context file.")

    write_section(lines, "## 2. Repository Map")
    repo_map = [
        ("Backend app", "main.py"),
        ("API routers", "api/"),
        ("Web routes", "routes/"),
        ("Services", "services/"),
        ("Shared config/models/auth dependencies", "app/"),
        ("SQLite migrations", "alembic/versions/"),
        ("Vue/Tauri frontend", "frontend/"),
        ("Templates and static web assets", "templates/, static/"),
        ("Deployment and release helpers", "deploy/, scripts/"),
        ("Tests", "tests/, frontend/tests/"),
        ("Long-form planning and result docs", "markdown文件存放区/"),
    ]
    lines.append("| Area | Path |")
    lines.append("|---|---|")
    for name, path in repo_map:
        lines.append(f"| {name} | `{path}` |")

    write_section(lines, "## 3. Backend Modules")
    for heading, path in [
        ("### 3.1 API Routers", "api"),
        ("### 3.2 Service Modules", "services"),
        ("### 3.3 App Modules", "app"),
        ("### 3.4 Extractors", "extractors"),
        ("### 3.5 Migrations", "alembic/versions"),
    ]:
        lines.append(heading)
        bullet_list(lines, module_tree(path))
        lines.append("")

    write_section(lines, "## 4. API Routes")
    lines.append(f"Detected routes: `{len(routes)}`")
    lines.append("")
    lines.append("| Method | Path | Source |")
    lines.append("|---|---|---|")
    for method, path, source in routes:
        lines.append(f"| {method} | `{path}` | `{source}` |")

    write_section(lines, "## 5. Database Schema Signals")
    lines.append("Tables and indexes are discovered from SQL literals in Python source and migrations; verify live DB state separately.")
    lines.append("")
    lines.append("### 5.1 Tables")
    bullet_list(lines, sorted(tables))
    lines.append("")
    lines.append("### 5.2 Indexes")
    bullet_list(lines, sorted(indexes))

    write_section(lines, "## 6. Contracts And Models")
    lines.append(f"Detected Pydantic/Enum/protocol-like classes: `{len(models)}`")
    lines.append("")
    lines.append("| Name | Base | Source |")
    lines.append("|---|---|---|")
    for name, bases, source in models:
        lines.append(f"| `{name}` | `{bases}` | `{source}` |")

    write_section(lines, "## 7. Frontend And Desktop")
    package = frontend["package"]
    lines.append(f"- Frontend package: `{package.get('name', 'unknown')}`")
    lines.append(f"- Frontend version: `{package.get('version', 'unknown')}`")
    lines.append("- Frontend stack: Vue 3, Pinia, Vue Router, Vue I18n, Vite, Tauri 2.")
    if frontend["tauri"]:
        lines.append(f"- Tauri package: `{frontend['tauri'].get('name', 'unknown')}` `{frontend['tauri'].get('version', 'unknown')}`")
    lines.append("")
    for heading, key in [
        ("### 7.1 Views", "views"),
        ("### 7.2 Components", "components"),
        ("### 7.3 Stores", "stores"),
        ("### 7.4 Frontend API/SDK Files", "api"),
        ("### 7.5 Frontend Tests", "tests"),
        ("### 7.6 Tauri Runtime Source", "tauri_files"),
    ]:
        lines.append(heading)
        bullet_list(lines, frontend[key])
        lines.append("")

    write_section(lines, "## 8. Scripts And Automation")
    bullet_list(lines, list_dir("scripts", recursive=False))

    write_section(lines, "## 9. Tests")
    test_files = list_dir("tests", ".py", recursive=True)
    lines.append(f"Detected Python test files: `{len(test_files)}`")
    bullet_list(lines, test_files)

    write_section(lines, "## 10. Dependencies")
    lines.append("### 10.1 Python Runtime")
    bullet_list(lines, parse_requirements("requirements.txt"))
    lines.append("")
    lines.append("### 10.2 Python Test/Build")
    bullet_list(lines, parse_requirements("requirements-test.txt") + parse_requirements("requirements-desktop-build.txt"))
    lines.append("")
    lines.append("### 10.3 Frontend")
    deps = package.get("dependencies", {})
    dev_deps = package.get("devDependencies", {})
    bullet_list(lines, [f"{name} {version}" for name, version in sorted(deps.items())])
    lines.append("")
    lines.append("### 10.4 Frontend Dev")
    bullet_list(lines, [f"{name} {version}" for name, version in sorted(dev_deps.items())])

    write_section(lines, "## 11. Documentation Index")
    bullet_list(lines, markdown_files())

    write_section(lines, "## 12. Operational Boundaries")
    boundaries = [
        "Do not treat roadmap text as truth without checking live code, routes, schemas, and tests.",
        "Do not commit or copy `.api_keys.json`, `config.local.yaml`, `.env*`, `app_data/`, `logs/`, local databases, dependency directories, or generated sidecar binaries into source snapshots.",
        "`config.example.yaml` is the tracked template; `config.local.yaml` is private runtime config.",
        "Desktop production must use a dynamic loopback backend endpoint, not a fixed public service contract.",
        "Public/server modes remain reserved or fail-closed unless separately implemented and security-tested.",
        "Use `scripts/backup_project.ps1 -DryRun` before milestone source snapshots.",
    ]
    plain_list(lines, boundaries)

    lines.append("")
    lines.append("---")
    lines.append("Generated by `scripts/generate_context.py`.")
    lines.append("Regenerate with: `python scripts/generate_context.py`.")

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK - {len(lines)} lines, {version}, {len(routes)} routes, {len(py_files)} python files scanned")


if __name__ == "__main__":
    main()
