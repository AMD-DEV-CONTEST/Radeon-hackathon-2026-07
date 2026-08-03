"""
RD-Agent 原生 Web UI 进程管理器
管理三个 Streamlit UI 的启动/停止/状态
"""
import subprocess
import time
import socket
import signal
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from loguru import logger

def _find_rdagent_path() -> Path:
    """动态查找 rdagent 包路径，不再硬编码 conda 环境路径"""
    try:
        import rdagent
        # namespace package 的 __file__ 可能为 None
        if rdagent.__file__:
            return Path(rdagent.__file__).parent
        # __file__ 为 None 时，用 __path__
        if hasattr(rdagent, '__path__'):
            return Path(list(rdagent.__path__)[0])
    except (ImportError, TypeError, IndexError):
        pass
    # fallback: 从 sys.path 中查找
    import sys
    for p in sys.path:
        if not p:
            continue
        try:
            candidate = Path(p) / "rdagent"
            if candidate.exists():
                return candidate
        except (OSError, ValueError):
            continue
    # 最终 fallback: 原始硬编码路径（macOS 开发环境）
    return Path("/opt/anaconda3/envs/aiquant/lib/python3.10/site-packages/rdagent")

RDAGENT_SITE_PACKAGES = _find_rdagent_path()


@dataclass
class UIProcess:
    name: str
    command: list[str]
    port: int
    process: Optional[subprocess.Popen] = None
    pid: Optional[int] = None

    def is_running(self) -> bool:
        """检查端口是否被占用"""
        if self.process and self.process.poll() is None:
            return True
        return self._port_in_use()

    def _port_in_use(self) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(("127.0.0.1", self.port)) == 0
        except Exception:
            return False


