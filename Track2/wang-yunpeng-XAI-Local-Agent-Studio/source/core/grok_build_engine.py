"""XAI 代码引擎抽象层（参考 Grok Build 的垂直代码子引擎）。

设计要点（模型/工具无关）：
- 提供一组只读 / 安全 dry-run 的代码工具抽象接口：仓库解析、批量重构、Git 与
  终端深度集成、漏洞启发式扫描、单元测试自动生成。
- 架构与路由是"真"的：所有方法都通过抽象接口定义，由 `CodeEngine` 依赖注入
  具体实现；测试时注入确定性 `Stub*` 实现，无需联网即可验证整条管线。
- 绝不在用户的真实仓库上做破坏性操作：重构等非 dry-run 动作只在引擎自行创建的
  临时目录中进行（os / pathlib 安全桩）。

本模块是 XAI 平台中"代码执行/构建"能力的落点，对应 Rust crate xai-grok-build。
"""

from __future__ import annotations

import os
import pathlib
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CodeResult:
    """统一工具返回结构。"""

    ok: bool
    tool: str
    data: dict
    msg: str


class RepoParser(ABC):
    """离线大代码仓库解析（只读）。"""

    @abstractmethod
    def scan(self, root: str) -> dict:
        """遍历 root，返回文件数、各语言计数、目录树样例。"""
        raise NotImplementedError


class RefactorTool(ABC):
    """批量重构（默认 dry-run，安全）。"""

    @abstractmethod
    def refactor(
        self, root: str, pattern: str, replacement: str, dry_run: bool = True
    ) -> CodeResult:
        """在 .py/.txt/.md 中统计 pattern 命中；dry_run 不修改，否则在临时目录替换。"""
        raise NotImplementedError


class GitTool(ABC):
    """Git 深度集成（dry-run 桩）。"""

    @abstractmethod
    def status(self, repo: str) -> CodeResult:
        """返回仓库状态（桩）。"""
        raise NotImplementedError

    @abstractmethod
    def commit(self, repo: str, msg: str, dry_run: bool = True) -> CodeResult:
        """返回计划中的 commit 命令（dry_run 不执行）。"""
        raise NotImplementedError


class TerminalTool(ABC):
    """终端深度集成（dry-run 桩）。"""

    @abstractmethod
    def run(
        self, cmd: str, cwd: str | None = None, dry_run: bool = True
    ) -> CodeResult:
        """返回计划中的命令（dry_run 不执行）。"""
        raise NotImplementedError


class VulnScanner(ABC):
    """漏洞启发式扫描（只读）。"""

    @abstractmethod
    def scan(self, root: str) -> CodeResult:
        """扫描危险调用（eval/exec/os.system/pickle.load），返回 findings。"""
        raise NotImplementedError


class TestGenTool(ABC):
    """单元测试自动生成（桩）。"""

    @abstractmethod
    def gen(self, source: str) -> CodeResult:
        """返回针对 source 的测试计划。"""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 确定性 Stub 实现
# ---------------------------------------------------------------------------

_SAFE_EXTS = {".py", ".txt", ".md"}
_DANGER_PATTERNS = ("eval(", "exec(", "os.system(", "pickle.load(")


class StubRepoParser(RepoParser):
    """只读仓库解析桩：基于 os.walk 计数。"""

    def scan(self, root: str) -> dict:
        files = 0
        languages: dict[str, int] = {}
        tree_sample: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                files += 1
                ext = os.path.splitext(name)[1].lower() or "(no-ext)"
                languages[ext] = languages.get(ext, 0) + 1
                if len(tree_sample) < 50:
                    rel = os.path.relpath(os.path.join(dirpath, name), root)
                    tree_sample.append(rel)
        return {"files": files, "languages": languages, "tree_sample": tree_sample}


