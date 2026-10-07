"""Background launcher for eval_sort_smolvla.py on the remote instance.

Uploads a tiny bash wrapper to /tmp and runs it via JupyterLab kernel.
Usage (local):
    python scripts/run_eval_sort_bg.py
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

JUPYTER_URL = "https://radeon-global.anruicloud.com/instances/u-13944-c577fd88/lab"

WRAPPER = r"""#!/bin/bash
set -e
cd /workspace/franka_fruit_pick_demo
export MPLBACKEND=Agg
LOG=/tmp/eval_sort.log
rm -f "$LOG"
nohup .venv/bin/python franka_fruit_pick/eval_sort_smolvla.py \
    --checkpoint outputs/train/smolvla_lerobot/checkpoints/002000 \
    --episodes 1 \
    --max-steps 400 \
    --output /tmp/eval_results.json \
    --save-video /workspace/eval_videos \
    > "$LOG" 2>&1 &
PID=$!
echo "started PID=$PID log=$LOG"
sleep 20
if kill -0 $PID 2>/dev/null; then
    echo "STATUS: running"
else
    echo "STATUS: exited"
fi
echo "---LOG_HEAD---"
head -80 "$LOG" 2>/dev/null || true
echo "---LOG_TAIL---"
tail -40 "$LOG" 2>/dev/null || true
"""


async def upload(page, remote_path: str, content: str) -> dict:
    base_url = page.url.split("/lab")[0]
    api_path = remote_path.lstrip("/")
    if api_path.startswith("workspace/"):
        api_path = api_path[len("workspace/"):]
    url = f"{base_url}/api/contents/{api_path}"
    body = {"type": "file", "format": "text", "content": content}
    return await page.evaluate("""
        async (params) => {
            const resp = await fetch(params.url, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                body: JSON.stringify(params.body),
            });
            return {status: resp.status, body: await resp.text()};
        }
    """, {"url": url, "body": body})


async def run_shell(page, cmd: str, timeout: int = 60) -> str:
    code = f"""
import subprocess
r = subprocess.run({cmd!r}, capture_output=True, text=True, shell=True, executable='/bin/bash')
print(r.stdout)
if r.stderr:
    print('STDERR:', r.stderr)
print('EXIT_CODE:', r.returncode)
"""
    base_url = page.url.split("/lab")[0]
    kernel_id = await page.evaluate("""
        async (base) => {
            const resp = await fetch(`${base}/api/kernels`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                body: JSON.stringify({name: 'python3', kind: 'kernel'})
            });
            const data = await resp.json();
            return data.id;
        }
    """, base_url)

    output = await page.evaluate("""
        async (params) => {
            const {base, kernelId, code, timeoutSec} = params;
            return new Promise((resolve, reject) => {
                const wsUrl = base.replace(/^http/, 'ws') + `/api/kernels/${kernelId}/channels`;
                const ws = new WebSocket(wsUrl);
                const outputs = [];
                let msgId = null;
                let settled = false;
                ws.onopen = () => {
                    msgId = Math.random().toString(36).substring(2);
                    ws.send(JSON.stringify({
                        header: {msg_id: msgId, msg_type: 'execute_request', version: '5.3'},
                        parent_header: {}, metadata: {},
                        content: {code, silent: false, store_history: false, user_expressions: {}, allow_stdin: false},
                        channel: 'shell'
                    }));
                };
                ws.onmessage = (ev) => {
                    const m = JSON.parse(ev.data);
                    if (m.parent_header && m.parent_header.msg_id !== msgId) return;
                    if (m.msg_type === 'stream') outputs.push(m.content.text);
                    else if (m.msg_type === 'execute_result') outputs.push(m.content.data['text/plain']);
                    else if (m.msg_type === 'error') outputs.push(m.content.traceback.join('\\n'));
                    else if (m.msg_type === 'status' && m.content.execution_state === 'idle' && msgId) {
                        settled = true; try { ws.close(); } catch (e) {} resolve(outputs.join('\\n'));
                    }
                };
                ws.onerror = (e) => { if (!settled) reject(new Error('ws error')); };
                setTimeout(() => { if (!settled) { try { ws.close(); } catch (e) {}
                    resolve(outputs.join('\\n') || `(timeout after ${timeoutSec}s)`); } }, timeoutSec * 1000);
            });
        }
    """, {"base": base_url, "kernelId": kernel_id, "code": code, "timeoutSec": timeout})

    try:
        await page.evaluate("""
            async (params) => {
                await fetch(`${params.base}/api/kernels/${params.kid}`, {
                    method: 'DELETE', headers: {'X-Requested-With': 'XMLHttpRequest'}
                });
            }
        """, {"base": base_url, "kid": kernel_id})
    except Exception:
        pass
    return output


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = None
        for pg in context.pages:
            if "instances" in (pg.url or "") and "lab" in (pg.url or ""):
                page = pg
                print(f"[connect] JupyterLab: {pg.url}", file=sys.stderr)
                break
        if page is None:
            print("[connect] no JupyterLab page found", file=sys.stderr)
            sys.exit(1)
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # Upload wrapper script (must be under /workspace which is JupyterLab root)
        result = await upload(page, "/workspace/run_eval_sort.sh", WRAPPER)
        print(f"[upload] wrapper HTTP {result['status']}")
        if result['status'] >= 400:
            print(f"[upload] error: {result['body'][:300]}")
            sys.exit(2)

        # Make it executable and run it
        out = await run_shell(page, "chmod +x /workspace/run_eval_sort.sh && bash /workspace/run_eval_sort.sh", timeout=45)
        print(out)


if __name__ == "__main__":
    asyncio.run(main())
