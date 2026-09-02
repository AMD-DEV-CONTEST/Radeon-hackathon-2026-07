#!/usr/bin/env python3
"""XAI 桌面启动器 — 原生 App 体验。

双击 XAI.app 后：
  1. 后台启动服务
  2. 以独立窗口模式打开（Chrome app 模式，无地址栏无标签页）
  3. 如果没 Chrome → 用 AppleScript 创建干净 Safari 窗口
  4. 通知栏提示「XAI 已就绪」
"""

from __future__ import annotations
import os, sys, time, signal, socket, subprocess, threading
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
XAI_PORT = int(os.environ.get("XAI_PORT", "8000"))
XAI_HOME = os.environ.get("XAI_HOME", os.path.expanduser("~/.xai"))
XAI_WS = os.environ.get("XAI_WORKSPACE", os.path.join(XAI_HOME, "workspace"))
URL = f"http://localhost:{XAI_PORT}"


def wait_server(port: int, timeout: int = 15) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection(("localhost", port), timeout=1)
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    return False


def start_server() -> subprocess.Popen | None:
    server_script = PROJECT_DIR / "server_xai.py"
    if not server_script.exists():
        return None

    # 杀旧进程（精准 PID，不比杀 pkill 杀一片）
    # 注意：socket/os/signal 已在模块顶部导入，禁止在函数内重复 import，
    # 否则当 8000 端口为空（正常双击场景）时该分支不执行，os 变量未绑定，
    # 后续 os.environ.copy() 会抛 UnboundLocalError（#14 假启动根因）。
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        if s.connect_ex(("127.0.0.1", 8000)) == 0:
            s.close()
            # lsof 查谁占 8000 端口，精准杀
            r = subprocess.run(["lsof", "-ti", ":8000"], capture_output=True, text=True, timeout=5)
            for pid in r.stdout.strip().split():
                if pid:
                    os.kill(int(pid), signal.SIGTERM)
            time.sleep(1)
    except Exception:
        pass

    env = os.environ.copy()
    env["XAI_HOME"] = XAI_HOME
    env["XAI_WORKSPACE"] = XAI_WS
    env["XAI_PORT"] = str(XAI_PORT)

    return subprocess.Popen(
        [sys.executable, str(server_script)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def open_window():
    """打开独立窗口 — 优先 Chrome app 模式（无工具栏），回退 Safari"""

    # 方案A：Chrome app 模式 — 真正的独立窗口
    chrome_paths = [
        "/Applications/Google Chrome.app",
        "/Applications/Microsoft Edge.app",
        "/Applications/Brave Browser.app",
    ]
    for chrome in chrome_paths:
        if Path(chrome).exists():
            app_name = Path(chrome).stem
            print(f"[桌面] 使用 {app_name} app 模式（独立窗口）")
            subprocess.Popen(
                ["open", "-a", app_name, "--args", f"--app={URL}", "--window-size=1200,800"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return

    # 方案B：Safari — AppleScript 创建干净窗口
    print("[桌面] 使用 Safari")
    applescript = f'''
    tell application "Safari"
        activate
        make new document with properties {{URL:"{URL}"}}
    end tell
    '''
    subprocess.run(["osascript", "-e", applescript], timeout=5)


def notify(msg: str):
    """macOS 系统通知"""
    subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "XAI 统一操作台"'],
                   timeout=3, capture_output=True)


def main():
    # 启动服务
    proc = start_server()
    if proc is None:
        print("[桌面] ❌ 找不到 server_xai.py")
        sys.exit(1)

    # 等待就绪
    if not wait_server(XAI_PORT):
        print("[桌面] ❌ 服务启动超时")
        proc.terminate()
        sys.exit(1)

    # 打开独立窗口
    open_window()

    # 通知
    notify("XAI 已就绪，模型: DeepSeek")

    # 清理函数
    def cleanup():
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try: proc.kill()
            except: pass
        pid_file = Path(XAI_HOME) / "server.pid"
        if pid_file.exists():
            try: pid_file.unlink()
            except: pass

    signal.signal(signal.SIGINT, lambda *_: (cleanup(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (cleanup(), sys.exit(0)))

    # 等待服务进程退出
    try:
        proc.wait()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