class StubRefactorTool(RefactorTool):
    """重构桩：统计命中，dry_run 不修改；非 dry_run 仅作用于临时目录。"""

    def refactor(
        self, root: str, pattern: str, replacement: str, dry_run: bool = True
    ) -> CodeResult:
        matches = 0
        targeted_files: list[str] = []
        for path in pathlib.Path(root).rglob("*"):
            if path.is_file() and path.suffix.lower() in _SAFE_EXTS:
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                count = text.count(pattern)
                if count > 0:
                    matches += count
                    targeted_files.append(str(path))

        if dry_run:
            return CodeResult(
                ok=True,
                tool="refactor",
                data={
                    "matches": matches,
                    "files": len(targeted_files),
                    "modified": False,
                },
                msg=f"dry-run: {matches} 处命中，未修改文件",
            )

        # 安全替换：仅写入引擎创建的临时目录，绝不触碰用户仓库。
        tmp = tempfile.mkdtemp(prefix="grok_refactor_")
        for src in targeted_files:
            rel = os.path.relpath(src, root)
            dst = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            original = pathlib.Path(src).read_text(encoding="utf-8", errors="ignore")
            pathlib.Path(dst).write_text(
                original.replace(pattern, replacement), encoding="utf-8"
            )
        return CodeResult(
            ok=True,
            tool="refactor",
            data={
                "matches": matches,
                "files": len(targeted_files),
                "modified": True,
                "temp_dir": tmp,
            },
            msg=f"已在临时目录 {tmp} 完成 {matches} 处替换",
        )


class StubGitTool(GitTool):
    """Git 集成桩：只返回计划中的命令。"""

    def status(self, repo: str) -> CodeResult:
        return CodeResult(
            ok=True,
            tool="git_status",
            data={"planned_cmd": f"git -C {repo} status"},
            msg="dry-run: planned git status",
        )

    def commit(self, repo: str, msg: str, dry_run: bool = True) -> CodeResult:
        return CodeResult(
            ok=True,
            tool="git_commit",
            data={"planned_cmd": f"git -C {repo} commit -m {msg!r}"},
            msg="dry-run: planned git commit" if dry_run else "executed git commit",
        )


class StubTerminalTool(TerminalTool):
    """终端集成桩：只返回计划中的命令。"""

    def run(
        self, cmd: str, cwd: str | None = None, dry_run: bool = True
    ) -> CodeResult:
        return CodeResult(
            ok=True,
            tool="terminal",
            data={"planned_cmd": cmd, "cwd": cwd},
            msg="dry-run: planned command" if dry_run else "executed command",
        )


class StubVulnScanner(VulnScanner):
    """漏洞扫描桩：只读启发式。"""

    def scan(self, root: str) -> CodeResult:
        findings: list[dict] = []
        for path in pathlib.Path(root).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _SAFE_EXTS:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for ln, line in enumerate(lines, start=1):
                for pat in _DANGER_PATTERNS:
                    if pat in line:
                        findings.append(
                            {
                                "file": str(path),
                                "line": ln,
                                "pattern": pat,
                                "snippet": line.strip(),
                            }
                        )
        return CodeResult(
            ok=True,
            tool="vuln_scan",
            data={"findings": findings, "count": len(findings)},
            msg=f"发现 {len(findings)} 处疑似危险调用",
        )


class StubTestGenTool(TestGenTool):
    """测试生成桩：返回确定性的测试用例计划。"""

    def gen(self, source: str) -> CodeResult:
        return CodeResult(
            ok=True,
            tool="test_gen",
            data={
                "target": source,
                "cases": ["test_init", "test_happy_path", "test_edge_case"],
            },
            msg=f"为 {source} 生成 3 个测试用例计划",
        )


# ---------------------------------------------------------------------------
# 引擎聚合层
# ---------------------------------------------------------------------------


