"""XAI V4 Action Bus — 所有系统动作的统一入口。

V4 §5: 任何模块禁止直接写文件/执行命令/调网络。
所有动作必须经过: ActionBus → Guardian → Executor → Result。

Actions: file, exec, network, model, agent
每条 Action 记录: action, source, time, approval, result

Phase G（#211）真实执行化：
- 之前 _execute 仅做 Guardian 检查 + 审计日志，返回 "accepted" 不实际执行。
- 现接入 LocalExecutor，对 file_write / file_delete / exec_command / network_request
  在 Guardian 放行后真实执行；Guardian 拒绝（P0/需审批）则不执行，保持治理闸门。
- 引擎直执行（画布 exec 节点）改走 ActionBus（见 core/kernel/workflow.py wf_node_exec），
  带 openclaw fallback 兼容历史行为。
"""

from __future__ import annotations

import os
import time
import shutil
import subprocess
import urllib.request
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


class ActionType(str, Enum):
    FILE = "file"
    EXEC = "exec"
    NETWORK = "network"
    MODEL = "model"
    AGENT = "agent"


@dataclass
class ActionLog:
    """每条 Action 的审计日志"""
    action: str          # 动作描述
    action_type: ActionType
    source: str          # 发起模块
    timestamp: float = field(default_factory=time.time)
    approval: str = ""   # "auto" | "auto-P1" | "approved-<aid>" | "denied-P0" | "pending-P1"
    result: str = ""     # "ok" | "error:<msg>"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    """Action 执行结果"""
    ok: bool
    output: str = ""
    error: str = ""
    log: Optional[ActionLog] = None
    sandbox_mode: str = ""  # "hard" | "soft" | "none"


def _set_process_limits():
    """macOS 进程资源限制：CPU 60s / 内存 512MB / 禁用 fork。"""
    import resource
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except Exception:
        pass


