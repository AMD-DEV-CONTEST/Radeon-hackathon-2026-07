"""OpenClaw 适配器

封装 OpenClaw 执行网关的能力：
- 工具执行（桌面/浏览器/文件/shell/定时/MCP）
- skill 管理（SKILL.md 加载/卸载）
- cron 调度
- before_tool_call Hook（Guardian 治理层嫁接点）

真实模式：调用 OpenClaw CLI/Gateway HTTP API
本地模式：用 Python 标准库实现等价功能（离线可用）
"""

from __future__ import annotations
import os
import json
import logging
import re
import shlex
import shutil
import subprocess
import tempfile
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import Adapter, AdapterResult

logger = logging.getLogger(__name__)


class OpenClawAdapter(Adapter):
    """OpenClaw 执行网关适配器

    真实模式检测：
      - openclaw 命令行可用 → 走 CLI
      - 否则 → 本地等价实现
    """

    @property
    def name(self) -> str:
        return "openclaw"

    def __init__(self, workspace: str = "", local_only: bool = False):
        self._workspace = Path(workspace or os.path.expanduser("~/.xai/workspace"))
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._local_only = local_only
        self._tools: Dict[str, callable] = {}
        self._register_local_tools()

    # ---- 生命周期 ----

    def is_available(self) -> bool:
        """检测 OpenClaw 是否已安装"""
        if self._local_only:
            return False
        return shutil.which("openclaw") is not None

    def workspace_path(self, filename: str) -> str:
        """返回 workspace 下文件的绝对路径（供 engine 做语法校验等）。"""
        return str((self._workspace / filename).resolve())

    def health_check(self) -> AdapterResult:
        if self.is_available():
            try:
                r = subprocess.run(["openclaw", "--version"], capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    return AdapterResult(ok=True, output=r.stdout.strip(), meta={"mode": "real"})
                return AdapterResult(ok=False, output=r.stderr.strip() or "unknown error", meta={"mode": "real", "exit_code": r.returncode})
            except FileNotFoundError:
                logger.info("openclaw 命令未找到，使用本地模式")
            except subprocess.TimeoutExpired:
                logger.warning("openclaw --version 超时")
            except Exception as e:
                logger.warning(f"openclaw 健康检查异常: {e}")
        tool_count = len(self._tools)
        return AdapterResult(
            ok=True,
            output=f"本地模式，{tool_count} 个工具可用",
            meta={"mode": "local", "tools": tool_count, "degraded": True},
        )

    # ---- 工具注册（本地模式） ----

    def _register_local_tools(self):
        self._tools = {
            "exec": self._exec_command,
            "file_read": self._file_read,
            "file_write": self._file_write,
            "file_delete": self._file_delete,
            "browser_open": self._browser_open,
            "list_dir": self._list_dir,
        }

    def _safe_path(self, filename: str) -> Path:
        p = (self._workspace / filename).resolve()
        if not str(p).startswith(str(self._workspace.resolve())):
            raise ValueError(f"路径越界: {filename}")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _resolve_scan_target(self, filepath: str) -> Path:
        """为只读安全扫描解析文件：在多个候选位置查找（只读，不越界约束到工作区）。

        依次尝试：原样路径 → 工作区 → 当前目录 → 当前目录向上若干层。
        找不到时抛出含已搜索路径的清晰错误，而非裸 FileNotFoundError。
        """
        candidates: List[Path] = [Path(filepath)]
        candidates.append(self._workspace / filepath)
        try:
            candidates.append(Path.cwd() / filepath)
        except Exception:
            pass
        cwd = Path.cwd()
        for parent in [cwd, *cwd.parents[:3]]:
            candidates.append(parent / filepath)
        seen = set()
        for c in candidates:
            try:
                rp = c.resolve()
                if str(rp) in seen:
                    continue
                seen.add(str(rp))
                if rp.is_file():
                    return rp
            except Exception:
                continue
        raise FileNotFoundError(
            f"找不到文件: {filepath}\n已搜索: " + "; ".join(str(c) for c in candidates[:4])
        )

    def _exec_command(self, action: dict) -> AdapterResult:
        cmd = action.get("command", "")
        timeout = action.get("timeout", 30)
        try:
            # 使用 shlex.split 安全解析命令，避免 shell=True 注入
            args = shlex.split(cmd) if isinstance(cmd, str) else cmd
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=str(self._workspace))
            return AdapterResult(
                ok=r.returncode == 0,
                output=r.stdout[:4000] or r.stderr[:4000],
                meta={"exit_code": r.returncode},
            )
        except subprocess.TimeoutExpired:
            return AdapterResult(ok=False, error=f"命令超时（{timeout}s）: {str(cmd)[:100]}")
        except FileNotFoundError:
            return AdapterResult(ok=False, error=f"命令不存在: {str(cmd)[:100]}")
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def _file_read(self, action: dict) -> AdapterResult:
        path = self._safe_path(action.get("path", ""))
        try:
            content = path.read_text(encoding="utf-8")
            return AdapterResult(ok=True, output=content[:8000], meta={"path": str(path), "size": len(content)})
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def _file_write(self, action: dict) -> AdapterResult:
        path = self._safe_path(action.get("path", ""))
        content = action.get("content", "")
        try:
            path.write_text(content, encoding="utf-8")
            return AdapterResult(ok=True, output=f"已写入 {path} ({len(content)} 字节)", meta={"path": str(path)})
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def _file_delete(self, action: dict) -> AdapterResult:
        path = self._safe_path(action.get("path", ""))
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            return AdapterResult(ok=True, output=f"已删除 {path}")
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def _browser_open(self, action: dict) -> AdapterResult:
        url = action.get("url", "")
        try:
            webbrowser.open(url)
            return AdapterResult(ok=True, output=f"已打开 {url}")
        except Exception as e:
            return AdapterResult(ok=False, error=f"无法打开浏览器: {e}。请手动访问: {url}")

    def _list_dir(self, action: dict) -> AdapterResult:
        path = self._safe_path(action.get("path", "."))
        try:
            items = []
            for p in sorted(path.iterdir()):
                t = "📁" if p.is_dir() else "📄"
                items.append(f"{t} {p.name}")
            return AdapterResult(ok=True, output="\n".join(items) or "(空目录)")
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    # ---- 执行入口（引擎调这里） ----

    def execute(self, action: Dict[str, Any]) -> AdapterResult:
        """执行一个动作。引擎传入 {"tool": "...", ...参数...}"""
        tool = action.get("tool", "")

        # 已知本地工具（exec/file_write/file_read/list_dir/browser_open/file_delete）
        # 始终用本地实现：不依赖 OpenClaw CLI 的确切参数格式，可靠性最高，
        # 避免「功能没反应 / 空错误」。MCP/skills/channels/cron 等仍走真实 CLI。
        if tool in self._tools:
            return self._tools[tool](action)

        # 其余走 OpenClaw CLI 真实模式
        if self.is_available() and not self._local_only:
            return self._execute_real(action)

        return AdapterResult(ok=False, error=f"未知工具: {tool}")

    def _execute_real(self, action: dict) -> AdapterResult:
        tool = action.get("tool", "")
        args = action.get("args", {})
        cmd_parts = ["openclaw", tool]
        for k, v in args.items():
            if v:
                cmd_parts.append(f"--{k}={v}")
        try:
            r = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=60, cwd=str(self._workspace))
            return AdapterResult(
                ok=r.returncode == 0,
                output=r.stdout[:4000] or r.stderr[:4000],
                error="" if r.returncode == 0 else (r.stderr[:500] or f"openclaw {tool} 退出码 {r.returncode}"),
                meta={"mode": "openclaw", "exit_code": r.returncode},
            )
        except Exception as e:
            return AdapterResult(ok=False, error=str(e), meta={"mode": "openclaw"})

    # ---- Skill 管理 ----

    def load_skill(self, skill_name: str) -> AdapterResult:
        """加载一个 SKILL.md 技能"""
        skill_dir = self._workspace / "skills" / skill_name
        if skill_dir.exists():
            return AdapterResult(ok=True, output=f"技能已加载: {skill_name}", meta={"path": str(skill_dir)})
        return AdapterResult(ok=False, error=f"技能不存在: {skill_name}")

    def list_skills(self) -> AdapterResult:
        skills_dir = self._workspace / "skills"
        if not skills_dir.exists():
            return AdapterResult(ok=True, output="(无已加载技能)")
        items = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        return AdapterResult(ok=True, output="\n".join(items) if items else "(无已加载技能)", meta={"count": len(items)})

    # ---- Cron 调度 ----

    def schedule_cron(self, name: str, schedule: str, command: str) -> AdapterResult:
        """注册一个定时任务（原子写入）"""
        cron_dir = self._workspace / "cron"
        cron_dir.mkdir(parents=True, exist_ok=True)
        entry = {"name": name, "schedule": schedule, "command": command}
        entry_json = json.dumps(entry, ensure_ascii=False, indent=2)
        target = cron_dir / f"{name}.json"
        fd, tmp = tempfile.mkstemp(dir=str(cron_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(entry_json)
            os.replace(tmp, str(target))
            return AdapterResult(ok=True, output=f"已注册定时任务: {name} ({schedule})", meta=entry)
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def list_cron(self) -> AdapterResult:
        cron_dir = self._workspace / "cron"
        if not cron_dir.exists():
            return AdapterResult(ok=True, output="(无定时任务)")
        items = []
        for f in cron_dir.glob("*.json"):
            entry = json.loads(f.read_text())
            items.append(f"  {entry['name']}: {entry['schedule']} → {entry['command']}")
        return AdapterResult(ok=True, output="\n".join(items) if items else "(无定时任务)")

    # ---- MCP 桥接（OpenClaw 原生 105 文件 MCP 支持） ----

    def mcp_list_servers(self) -> AdapterResult:
        """列出已连接的 MCP 服务器"""
        if self.is_available():
            try:
                r = subprocess.run(["openclaw", "mcp", "list"], capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    return AdapterResult(ok=True, output=r.stdout[:4000], meta={"mode": "openclaw"})
            except Exception:
                pass
        # fallback: 检查本地 MCP 配置
        mcp_config = Path.home() / ".openclaw" / "mcp.json"
        if mcp_config.exists():
            try:
                config = json.loads(mcp_config.read_text())
                servers = list(config.get("mcpServers", {}).keys()) if isinstance(config, dict) else []
                return AdapterResult(
                    ok=True,
                    output="\n".join(f"  {s}" for s in servers) if servers else "(无 MCP 连接)",
                    meta={"servers": servers, "mode": "local"},
                )
            except Exception:
                pass
        return AdapterResult(ok=True, output="(无 MCP 连接)", meta={"servers": []})

    def mcp_add(self, server_name: str, config: dict = None) -> AdapterResult:
        """添加一个 MCP 服务器（真实命令：openclaw mcp add <name>）"""
        if self.is_available():
            try:
                cmd = ["openclaw", "mcp", "add", server_name]
                if config:
                    cmd.extend([json.dumps(config)])
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if r.returncode == 0:
                    return AdapterResult(ok=True, output=f"MCP 已添加: {server_name}", meta={"mode": "openclaw"})
                return AdapterResult(
                    ok=False,
                    error=f"添加失败，可能需要完整配置。示例: openclaw mcp add {server_name} '{{\"command\":\"uvx\",\"args\":[\"context7-mcp\"]}}'\n原错误: {r.stderr[:300]}",
                    meta={"mode": "openclaw"},
                )
            except Exception as e:
                return AdapterResult(ok=False, error=str(e))
        return AdapterResult(ok=False, error="OpenClaw 未安装或不可用")

    def mcp_connect(self, server_name: str, config: dict = None) -> AdapterResult:
        """兼容别名：同 mcp_add"""
        return self.mcp_add(server_name, config)

    def mcp_list_tools(self, server_name: str = "") -> AdapterResult:
        """列出 MCP 服务器提供的工具"""
        if self.is_available():
            try:
                cmd = ["openclaw", "mcp", "tools"]
                if server_name:
                    cmd.extend(["--server", server_name])
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    return AdapterResult(ok=True, output=r.stdout[:4000], meta={"mode": "openclaw"})
            except Exception:
                pass
        return AdapterResult(ok=False, error="无法获取 MCP 工具列表")

    # ---- Skill 桥接（OpenClaw 原生 52 个 SKILL.md 技能） ----

    def list_real_skills(self) -> AdapterResult:
        """列出 OpenClaw 真实技能（~/.openclaw/skills/ 下的 SKILL.md）"""
        skills_dir = Path.home() / ".openclaw" / "skills"
        if not skills_dir.exists():
            return AdapterResult(ok=True, output="(OpenClaw skills 目录不存在)", meta={"count": 0})

        skills = []
        for d in sorted(skills_dir.iterdir()):
            if d.is_dir():
                skill_md = d / "SKILL.md"
                if skill_md.exists():
                    skills.append({"name": d.name, "path": str(skill_md)})
        return AdapterResult(
            ok=True,
            output="\n".join(f"  {s['name']}" for s in skills) if skills else "(无技能)",
            meta={"skills": skills, "count": len(skills), "source": str(skills_dir)},
        )

    def load_real_skill(self, skill_name: str) -> AdapterResult:
        """读取一个真实 OpenClaw SKILL.md 技能"""
        skill_md = Path.home() / ".openclaw" / "skills" / skill_name / "SKILL.md"
        if not skill_md.exists():
            return AdapterResult(ok=False, error=f"技能不存在: {skill_name} (路径: {skill_md})")
        try:
            content = skill_md.read_text(encoding="utf-8")
            # 提取 frontmatter（如果有）
            frontmatter = {}
            body = content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].strip().split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            frontmatter[k.strip()] = v.strip()
                    body = parts[2].strip()
            return AdapterResult(
                ok=True,
                output=body[:4000],
                meta={"name": skill_name, "frontmatter": frontmatter, "path": str(skill_md)},
            )
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def register_skill(self, name: str, skill_md_content: str, description: str = "") -> AdapterResult:
        """注册一个新技能到 OpenClaw"""
        skill_dir = Path.home() / ".openclaw" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
        return AdapterResult(ok=True, output=f"技能已注册: {name}", meta={"path": str(skill_dir)})

    # ---- Grok Build 完整工具链 ----

    def git_operation(self, action: dict) -> AdapterResult:
        """Git 操作：status/log/commit/diff/branch"""
        op = action.get("op", "status")
        git_dir = action.get("repo_path", str(self._workspace))
        try:
            cmd = ["git", "-C", git_dir, op]
            extra_args = action.get("extra_args", [])
            if isinstance(extra_args, str):
                extra_args = extra_args.split()
            cmd.extend(extra_args)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return AdapterResult(
                ok=r.returncode == 0,
                output=r.stdout[:3000] or r.stderr[:1000],
                meta={"op": op, "exit_code": r.returncode},
            )
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def code_refactor(self, action: dict) -> AdapterResult:
        """代码重构：读取文件 → Hermes 推理 → 写回"""
        filepath = action.get("file", "")
        instruction = action.get("instruction", "优化代码结构")
        try:
            # 读取原文件（本地模式）
            read_result = self._file_read({"path": filepath})
            if not read_result.ok:
                return read_result
            # 构造重构指令（实际重构由引擎层的 Hermes 完成）
            return AdapterResult(
                ok=True,
                output=read_result.output,
                meta={"action": "refactor_prepare", "file": filepath, "instruction": instruction},
            )
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def vulnerability_scan(self, action: dict) -> AdapterResult:
        """安全漏洞扫描：检查 Python 代码的常见安全问题"""
        filepath = action.get("file", "")
        try:
            p = self._resolve_scan_target(filepath)
            content = p.read_text(encoding="utf-8")
            findings = []
            # 简单启发式扫描
            dangerous = [
                (r"os\.system\(", "P1: 使用 os.system() 存在命令注入风险，建议用 subprocess.run()"),
                (r"subprocess\.run\(.*shell=True", "P1: shell=True 存在命令注入风险"),
                (r"eval\(", "P0: eval() 可执行任意代码，禁止使用"),
                (r"exec\(", "P0: exec() 可执行任意代码，禁止使用"),
                ("pickle.load", "P1: pickle 反序列化可能导致代码执行"),
                ("password", "P2: 代码中含 password 关键词，检查是否硬编码凭证"),
                ("api_key", "P2: 代码中含 api_key 关键词，检查是否硬编码凭证"),
                ("secret", "P2: 代码中含 secret 关键词，检查是否硬编码凭证"),
            ]
            for pattern, warning in dangerous:
                if re.search(pattern, content, re.IGNORECASE):
                    findings.append(f"  [{warning.split(':')[0]}] {warning}")
            if findings:
                return AdapterResult(
                    ok=True,
                    output=f"🔍 {filepath} 安全扫描发现 {len(findings)} 个问题:\n" + "\n".join(findings),
                    meta={"file": filepath, "findings": len(findings)},
                )
            return AdapterResult(ok=True, output=f"✅ {filepath} 未发现已知安全问题")
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def repo_parse(self, action: dict) -> AdapterResult:
        """仓库解析：列出项目结构和文件统计"""
        repo_path = action.get("path", str(self._workspace))
        try:
            p = Path(repo_path)
            if not p.exists():
                return AdapterResult(ok=False, error=f"路径不存在: {repo_path}")
            files = []
            total_lines = 0
            for f in sorted(p.rglob("*.py"))[:50]:
                if "__pycache__" in str(f) or "node_modules" in str(f) or ".git" in str(f):
                    continue
                try:
                    lines = len(f.read_text(encoding="utf-8", errors="ignore").splitlines())
                    rel = f.relative_to(p)
                    files.append(f"  {rel} ({lines} 行)")
                    total_lines += lines
                except Exception:
                    pass
            return AdapterResult(
                ok=True,
                output=f"📁 {repo_path}\n共 {len(files)} 个 Python 文件, {total_lines} 行\n" + "\n".join(files[:30]),
                meta={"files": len(files), "total_lines": total_lines},
            )
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    # ---- 渠道管理 ----

    def list_channels(self) -> AdapterResult:
        """列出 OpenClaw 支持的消息渠道（真实命令：openclaw channels list）"""
        if self.is_available():
            try:
                r = subprocess.run(["openclaw", "channels", "list"], capture_output=True, text=True, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    return AdapterResult(ok=True, output=r.stdout[:3000], meta={"mode": "openclaw"})
            except Exception:
                pass
        # fallback：可支持的渠道目录（标注「支持」而非「已连接」，避免假数据）
        channels = ["telegram", "discord", "slack", "whatsapp", "signal", "imessage", "webchat", "wechat", "line", "zalo", "matrix", "msteams", "googlechat"]
        return AdapterResult(ok=True, output="（以下为 OpenClaw 支持的渠道目录，需配置后连接）\n" + "\n".join(f"  {c}" for c in channels), meta={"channels": channels, "configured": False})

    def channel_status(self, channel: str) -> AdapterResult:
        """检查某个渠道的连接状态（真实命令：openclaw channels status）"""
        if self.is_available():
            try:
                r = subprocess.run(["openclaw", "channels", "status", channel], capture_output=True, text=True, timeout=10)
                return AdapterResult(ok=r.returncode == 0, output=r.stdout[:1000] or r.stderr[:500], meta={"mode": "openclaw"})
            except Exception as e:
                return AdapterResult(ok=False, error=str(e))
        return AdapterResult(ok=False, error=f"OpenClaw 未安装，无法检查渠道 {channel} 状态")