class CodeEngine:
    """代码引擎：聚合各工具，支持依赖注入（默认注入 Stub 实现）。"""

    def __init__(
        self,
        parser: RepoParser | None = None,
        refactor_tool: RefactorTool | None = None,
        git_tool: GitTool | None = None,
        terminal_tool: TerminalTool | None = None,
        vuln_scanner: VulnScanner | None = None,
        test_gen_tool: TestGenTool | None = None,
    ):
        self.parser = parser or StubRepoParser()
        self.refactor_tool = refactor_tool or StubRefactorTool()
        self.git_tool = git_tool or StubGitTool()
        self.terminal_tool = terminal_tool or StubTerminalTool()
        self.vuln_scanner = vuln_scanner or StubVulnScanner()
        self.test_gen_tool = test_gen_tool or StubTestGenTool()

    def analyze(self, repo_path: str) -> dict:
        """组合仓库解析 + 漏洞扫描，返回合并字典。"""
        repo = self.parser.scan(repo_path)
        vuln: CodeResult = self.vuln_scanner.scan(repo_path)
        return {
            "files": repo["files"],
            "languages": repo["languages"],
            "tree_sample": repo["tree_sample"],
            "vuln_findings": vuln.data["findings"],
            "vuln_count": vuln.data["count"],
        }

    def refactor(
        self, root: str, pattern: str, replacement: str, dry_run: bool = True
    ) -> CodeResult:
        return self.refactor_tool.refactor(root, pattern, replacement, dry_run)

    def git_commit(self, repo: str, msg: str, dry_run: bool = True) -> CodeResult:
        return self.git_tool.commit(repo, msg, dry_run)

    def run_terminal(
        self, cmd: str, cwd: str | None = None, dry_run: bool = True
    ) -> CodeResult:
        return self.terminal_tool.run(cmd, cwd, dry_run)

    def gen_tests(self, source: str) -> CodeResult:
        return self.test_gen_tool.gen(source)


def default_engine() -> CodeEngine:
    """返回注入 Stub 实现的默认引擎。"""
    return CodeEngine()


# ---------------------------------------------------------------------------
# Grok Build 桥接层 —— headless CLI 方式调用本地 grok 二进制
# ---------------------------------------------------------------------------

import subprocess
import shutil
import json
import logging

logger = logging.getLogger(__name__)

GROK_BIN = shutil.which("grok") or os.path.expanduser("~/.grok/bin/grok")

# grok 0.2.111 实际不支持、但 XAI 旧代码/文档曾误以为支持的 CLI flag。
# 这些 flag 传入会被 Rust clap 解析器直接拒绝（unexpected argument），导致整个任务失败。
# 桥接层在拼命令前统一过滤掉，避免崩溃；等价能力后续在 XAI 侧实现。
UNSUPPORTED_GROK_FLAGS = {"--check", "--best-of-n"}