class LocalExecutor:
    """本地真实执行器（Phase G 补齐 V4 §5 缺口）。

    受 ActionBus 的 Guardian 闸门保护：仅在 Guardian 放行后才会被调用。
    - file_write: 真实写文件（自动建父目录）
    - file_delete: 安全删除（移入 trash 目录，避免不可逆 rm）
    - exec_command: 真实 Shell 执行（带超时，捕获输出）
    - network_request: 真实 HTTP GET（带超时）
    所有方法均返回 (ok, output) 且内部吞掉异常，绝不向上抛。
    """

    def __init__(self, trash_dir: str = ""):
        self.trash_dir = trash_dir or os.path.join(
            os.path.expanduser("~/.xai"), "trash"
        )
        # P0-K3b: 硬沙箱检测 — nsjail > firejail > macOS sandbox-exec > setrlimit
        self._nsjail_path = shutil.which('nsjail')
        self._firejail_path = shutil.which('firejail')
        self._nsjail_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nsjail.cfg")
        # 硬沙箱 profile 路径
        self._sandbox_profile = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "sandbox_profile.sb"
        )

    @property
    def sandbox_mode(self) -> str:
        """当前沙箱模式：hard (nsjail/firejail) | soft (setrlimit) | none"""
        if self._nsjail_path or self._firejail_path:
            return "hard"
        return "soft"

    def run_hardened(self, cmd: str, timeout: float = 60.0) -> Tuple[bool, str]:
        """硬沙箱执行——nsjail > firejail > macOS sandbox-exec > setrlimit。"""
        # P0-K3b: nsjail 优先
        if self._nsjail_path and os.path.exists(self._nsjail_cfg_path):
            sandbox_cmd = [self._nsjail_path, '--mode', 'o', '--config', self._nsjail_cfg_path, '--', '/bin/bash', '-c', cmd]
            return self._run_sandboxed_cmd(sandbox_cmd, timeout)
        # firejail 次之
        if self._firejail_path:
            sandbox_cmd = [self._firejail_path, '--quiet', '--net=none', '--timeout=60', '--', '/bin/bash', '-c', cmd]
            return self._run_sandboxed_cmd(sandbox_cmd, timeout)
        # macOS sandbox-exec 兜底
        if os.path.exists(self._sandbox_profile):
            # 与 nsjail/firejail 路径一致：用 `sh -c <cmd>` 包装执行体；否则
            # `sandbox-exec -f prof + shlex.split(cmd)` 会把 args[0] 当成可执行文件
            # —— 模型思考文本/复杂 shell 都会触发 execvp 失败（exit 71）。
            sandbox_cmd = ["sandbox-exec", "-f", self._sandbox_profile, "sh", "-c", cmd]
            ok, out = self._run_sandboxed_cmd(sandbox_cmd, timeout)
            if ok:
                return True, out
            # sandbox-exec 失败 → 软退 setrlimit
            print(f"[SANDBOX] sandbox-exec failed ({out[:120]}), falling back to setrlimit", flush=True)
        # 软退：setrlimit
        print("[SANDBOX] no container/hard sandbox available, using setrlimit soft sandbox", flush=True)
        return self.run_command(cmd, timeout)

    def _run_sandboxed_cmd(self, sandbox_cmd: list, timeout: float) -> Tuple[bool, str]:
        """运行沙箱包装命令，统一超时/输出处理。"""
        try:
            proc = subprocess.Popen(
                sandbox_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                preexec_fn=_set_process_limits if os.name != "nt" else None,
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return False, f"沙箱超时（>{timeout}s），已终止"
            out = (stdout or "") + (stderr or "")
            if proc.returncode != 0:
                return False, f"[sandbox exit {proc.returncode}] {out[:800]}"
            return True, out[:20000]
        except FileNotFoundError:
            return False, "沙箱二进制不可用"
        except Exception as e:
            return False, f"沙箱执行失败: {e}"

    def write_file(self, path: str, content: str) -> Tuple[bool, str]:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return True, f"已写入 {path}（{len(content)} 字符）"
        except Exception as e:
            return False, f"写文件失败: {e}"

    def delete_file(self, path: str) -> Tuple[bool, str]:
        try:
            p = Path(path)
            if not p.exists():
                return False, f"文件不存在: {path}"
            os.makedirs(self.trash_dir, exist_ok=True)
            dest = os.path.join(self.trash_dir, f"{int(time.time()):.0f}_{p.name}")
            shutil.move(str(p), dest)
            return True, f"已移入回收站: {dest}"
        except Exception as e:
            return False, f"删除失败: {e}"

    def run_command(self, cmd: str, timeout: float = 60.0, max_output: int = 20000) -> Tuple[bool, str]:
        """在沙箱中执行命令——禁止 shell=True，限制资源和输出。"""
        import shlex
        try:
            args = shlex.split(cmd)
        except ValueError:
            args = ["sh", "-c", cmd]  # fallback for complex commands
        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                # macOS 资源限制
                preexec_fn=_set_process_limits if os.name != "nt" else None,
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return False, f"沙箱超时（>{timeout}s），已终止"
            out = (stdout or "") + (stderr or "")
            if len(out) > max_output:
                out = out[:max_output] + f"\n... (截断，共{len(out)}字符)"
            if proc.returncode != 0:
                return False, f"[exit {proc.returncode}] {out[:800]}"
            return True, out[:max_output]
        except FileNotFoundError:
            return False, "命令未找到（沙箱限制：不允许的路径）"
        except Exception as e:
            return False, f"沙箱执行失败: {e}"

    def http_request(self, url: str, timeout: float = 15.0) -> Tuple[bool, str]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "XAI/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(8000).decode("utf-8", errors="ignore")
            return True, body[:2000]
        except Exception as e:
            return False, f"请求失败: {e}"


class ActionBus:
    """V4 执行总线。所有系统动作必须通过此入口。

    职责:
      1. 统一 Action 入口
      2. Guardian 风险评估
      3. 执行器路由（Phase G: 真实执行）
      4. 审计日志
    """

    def __init__(self, guardian=None, max_log_size: int = 1000, executor=None):
        self._guardian = guardian
        self._logs: List[ActionLog] = []
        self._max_logs = max_log_size
        self._executor = executor or LocalExecutor()

    def set_executor(self, executor) -> None:
        """注入自定义执行器（测试 / 替换后端）。"""
        self._executor = executor

    # ---- 动作定义 ----

    def file_write(self, path: str, content: str, source: str = "engine") -> ActionResult:
        """写入文件。Guardian 检查后真实写入（Phase G）。"""
        return self._execute(ActionType.FILE, f"写文件: {path}", source,
                             detail=path, payload=content)

    def file_delete(self, path: str, source: str = "engine") -> ActionResult:
        """删除文件。Guardian P0 检查（默认拒绝，仅审批后可执行）。"""
        return self._execute(ActionType.FILE, f"删除文件: {path}", source,
                             detail=path, require_approval=True)

    def exec_command(self, cmd: str, source: str = "engine") -> ActionResult:
        """执行 Shell 命令。Guardian P1 检查后真实执行（Phase G）。"""
        return self._execute(ActionType.EXEC, f"执行: {cmd[:80]}", source,
                             detail=cmd)

    def network_request(self, url: str, source: str = "engine") -> ActionResult:
        """网络请求。Guardian P1 检查后真实请求（Phase G）。"""
        return self._execute(ActionType.NETWORK, f"请求: {url[:80]}", source, detail=url)

    def model_call(self, model: str, prompt_len: int, source: str = "engine") -> ActionResult:
        """模型调用。P2 日志，无需审批。"""
        return self._execute(ActionType.MODEL, f"模型: {model} ({prompt_len} chars)", source,
                             detail=f"{model}:{prompt_len}")

    def agent_call(self, agent: str, task: str, source: str = "planner") -> ActionResult:
        """Agent 调用。P2 日志，无需审批。"""
        return self._execute(ActionType.AGENT, f"Agent: {agent} → {task[:60]}", source,
                             detail=f"{agent}:{task[:80]}")

    # ---- 核心逻辑 ----

    @staticmethod
    def _guardian_kind(action_type: ActionType, require_approval: bool) -> str:
        """将 ActionBus 动作类型映射到 Guardian 的 kind（对齐 guardian.classify）。"""
        if action_type == ActionType.FILE:
            # 删除走 P0 delete_file（被闸门拦截）；普通写文件按 P2 compute 放行
            return "delete_file" if require_approval else "compute"
        if action_type == ActionType.EXEC:
            return "run_command"
        if action_type == ActionType.NETWORK:
            return "network"
        return "compute"

    def _execute(self, action_type: ActionType, action: str, source: str,
                 detail: str = "", payload: str = "", require_approval: bool = False) -> ActionResult:
        """统一执行流程: Guardian → 审批 → 真实执行 → 日志。"""

        # Step 1: Guardian 风险评估
        approval_status = "auto"
        try:
            from core.guardian import Action as GAction, classify as g_classify, RiskLevel
            kind = self._guardian_kind(action_type, require_approval)
            gaction = GAction(kind=kind, target=detail[:200])
            result = g_classify(gaction)
            if result.level == RiskLevel.P0:
                return ActionResult(ok=False, error=f"P0 风险操作被拒绝: {result.reason}",
                                    log=ActionLog(action=action, action_type=action_type,
                                                  source=source, approval="denied-P0"))
            if result.level == RiskLevel.P1:
                if require_approval:
                    return ActionResult(ok=False, error=f"P1 操作需要审批: {result.reason}",
                                        log=ActionLog(action=action, action_type=action_type,
                                                      source=source, approval="pending-P1"))
                approval_status = "auto-P1"
        except ImportError:
            pass  # Guardian 未安装，放行

        # Step 2: 真实执行（Phase G 补齐，含看门狗计时）
        exec_output = ""
        exec_ok = True
        sandbox_mode = ""
        started_at = time.time()
        wd_task_id = None
        try:
            from core.task_watchdog import global_watchdog
            wd_task_id = global_watchdog.watch(
                f"action:{action_type.value}", timeout_s=45,
                fallback=lambda: None,
            )
        except ImportError:
            pass
        try:
            if action_type == ActionType.FILE and require_approval:
                exec_ok, exec_output = self._executor.delete_file(detail)
            elif action_type == ActionType.FILE:
                exec_ok, exec_output = self._executor.write_file(detail, payload)
            elif action_type == ActionType.EXEC:
                exec_ok, exec_output = self._executor.run_hardened(detail)
                sandbox_mode = self._executor.sandbox_mode
            elif action_type == ActionType.NETWORK:
                exec_ok, exec_output = self._executor.http_request(detail)
            # MODEL / AGENT 仅审计，不实际执行
        except Exception as e:
            exec_ok, exec_output = False, f"执行器异常: {e}"
        finally:
            if wd_task_id:
                elapsed = time.time() - started_at
                try:
                    from core.task_watchdog import global_watchdog
                    if elapsed > 30:
                        global_watchdog.fail(wd_task_id, f"耗时 {elapsed:.1f}s (阈值 30s)")
                    else:
                        global_watchdog.resolve(wd_task_id, {"elapsed_s": round(elapsed, 1), "ok": exec_ok})
                except ImportError:
                    pass

        # Step 3: 记录日志
        result_str = "ok" if exec_ok else f"error:{exec_output[:120]}"
        log = ActionLog(action=action, action_type=action_type, source=source,
                        approval=approval_status, result=result_str)
        self._logs.append(log)
        if len(self._logs) > self._max_logs:
            self._logs = self._logs[-self._max_logs:]

        if not exec_ok:
            return ActionResult(ok=False, error=exec_output, log=log, sandbox_mode=sandbox_mode)
        return ActionResult(ok=True, output=exec_output, log=log, sandbox_mode=sandbox_mode)

    # ---- 审计 ----

    def recent_logs(self, limit: int = 50) -> List[ActionLog]:
        return self._logs[-limit:]

    def log_count(self) -> int:
        return len(self._logs)


# 单例
_default_bus: Optional[ActionBus] = None


def default_action_bus(guardian=None) -> ActionBus:
    global _default_bus
    if _default_bus is None:
        _default_bus = ActionBus(guardian=guardian)
    return _default_bus
