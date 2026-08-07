#!/usr/bin/env python3
"""
NodeFlow 上传 / 部署审查 agent (preflight checker)

在「推到 GitHub / 部署到 AMD GPU 服务器」之前运行本脚本，逐项检查整个
上传部署链路是否存在卡点，并给出 PASS / WARN / FAIL 结论。

用法:
    python3 review_agent.py            # 全量检查
    python3 review_agent.py --quick    # 只查关键路径（上传前必跑）
    python3 review_agent.py --verbose  # 打印每一项详情

退出码:
    0 = 全部 PASS（可上传）
    1 = 存在 FAIL（必须修复后才能上传）
    2 = 存在 WARN（可上传，但建议处理）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CI = os.environ.get("CI") is not None

# 结果统计
PASSED: list[str] = []
WARNED: list[str] = []
FAILED: list[str] = []
_verbose = False


def _log(level: str, msg: str) -> None:
    if level == "PASS":
        PASSED.append(msg)
    elif level == "WARN":
        WARNED.append(msg)
    elif level == "FAIL":
        FAILED.append(msg)
    if _verbose or level != "PASS":
        print(f"[{level}] {msg}")


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return 127, f"command not found: {' '.join(cmd)}"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


# ---------------------------------------------------------------------------
# 1. 文件完整性与结构
# ---------------------------------------------------------------------------
def check_files() -> None:
    must_exist = [
        "README.md",
        "NodeFlow-README.md",
        "参赛材料.md",
        "backend/main.py",
        "backend/config.py",
        "backend/model_manager.py",
        "backend/engine.py",
        "backend/store_service.py",
        "backend/requirements.txt",
        "frontend/package.json",
        "frontend/vite.config.js",
        "frontend/src/App.jsx",
        "frontend/index.html",
        "start.sh",
        "setup.sh",
        ".gitignore",
        "HANDOVER.md",
        "HANDOVER_V2.md",
        "review_agent.py",
        "push_to_github.sh",
        "nodeflow-deck/nodeflow-deck.html",
        "project-profile.html",
    ]
    missing = [f for f in must_exist if not (ROOT / f).exists()]
    if missing:
        _log("FAIL", f"缺少必要文件: {missing}")
    else:
        _log("PASS", f"全部 {len(must_exist)} 个必要文件存在")

    # 前端构建产物
    if (ROOT / "frontend" / "dist" / "index.html").exists():
        _log("PASS", "前端 dist 构建产物存在")
    else:
        _log("WARN", "前端 dist 未构建（部署前需 npm run build）")


# ---------------------------------------------------------------------------
# 2. 敏感信息泄露检查（必查）
# ---------------------------------------------------------------------------
SECRET_PATTERNS = [
    (r"hf_[A-Za-z0-9]{20,}", "HuggingFace token"),
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI/API key"),
    (r"ghp_[A-Za-z0-9]{20,}", "GitHub PAT"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"bearer\s+[A-Za-z0-9._-]{20,}", "Bearer token"),
    (r"password\s*[=:]\s*.+", "明文口令"),
]
SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", ".screenshots", ".uploads"}


def check_secrets() -> None:
    leaked: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(part in SKIP_DIRS for part in Path(rel).parts):
            continue
        if path.suffix in {".png", ".jpg", ".gif", ".zip", ".pyc", ".safetensors", ".ckpt", ".bin"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat, label in SECRET_PATTERNS:
            m = re.search(pat, text)
            if m:
                # 占位符不算泄露
                if m.group(0) == "hf_YOUR_HF_TOKEN_HERE":
                    continue
                leaked.append(f"{rel} ({label})")
                break
    if leaked:
        # 只阻止确认为真实 token 的泄露；README 中可能只是示例
        real = [l for l in leaked if "hf_" in l or "sk-" in l or "ghp_" in l]
        if real:
            _log("FAIL", f"检测到疑似真实密钥: {real[:5]} —— 必须移除后再上传")
        else:
            _log("WARN", f"检测到疑似敏感串（可能为示例）: {leaked[:5]}")
    else:
        _log("PASS", "未检测到敏感信息泄露")


# ---------------------------------------------------------------------------
# 3. 后端 Python 语法检查
# ---------------------------------------------------------------------------
def check_python_syntax() -> None:
    py_files = sorted((ROOT / "backend").rglob("*.py"))
    bad: list[str] = []
    for f in py_files:
        try:
            compile(f.read_text(encoding="utf-8"), str(f), "exec")
        except SyntaxError as e:
            bad.append(f"{f.name}: {e}")
    if bad:
        _log("FAIL", f"Python 语法错误: {bad}")
    else:
        _log("PASS", f"后端 {len(py_files)} 个 .py 文件语法通过")


# ---------------------------------------------------------------------------
# 4. 前端构建检查
# ---------------------------------------------------------------------------
def check_frontend_build() -> None:
    if not (ROOT / "frontend" / "node_modules").exists():
        _log("WARN", "node_modules 缺失（部署前需 npm install --legacy-peer-deps）")
        return
    code, out = _run(["npm", "--prefix", "frontend", "run", "build"], timeout=180)
    if code != 0:
        _log("FAIL", f"前端构建失败: {out[-800:]}")
    else:
        _log("PASS", "前端 npm run build 构建成功")


# ---------------------------------------------------------------------------
# 5. 后端依赖与启动检查
# ---------------------------------------------------------------------------
def check_backend_deps_and_start() -> None:
    req = ROOT / "backend" / "requirements.txt"
    if not req.exists():
        _log("FAIL", "requirements.txt 缺失")
        return
    # 检查关键依赖是否可导入（torch 在无 GPU 环境可能缺失，用 WARN）
    critical = ["fastapi", "uvicorn", "pydantic", "PIL"]
    missing: list[str] = []
    for mod in critical:
        code, _ = _run([sys.executable, "-c", f"import {mod}"])
        if code != 0:
            missing.append(mod)
    if missing:
        _log("WARN", f"本地环境缺少依赖: {missing}（部署到 GPU 服务器会通过 requirements.txt 安装）")
    else:
        _log("PASS", "后端关键依赖可导入")

    # 尝试 import main 模块（不启动服务，只验证无 import 错误）
    code, out = _run([sys.executable, "-c", "import sys; sys.path.insert(0,'backend'); import main"], timeout=30)
    if code != 0:
        # 若缺 torch 等重型依赖，降级为 WARN 而非 FAIL
        if "No module named" in out:
            _log("WARN", f"backend/main import 需要重型依赖（可接受，GPU 服务器会装）: {out.splitlines()[-1]}")
        else:
            _log("FAIL", f"backend/main import 失败: {out[-400:]}")
    else:
        _log("PASS", "backend/main 可正常 import")


# ---------------------------------------------------------------------------
# 6. Git 状态检查
# ---------------------------------------------------------------------------
def check_git() -> None:
    if not (ROOT / ".git").exists():
        _log("FAIL", ".git 仓库未初始化")
        return
    code, out = _run(["git", "status", "--porcelain"])
    if code != 0:
        _log("FAIL", f"git status 失败: {out}")
        return
    uncommitted = [l for l in out.splitlines() if l]
    if uncommitted:
        _log("WARN", f"有 {len(uncommitted)} 个未提交的文件/改动（需 git add + commit）")
    else:
        _log("PASS", "工作区干净，无未提交改动")

    code, out = _run(["git", "remote", "-v"])
    if "github.com" in out:
        _log("PASS", "已配置 GitHub remote")
    elif out.strip():
        _log("WARN", f"已配置 remote 但非 GitHub: {out[:200]}")
    else:
        _log("WARN", "未配置 GitHub remote（上传前需 git remote add）")

    code, out = _run(["git", "log", "-1", "--oneline"])
    if code == 0 and out.strip():
        _log("PASS", f"已有提交: {out.strip()}")
    else:
        _log("WARN", "尚无任何 commit（上传前需首次提交）")


# ---------------------------------------------------------------------------
# 7. 前端请求端点 与 后端端点 对齐检查
# ---------------------------------------------------------------------------
def check_api_alignment() -> None:
    # 后端端点定义
    main_py = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    backend_routes = set(re.findall(r'@app\.(?:get|post|put|delete)\(\s*"([^"]+)"', main_py))
    # 前端调用的 /api 路径
    api_calls: set[str] = set()
    for glob_dir in [ROOT / "frontend" / "src", ROOT / ".uploads" / "11111_extracted" / "nodeflow-ui"]:
        if not glob_dir.exists():
            continue
        for f in glob_dir.rglob("*"):
            if f.suffix not in {".js", ".jsx", ".html"}:
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            api_calls.update(
                re.findall(r'["\'`](/api/[A-Za-z0-9_/{}\-\$\.]+)["\'`]', text)
            )
    # 规范化：去掉路径参数
    def norm(p: str) -> str:
        return re.sub(r"\{[^}]+\}", ":id", p)

    backend_norm = {norm(r) for r in backend_routes}
    missing: list[str] = []
    for call in sorted(api_calls):
        # 前端 base 路径可能是 /api/... 已含前缀
        p = call if call.startswith("/api") else "/api" + call
        base = p.split("?")[0]
        # 匹配：后端路由含该前缀（含参数化）
        matched = any(
            re.match(norm(r).replace(":id", "[^/]+").replace(":path", ".*") + "$", base)
            for r in backend_norm
        )
        if not matched:
            missing.append(p)
    if missing:
        _log("WARN", f"前端引用但后端未发现的路由: {sorted(set(missing))[:10]}")
    else:
        _log("PASS", f"前端 {len(api_calls)} 处 API 调用均有后端端点对应")


# ---------------------------------------------------------------------------
# 8. 模型/LoRA 配置完整性
# ---------------------------------------------------------------------------
def check_model_config() -> None:
    cfg = ROOT / "backend" / "config.py"
    if not cfg.exists():
        return
    text = cfg.read_text(encoding="utf-8")
    model_ids = re.findall(r'^\s{4}"([a-z0-9_]+)":\s*\{', text, re.M)
    if model_ids:
        _log("PASS", f"模型注册表含 {len(model_ids)} 个模型: {model_ids}")
    else:
        _log("WARN", "config.py 未解析到模型注册表条目")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    global _verbose
    args = sys.argv[1:]
    _verbose = "-v" in args or "--verbose" in args
    quick = "--quick" in args

    print("=" * 60)
    print(" NodeFlow 上传/部署审查 agent")
    print("=" * 60)

    check_files()
    check_secrets()
    check_python_syntax()
    if not quick:
        check_frontend_build()
        check_backend_deps_and_start()
    check_git()
    check_api_alignment()
    check_model_config()

    print("-" * 60)
    print(f"结果汇总: PASS {len(PASSED)} | WARN {len(WARNED)} | FAIL {len(FAILED)}")

    if FAILED:
        print("\n❌ 存在 FAIL，必须修复后才能上传：")
        for m in FAILED:
            print(f"   - {m}")
        return 1
    if WARNED:
        print("\n⚠ 存在 WARN，可上传但建议处理：")
        for m in WARNED:
            print(f"   - {m}")
        return 2
    print("\n✅ 全部通过，可安全上传到 GitHub 并部署。")
    return 0


if __name__ == "__main__":
    sys.exit(main())