"""
Radeon Cloud 远程执行工具 - 基于 JupyterLab REST API + WebSocket
复用 browser-login-reuse Skill 的核心方法
用法: python remote_exec.py "shell 命令"
     python remote_exec.py --py "python 代码"
     python remote_exec.py --file 脚本.py
"""
import asyncio
import os
import sys
import json
from playwright.async_api import async_playwright

JUPYTER_URL = "https://radeon-global.anruicloud.com/instances/u-13944-c577fd88/lab"
WORKSPACE = r"d:\APPs\amdRadeon"
LOGS_DIR = os.path.join(WORKSPACE, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)


async def execute_via_jupyter_api(page, code, timeout=60):
    """通过 JupyterLab REST API + WebSocket 执行 Python 代码，返回输出文本"""
    base_url = page.url.split("/lab")[0]

    # 1. 创建 kernel
    try:
        kernel_id = await page.evaluate("""
            async (base) => {
                const resp = await fetch(`${base}/api/kernels`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                    body: JSON.stringify({name: 'python3', kind: 'kernel'})
                });
                if (!resp.ok) {
                    const text = await resp.text();
                    throw new Error(`HTTP ${resp.status}: ${text}`);
                }
                const data = await resp.json();
                return data.id;
            }
        """, base_url)
    except Exception as e:
        return f"[ERROR] 创建 kernel 失败: {e}"

    # 2. WebSocket 执行代码
    try:
        output = await page.evaluate("""
            async (params) => {
                const {base, kernelId, code, timeoutSec} = params;
                return new Promise((resolve, reject) => {
                    const wsUrl = base.replace(/^http/, 'ws') + `/api/kernels/${kernelId}/channels`;
                    let ws;
                    try { ws = new WebSocket(wsUrl); }
                    catch (e) { reject('WebSocket 创建失败: ' + e.message); return; }

                    const outputs = [];
                    const msgId = 'msg-' + Math.random().toString(36).slice(2, 12);
                    const sessionId = 'sess-' + Math.random().toString(36).slice(2, 12);
                    let idleReceived = false;

                    ws.onopen = () => {
                        ws.send(JSON.stringify({
                            header: {msg_id: msgId, username: '', session: sessionId,
                                     msg_type: 'execute_request', version: '5.4'},
                            parent_header: {}, metadata: {},
                            content: {code: code, silent: false, store_history: true,
                                      user_expressions: {}, allow_stdin: false,
                                      stop_on_error: true},
                            channel: 'shell'
                        }));
                    };

                    ws.onmessage = (event) => {
                        let msg;
                        try { msg = JSON.parse(event.data); } catch (e) { return; }
                        const parentMsgId = msg.parent_header && msg.parent_header.msg_id;
                        if (parentMsgId !== msgId) return;

                        const t = msg.msg_type;
                        if (t === 'stream') {
                            outputs.push(msg.content.text || '');
                        } else if (t === 'execute_result') {
                            const text = msg.content.data && msg.content.data['text/plain'];
                            if (text) outputs.push(text);
                        } else if (t === 'display_data') {
                            const text = msg.content.data && msg.content.data['text/plain'];
                            if (text) outputs.push('[display] ' + text);
                        } else if (t === 'error') {
                            outputs.push('ERROR: ' + (msg.content.ename || '') + ': ' + (msg.content.evalue || ''));
                            outputs.push((msg.content.traceback || []).join('\\n'));
                        } else if (t === 'status' && msg.content.execution_state === 'idle') {
                            idleReceived = true;
                            ws.close();
                            resolve(outputs.join('\\n') || '(no output, kernel idle)');
                        }
                    };

                    ws.onerror = (e) => reject('WebSocket 错误: ' + (e.message || 'unknown'));
                    setTimeout(() => {
                        if (!idleReceived) {
                            try { ws.close(); } catch (e) {}
                            resolve(outputs.join('\\n') || `(timeout after ${timeoutSec}s)`);
                        }
                    }, timeoutSec * 1000);
                });
            }
        """, {"base": base_url, "kernelId": kernel_id, "code": code, "timeoutSec": timeout})
    except Exception as e:
        output = f"[ERROR] 执行失败: {e}"

    # 3. 关闭 kernel
    try:
        await page.evaluate("""
            async (params) => {
                await fetch(`${params.base}/api/kernels/${params.kid}`, {
                    method: 'DELETE',
                    headers: {'X-Requested-With': 'XMLHttpRequest'}
                });
            }
        """, {"base": base_url, "kid": kernel_id})
    except Exception:
        pass

    return output


async def run_shell(page, cmd, timeout=60):
    """执行 shell 命令，返回输出"""
    code = f"""
import subprocess
r = subprocess.run({cmd!r}, capture_output=True, text=True, shell=True, executable='/bin/bash')
print(r.stdout)
if r.stderr:
    print('STDERR:', r.stderr)
print('EXIT_CODE:', r.returncode)
"""
    return await execute_via_jupyter_api(page, code, timeout=timeout)


async def main():
    if len(sys.argv) < 2:
        print("用法: python remote_exec.py --shell 'shell 命令' [timeout]")
        print("     python remote_exec.py --py 'python 代码' [timeout]")
        print("     python remote_exec.py --file 脚本.py [timeout]")
        sys.exit(1)

    # 解析参数
    mode = sys.argv[1]
    if mode == '--py':
        code = sys.argv[2]
        timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 60
        is_python = True
    elif mode == '--file':
        with open(sys.argv[2], 'r', encoding='utf-8') as f:
            code = f.read()
        timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 120
        is_python = True
    elif mode == '--shell':
        cmd = sys.argv[2]
        timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 60
        is_python = False
    else:
        # 兼容旧用法：第一个参数就是 shell 命令
        cmd = sys.argv[1]
        timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        is_python = False

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()

        # 找 JupyterLab 页面
        page = None
        for pg in context.pages:
            url = pg.url or ""
            if "instances" in url and "lab" in url:
                page = pg
                print(f"[连接] 找到 JupyterLab 页面: {url}", file=sys.stderr)
                break

        if page is None:
            print(f"[连接] 未找到 JupyterLab 页面，新开一个...", file=sys.stderr)
            page = await context.new_page()
            await page.goto(JUPYTER_URL, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(5)

        # 确保页面加载完成
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(2)

        if is_python:
            output = await execute_via_jupyter_api(page, code, timeout=timeout)
        else:
            output = await run_shell(page, cmd, timeout=timeout)

        print(output)


asyncio.run(main())