class RDUIManager:
    """RD-Agent 三套 Web UI 的生命周期管理器"""

    def __init__(self):
        self._uis: dict[str, UIProcess] = {}

    # ── 端口定义 ────────────────────────────────────────
    UI_CONFIGS = {
        "log_traces": {
            "name": "日志追踪",
            "port": 19899,
            "description": "查看 RD-Agent 因子进化/模型训练的日志轨迹",
            "icon": "📋",
        },
        "server_ui": {
            "name": "实时日志",
            "port": 19898,
            "description": "实时查看 RD-Agent 运行日志流",
            "icon": "📡",
        },
        "ds_interact": {
            "name": "数据科学交互",
            "port": 19900,
            "description": "交互式数据科学实验与因子探索",
            "icon": "🔬",
        },
    }

    def _get_streamlit_app_path(self, relative_path: str) -> str:
        """获取 rdagent 包内 Streamlit 应用的绝对路径"""
        return str(RDAGENT_SITE_PACKAGES / relative_path)

    def start_ui(self, ui_id: str, log_dir: str = "", force_restart: bool = False) -> dict:
        """启动指定 UI

        Args:
            log_dir: 日志目录路径。可以是父目录（如 .../log/）或具体运行目录。
                     推荐传父目录，让 Streamlit 通过 URL query param log_dir 选择具体运行。
        """
        if ui_id not in self.UI_CONFIGS:
            return {"success": False, "error": f"未知 UI: {ui_id}"}

        config = self.UI_CONFIGS[ui_id]
        port = config["port"]

        # 检查是否已在运行
        existing = self._uis.get(ui_id)
        if existing and existing.is_running():
            if not force_restart:
                return {
                    "success": True,
                    "message": f"{config['name']} 已在运行",
                    "port": port,
                    "url": f"http://localhost:{port}",
                }
            else:
                logger.info(f"force_restart=True，终止旧进程: {ui_id}")
                if existing.process and existing.process.poll() is None:
                    existing.process.terminate()
                    try:
                        existing.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        logger.warning(f"进程未在5秒内退出，强制终止: {ui_id}")
                        existing.process.kill()
                        existing.process.wait(timeout=3)
                self._uis.pop(ui_id, None)

        # force_restart 时或端口被占用时，释放端口
        # 即使 existing 为 None（API 重启后状态丢失），也要清理端口
        if force_restart or self._port_open(port):
            self._kill_port(port)
            time.sleep(1)  # 等待端口释放

        # 构建启动命令
        try:
            if ui_id == "log_traces":
                app_path = self._get_streamlit_app_path("log/ui/app.py")
                cmd = [
                    "streamlit", "run", app_path,
                    f"--server.port={port}",
                    "--server.headless=true",
                    "--browser.serverAddress=0.0.0.0",
                ]
                if log_dir:
                    cmd.extend(["--", f"--log_dir={log_dir}"])

            elif ui_id == "server_ui":
                server_app = RDAGENT_SITE_PACKAGES / "log" / "server" / "app.py"
                cmd = ["python", str(server_app), f"--port={port}"]

            elif ui_id == "ds_interact":
                app_path = self._get_streamlit_app_path("log/ui/ds_user_interact.py")
                cmd = [
                    "streamlit", "run", app_path,
                    f"--server.port={port}",
                    "--server.headless=true",
                    "--browser.serverAddress=0.0.0.0",
                ]

            logger.info(f"启动 {config['name']}: {' '.join(cmd)}")

            # 将 stdout/stderr 重定向到日志文件，便于排查启动问题
            ui_log_path = Path("/tmp") / f"aiquant_ui_{ui_id}.log"
            ui_log_file = open(ui_log_path, "w")
            proc = subprocess.Popen(
                cmd,
                stdout=ui_log_file,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if os.name != "nt" else None,
            )

            ui_proc = UIProcess(
                name=config["name"],
                command=cmd,
                port=port,
                process=proc,
                pid=proc.pid,
            )
            self._uis[ui_id] = ui_proc

            # 等待端口就绪
            for _ in range(15):
                time.sleep(1)
                if ui_proc._port_in_use():
                    return {
                        "success": True,
                        "message": f"{config['name']} 已启动",
                        "port": port,
                        "url": f"http://localhost:{port}",
                        "pid": proc.pid,
                    }

            return {
                "success": True,
                "message": f"{config['name']} 正在启动中（可能需要10-15秒）",
                "port": port,
                "url": f"http://localhost:{port}",
                "pid": proc.pid,
            }

        except Exception as e:
            logger.error(f"启动 {config['name']} 失败: {e}")
            return {"success": False, "error": str(e)}

    def stop_ui(self, ui_id: str) -> dict:
        """停止指定 UI"""
        if ui_id not in self.UI_CONFIGS:
            return {"success": False, "error": f"未知 UI: {ui_id}"}

        config = self.UI_CONFIGS[ui_id]
        port = config["port"]
        proc = self._uis.pop(ui_id, None)

        killed = False
        if proc and proc.process:
            try:
                if os.name != "nt":
                    os.killpg(os.getpgid(proc.process.pid), signal.SIGTERM)
                else:
                    proc.process.terminate()
                proc.process.wait(timeout=5)
                killed = True
            except Exception:
                try:
                    proc.process.kill()
                    killed = True
                except Exception:
                    pass

        # 兜底：通过端口杀进程
        self._kill_port(port)

        return {
            "success": True,
            "message": f"{config['name']} 已停止",
            "port": port,
        }

    @staticmethod
    def _port_open(port: int) -> bool:
        """探测端口是否有进程监听（兜底用，不依赖进程字典）"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    def get_all_status(self) -> dict:
        """获取所有 UI 状态"""
        result = {}
        for ui_id, config in self.UI_CONFIGS.items():
            proc = self._uis.get(ui_id)
            # 进程字典为准；字典缺失（worker 重启 / 外部启动）时端口探测兜底
            running = (proc.is_running() if proc else False) or self._port_open(config["port"])
            result[ui_id] = {
                "name": config["name"],
                "description": config["description"],
                "icon": config["icon"],
                "port": config["port"],
                "running": running,
                "url": f"http://localhost:{config['port']}" if running else None,
                "pid": proc.pid if proc else None,
            }
        return result

    def _kill_port(self, port: int):
        """释放指定端口（不依赖 lsof，纯 Python 实现）"""
        import subprocess
        try:
            # 用 psutil 找到占用端口的进程
            try:
                import psutil
                for conn in psutil.net_connections():
                    if conn.laddr and conn.laddr.port == port and conn.pid:
                        if conn.pid != os.getpid():
                            try:
                                os.kill(conn.pid, signal.SIGKILL)
                            except Exception:
                                pass
                return
            except ImportError:
                pass

            # fallback: lsof
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True
            )
            pids = result.stdout.strip().split("\n")
            for pid_str in pids:
                pid_str = pid_str.strip()
                if pid_str and pid_str != str(os.getpid()):
                    try:
                        os.kill(int(pid_str), signal.SIGKILL)
                    except Exception:
                        pass
        except Exception:
            pass


# 全局单例
ui_manager = RDUIManager()