class GrokBuildBridge:
    """通过 `grok --single` headless CLI 调用本地 Grok Build 二进制。

    设计要点（对应「双核心融合架构」中代码工程核 Grok Build」：
    - 所有代码开发任务（生成/重构/单测/Git/扫描）经此桥接路由到真实 grok
    - grok 运行在独立子进程中，通过 headless 模式输出 JSON
    - 桥接层只做序列化/反序列化，不包含任何推理逻辑
    - grok 不可用时自动退回 Stub 实现（不阻塞主流程）

    v2.0 四能力映射：
    - agent  → --agent [name] / --agents [JSON]（子 agent 定义与派发）
    - goal   → --best-of-n [N]（并行 N 路取最优，目标驱动优化）【grok 0.2.111 未实现，桥接层已过滤】
    - apply  → --check（自验证循环 + 补丁自动应用）【grok 0.2.111 未实现，桥接层已过滤，等价能力待 XAI 侧实现】
    - dream  → --single + 创作模式 prompt（创意蒸馏与抽象）
    """

    def __init__(self, grok_bin: str = GROK_BIN):
        self.grok_bin = grok_bin
        self.available = bool(shutil.which(grok_bin) or os.path.isfile(grok_bin))
        self._capabilities: list[str] = []
        self._feature_cache: dict | None = None  # 动态探测 grok --help 的结果缓存

    # ---- 动态能力探测：根治『能力声明(wired)与真实二进制脱钩』类问题 ----
    def _detect_grok_features(self) -> dict:
        """运行时动态探测当前安装的 grok 实际支持的 flag / 子命令。

        不再硬编码 wired:True/False——每次进程启动后首次调用时跑一次
        `grok --help` 解析，结果缓存复用。这样 grok 升级/降级后能力清单
        自动对齐，不会出现『代码假设了二进制没有的 --check 之类能力』。
        """
        if getattr(self, "_feature_cache", None) is not None:
            return self._feature_cache
        import re
        feats: dict = {"flags": set(), "subcommands": set(), "raw": ""}
        if self.available:
            try:
                r = subprocess.run([self.grok_bin, "--help"], capture_output=True,
                                   text=True, timeout=20)
                text = (r.stdout or "") + "\n" + (r.stderr or "")
                feats["raw"] = text
                for m in re.finditer(r"--[a-z][a-z0-9\-]*", text):
                    feats["flags"].add(m.group(0))
                # 子命令：COMMANDS 段里缩进 2+ 空格后跟小写单词的行
                for m in re.finditer(r"^[ \t]{2,}([a-z][a-z0-9\-]+)[ \t]", text, re.MULTILINE):
                    feats["subcommands"].add(m.group(1))
            except Exception:
                pass
        self._feature_cache = feats
        return feats

    def _shared_model_env(self) -> dict:
        """共享主程序 key：从 ~/.xai/models.json 取激活模型（DeepSeek V4 Flash）的
        api_key，注入 grok 子进程环境，使 Grok Build 与主控制台共用同一套凭证。

        好处：key 轮换自动同步，无需手动改 launchd plist 或重复维护一份 key。
        """
        env = dict(os.environ)
        try:
            cfg_path = os.path.expanduser("~/.xai/models.json")
            if os.path.isfile(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    md = json.load(f)
                active = next((m for m in md.get("models", []) if m.get("is_active")), None)
                if active and active.get("api_key"):
                    env["DEEPSEEK_API_KEY"] = active["api_key"]
                else:
                    logger.warning("主程序 models.json 无激活模型 key，grok 可能无法鉴权")
        except Exception as e:
            logger.warning("读取主程序共享 key 失败: %s", e)
        return env

    # ---- 基础核心：单轮代码生成（修复参数顺序）----

    def run(self, task: str, cwd: str | None = None, extra_flags: str = "", model: str = "", timeout: int = 600,
            sandbox: str = "", max_turns: int = 0, json_schema: str = "",
            permission_mode: str = "", disable_web_search: bool = False) -> dict:
        """以 headless 模式调用 grok，返回 JSON 结果。

        extra_flags: Grok CLI 额外参数。注意：--check / --best-of-n 在 grok 0.2.111 不支持，
            桥接层会自动过滤，不会传给 grok。
        model: Grok 使用的模型名（如 deepseek-v4-pro），空则用 Grok 默认配置。
        timeout: 超时秒数（默认 600s），超时后返回 partial_output 而非异常。

        v0.2.111 完整能力映射（全部可选，默认不改变原有行为）：
        - sandbox: 沙箱 profile（--sandbox），限制文件/网络访问，处理不可信任务时用。
        - max_turns: 最大 agent 轮数（--max-turns），防止无限循环。
        - json_schema: JSON Schema 字符串（--json-schema），约束结构化输出，隐含 json 输出。
        - permission_mode: 权限模式（--permission-mode）：default/acceptEdits/auto/dontAsk/bypassPermissions/plan。
        - disable_web_search: 关闭联网搜索/抓取（--disable-web-search），离线或敏感任务用。
        """
        if not self.available:
            return {"ok": False, "error": "grok 二进制不可用", "task": task}

        cmd = [self.grok_bin]
        if extra_flags:
            # 过滤 grok 0.2.111 不支持的 flag（--check / --best-of-n 会导致 clap 直接报错）。
            # --best-of-n 后跟一个数值参数，需一并跳过。
            _tokens = extra_flags.split()
            _filtered: list[str] = []
            _skip_value = False
            for _i, _tok in enumerate(_tokens):
                if _skip_value:
                    _skip_value = False
                    continue
                if _tok in UNSUPPORTED_GROK_FLAGS:
                    if _tok == "--best-of-n" and _i + 1 < len(_tokens) and not _tokens[_i + 1].startswith("-"):
                        _skip_value = True
                    continue
                _filtered.append(_tok)
            cmd.extend(_filtered)
        if model:
            cmd.extend(["--model", model])
        if sandbox:
            cmd.extend(["--sandbox", sandbox])
        if max_turns and max_turns > 0:
            cmd.extend(["--max-turns", str(max_turns)])
        if permission_mode:
            cmd.extend(["--permission-mode", permission_mode])
        if disable_web_search:
            cmd.append("--disable-web-search")
        if json_schema:
            # --json-schema 隐含 --output-format json，故不再重复追加 output-format
            cmd.extend(["--json-schema", json_schema, "--single", task])
        else:
            cmd.extend(["--single", task, "--output-format", "json"])
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                cwd=cwd or os.getcwd(), env=self._shared_model_env(),
            )
            try:
                stdout_lines: list[str] = []
                for line in iter(process.stdout.readline, ""):
                    stdout_lines.append(line)
                process.wait(timeout=timeout)
                full_output = "".join(stdout_lines).strip()
                stderr_out = process.stderr.read() if process.stderr else ""
                if process.returncode == 0 and full_output:
                    try:
                        return json.loads(full_output)
                    except json.JSONDecodeError:
                        return {"ok": True, "raw": full_output, "task": task}
                return {"ok": False, "error": (stderr_out or "grok 无输出")[:500],
                        "returncode": process.returncode, "task": task}
            except subprocess.TimeoutExpired:
                process.kill()
                partial = "".join(stdout_lines).strip() + "\n" + (process.stderr.read() if process.stderr else "")
                return {"ok": True, "partial_output": partial[:4000], "truncated": True,
                        "task": task, "error": f"grok 执行超时 ({timeout}s)，已返回部分结果"}
        except FileNotFoundError:
            self.available = False
            return {"ok": False, "error": "grok 二进制未找到", "task": task}
        except Exception as e:
            return {"ok": False, "error": str(e), "task": task}

    def health_check(self) -> dict:
        """快速探测 grok 是否可用。"""
        if not self.available:
            return {"grok_build_bridge": "unavailable", "reason": "二进制未找到"}
        try:
            r = subprocess.run([self.grok_bin, "--version"], capture_output=True, text=True, timeout=10)
            return {"grok_build_bridge": "available", "version": r.stdout.strip() or r.stderr.strip(), "binary": self.grok_bin}
        except Exception as e:
            self.available = False
            return {"grok_build_bridge": "unavailable", "reason": str(e)}

    # ---- v0.2.111 能力扩展：只读子命令（不消耗模型调用）----

    def _run_subcommand(self, args: list[str], timeout: int = 20) -> dict:
        """执行 grok 只读子命令（models/inspect/doctor/sessions 等），返回原始文本。"""
        if not self.available:
            return {"ok": False, "error": "grok 二进制不可用"}
        try:
            r = subprocess.run([self.grok_bin, *args], capture_output=True, text=True, timeout=timeout)
            out = (r.stdout or "").strip()
            err = (r.stderr or "").strip()
            return {"ok": r.returncode == 0, "output": out, "error": err, "returncode": r.returncode}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"grok {' '.join(args)} 超时 ({timeout}s)"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def list_models(self) -> dict:
        """grok models → 解析可用模型清单与默认模型。"""
        res = self._run_subcommand(["models"])
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error", "无法获取模型"), "models": [], "default": None}
        models: list[str] = []
        default = None
        for line in res["output"].splitlines():
            s = line.strip()
            if s.startswith("- ") or s.startswith("* "):
                name = s[2:].strip()
                is_default = s.startswith("* ") or "(default)" in name
                name = name.replace("(default)", "").strip()
                if name:
                    models.append(name)
                    if is_default:
                        default = name
        return {"ok": True, "models": models, "default": default, "count": len(models),
                "raw": res["output"]}

    def inspect(self, cwd: str | None = None) -> dict:
        """grok inspect → 当前目录的配置发现（环境/权限/skills/登录策略）。"""
        if not self.available:
            return {"ok": False, "error": "grok 二进制不可用"}
        try:
            r = subprocess.run([self.grok_bin, "inspect"], capture_output=True, text=True,
                               timeout=20, cwd=cwd or os.getcwd())
            return {"ok": r.returncode == 0, "output": (r.stdout or "").strip(),
                    "error": (r.stderr or "").strip()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def doctor(self) -> dict:
        """grok doctor → 终端支持与配置健康检查（0.2.111 新增）。"""
        return self._run_subcommand(["doctor"])

    def list_sessions(self, limit: int = 20) -> dict:
        """grok sessions list → 最近会话列表（原始文本）。

        ⚠️ grok 0.2.111 的 sessions 是子命令，必须跟 list/search/delete，
        裸 `grok sessions` 会被 clap 拒绝（unexpected argument）。
        """
        res = self._run_subcommand(["sessions", "list"])
        if res.get("ok") and res.get("output"):
            lines = [l for l in res["output"].splitlines() if l.strip()][:limit]
            res["sessions_sample"] = lines
        return res

    def capabilities(self) -> dict:
        """返回结构化能力清单（供前端展示）。

        ⚠️ wired 字段由 _detect_grok_features() 运行时动态探测 grok --help 决定，
        不再硬编码——根治『代码假设了二进制没有的能力』（假 wiring）类问题。
        """
        feats = self._detect_grok_features()
        flags = feats["flags"]
        subs = feats["subcommands"]

        def _wired(flag: str | None = None, sub: str | None = None) -> bool:
            if flag is not None and flag in flags:
                return True
            if sub is not None and sub in subs:
                return True
            return False

        return {
            "binary": self.grok_bin,
            "available": self.available,
            "version_source": "grok --help (动态探测)",
            "dynamic_detected": True,
            "capabilities": [
                {"id": "run", "name": "Headless 代码执行", "flag": "--single --output-format json",
                 "desc": "单轮无界面执行代码任务，返回结构化 JSON（text/thought/usage）", "wired": True},
                {"id": "check", "name": "自验证循环", "flag": "--check",
                 "desc": "执行后追加一层自验证，用于修复/重构/优化类任务（桥接层已过滤 grok 不支持的 flag，等价能力待 XAI 侧实现）", "wired": _wired(flag="--check")},
                {"id": "best_of_n", "name": "并行多路取优", "flag": "--best-of-n N",
                 "desc": "同一任务并行 N 路，自动选最优结果，用于架构/设计探索（桥接层已过滤 grok 不支持的 flag）", "wired": _wired(flag="--best-of-n")},
                {"id": "json_schema", "name": "结构化输出", "flag": "--json-schema",
                 "desc": "用 JSON Schema 约束模型输出格式", "wired": _wired(flag="--json-schema")},
                {"id": "sandbox", "name": "沙箱隔离", "flag": "--sandbox",
                 "desc": "限制文件/网络访问，处理不可信任务", "wired": _wired(flag="--sandbox")},
                {"id": "max_turns", "name": "轮数上限", "flag": "--max-turns",
                 "desc": "限制 agent 最大轮数，防止失控", "wired": _wired(flag="--max-turns")},
                {"id": "permission_mode", "name": "权限模式", "flag": "--permission-mode",
                 "desc": "default/acceptEdits/auto/dontAsk/bypassPermissions/plan", "wired": _wired(flag="--permission-mode")},
                {"id": "models", "name": "模型清单", "flag": "grok models",
                 "desc": "列出所有可用模型与默认模型", "wired": _wired(sub="models")},
                {"id": "inspect", "name": "配置发现", "flag": "grok inspect",
                 "desc": "当前目录的环境/权限/skills/登录策略", "wired": _wired(sub="inspect")},
                {"id": "doctor", "name": "环境体检", "flag": "grok doctor",
                 "desc": "终端支持与配置健康检查", "wired": _wired(sub="doctor")},
                {"id": "sessions", "name": "会话管理", "flag": "grok sessions list",
                 "desc": "列出/搜索/恢复历史会话", "wired": _wired(sub="sessions")},
            ],
        }

# ---- 记忆注入：从 XAI 8层检索上下文，增强 grok 的 prompt ----

def build_grok_context(task: str, memory_core, max_items: int = 3, max_chars: int = 1500) -> str:
    """从 XAI 8层记忆检索相关上下文，注入 grok 的 prompt。

    memory_core: MemoryCore 实例（由调用方传入，避免循环导入）。
    返回注入文本，失败时返回空字符串（不阻断主流程）。
    用关键词匹配过滤不相关的记忆，避免注入噪声。
    """
    try:
        # 提取任务关键���用于相关性匹配（过滤常见编程停用词）
        _STOPWORDS = {"python", "py", "def", "return", "import", "the", "a", "an", "in", "to", "of",
                      "file", "code", "function", "class", "use", "write", "写", "一个", "的", "用",
                      "是", "在", "和", "了", "要", "让", "做", "把", "被", "从", "对", "与",
                      "hello", "world", "echo", "test", "example", "print"}
        task_lower = task.lower()
        task_words = set(w for w in task_lower.replace("，", " ").replace(",", " ").split()
                        if len(w) > 1 and w not in _STOPWORDS)

        def is_relevant(text: str) -> bool:
            """需要至少 2 个任务关键词命中，或关键词数为 0-1 时放行（简单任务无需记忆）。"""
            if not task_words:
                return False  # 无有效关键词 → 不注入，避免噪声
            text_lower = (text or "").lower()
            hits = sum(1 for w in task_words if w in text_lower)
            return hits >= 2 if len(task_words) >= 2 else hits >= 1

        parts: list[str] = []
        injected_chars = 0

        # 锚点记忆：匹配成功模板
        if memory_core:
            anchors = memory_core.query(layer="anchor", engine="grok_build", limit=10)
            added = 0
            for a in (anchors or []):
                if added >= max_items or injected_chars >= max_chars:
                    break
                val = (a.value or "") if hasattr(a, "value") else str(a)
                if len(val) > 20 and is_relevant(val):
                    chunk = f"[成功模板] {val[:200]}"
                    injected_chars += len(chunk)
                    parts.append(chunk)
                    added += 1

        # 失败纠正：避免重复踩坑
        if memory_core:
            failures = memory_core.query(layer="failure_correction", engine="grok_build", limit=5)
            added = 0
            for f in (failures or []):
                if added >= 2 or injected_chars >= max_chars:
                    break
                val = (f.value or "") if hasattr(f, "value") else str(f)
                if val and is_relevant(val):
                    chunk = f"[已知失败·请避免] {val[:150]}"
                    injected_chars += len(chunk)
                    parts.append(chunk)
                    added += 1

        # 用户画像：编码偏好
        if memory_core:
            profiles = memory_core.query(layer="user_profile", engine="grok_build", limit=5)
            profile_tags = set()
            for p in (profiles or []):
                meta = (p.meta or {}) if hasattr(p, "meta") else {}
                val = (p.value or "") if hasattr(p, "value") else ""
                if is_relevant(val):
                    for tag in meta.get("tags", []):
                        profile_tags.add(tag)
            if profile_tags:
                chunk = f"[用户编码偏好] {', '.join(sorted(profile_tags))}"
                injected_chars += len(chunk)
                parts.append(chunk)

        # 因果记忆：模型推荐（全局，不限任务）
        if memory_core:
            causals = memory_core.query(layer="causal", engine="grok_build", limit=20) if memory_core else []
            model_stats: dict[str, dict] = {}
            for c in (causals or []):
                meta = (c.meta or {}) if hasattr(c, "meta") else {}
                m = meta.get("model", "")
                if m:
                    if m not in model_stats:
                        model_stats[m] = {"ok": 0, "total": 0}
                    model_stats[m]["total"] += 1
                    if meta.get("ok"):
                        model_stats[m]["ok"] += 1
            best_model = ""
            best_rate = 0.0
            for m, stats in model_stats.items():
                if stats["total"] >= 2:
                    rate = stats["ok"] / stats["total"]
                    if rate > best_rate:
                        best_rate = rate
                        best_model = m
            if best_model and best_rate >= 0.7:
                chunk = f"[推荐模型] {best_model}（历史成功率 {best_rate:.0%}）"
                injected_chars += len(chunk)
                parts.append(chunk)

        if not parts:
            return ""

        header = "\n\n--- XAI 系统记忆上下文（来自8层记忆系统）---\n"
        context = header + "\n".join(parts) + "\n--- 记忆上下文结束 ---\n"

        if len(context) > max_chars:
            context = context[:max_chars - 50] + "\n...（已截断）\n"

        return context
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Grok 模型偏好（与 XAI 引擎模型同步）
# ---------------------------------------------------------------------------
import json as _json
import threading as _threading

_GROK_PREF_PATH = os.path.join(os.environ.get("XAI_HOME", os.path.expanduser("~/.xai")), "grok_pref.json")
_grok_pref_lock = _threading.Lock()


def load_grok_pref() -> str:
    """读取用户显式设置的 Grok 模型偏好（空串=未设置，用引擎推导）。"""
    try:
        with open(_GROK_PREF_PATH, "r", encoding="utf-8") as f:
            d = _json.load(f)
        return (d.get("model") or "").strip()
    except Exception:
        return ""


def save_grok_pref(model: str) -> None:
    """持久化 Grok 模型偏好到 ~/.xai/grok_pref.json。"""
    try:
        with _grok_pref_lock:
            with open(_GROK_PREF_PATH, "w", encoding="utf-8") as f:
                _json.dump({"model": (model or "").strip()}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def map_engine_to_grok(entry) -> str:
    """将 XAI 引擎模型条目映射为 Grok 模型 key（deepseek-flash / deepseek-pro / 原样 / 空）。

    - DeepSeek → deepseek-flash（Pro/Reasoner/reasoner → deepseek-pro）
    - 名称含 grok → 原样透传
    - 其他 provider（ollama / llamacpp / openai 等）→ 空串（Grok 用默认）
    """
    if not entry:
        return ""
    provider = (getattr(entry, "provider", "") or "").lower()
    model = (getattr(entry, "model", "") or "").lower()
    name = (getattr(entry, "name", "") or "").lower()
    full = f"{model} {name}"
    if "grok" in full:
        return model or name
    if provider == "deepseek" or "deepseek" in model or "ds" in model:
        if "pro" in full or "reasoner" in full or "v4-pro" in full:
            return "deepseek-pro"
        return "deepseek-flash"
    return ""


def resolve_grok_model(engine) -> str:
    """Grok 实际使用的模型：优先用户显式偏好，否则由当前激活引擎模型推导。"""
    pref = load_grok_pref()
    if pref:
        return pref
    try:
        active = engine.model_registry.active()
    except Exception:
        active = None
    return map_engine_to_grok(active)


def default_bridge() -> GrokBuildBridge:
    return GrokBuildBridge()
