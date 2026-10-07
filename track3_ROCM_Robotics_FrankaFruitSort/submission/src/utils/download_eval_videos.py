"""Download eval videos and results from remote JupyterLab via Contents API.

Usage:
    python scripts/download_eval_videos.py
"""
import asyncio
import sys
import base64
from pathlib import Path

from playwright.async_api import async_playwright

REMOTE_FILES = [
    ("/workspace/eval_videos/ep1_018_plum.mp4", "d:/APPs/amdRadeon/screenshots/sort_demo/ep1_018_plum.mp4"),
    ("/workspace/eval_videos/ep1_011_banana.mp4", "d:/APPs/amdRadeon/screenshots/sort_demo/ep1_011_banana.mp4"),
    ("/tmp/eval_results.json", "d:/APPs/amdRadeon/logs/eval_results.json"),
]


async def download_file(page, remote_path: str, local_path: str) -> None:
    base_url = page.url.split("/lab")[0]
    api_path = remote_path.lstrip("/")
    if api_path.startswith("workspace/"):
        api_path = api_path[len("workspace/"):]
    elif api_path.startswith("tmp/"):
        # /tmp is outside JupyterLab root; read via shell base64 instead
        await download_via_shell(page, remote_path, local_path)
        return
    url = f"{base_url}/api/contents/{api_path}"

    result = await page.evaluate("""
        async (url) => {
            const resp = await fetch(url, {
                headers: {'X-Requested-With': 'XMLHttpRequest'},
            });
            const data = await resp.json();
            return {status: resp.status, content: data.content, format: data.format};
        }
    """, url)

    if result["status"] >= 400:
        print(f"[download] FAIL {remote_path}: HTTP {result['status']}")
        return

    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    if result["format"] == "base64":
        data = base64.b64decode(result["content"])
        Path(local_path).write_bytes(data)
    else:
        Path(local_path).write_text(result["content"], encoding="utf-8")
    print(f"[download] OK {remote_path} -> {local_path} ({Path(local_path).stat().st_size} bytes)")


async def download_via_shell(page, remote_path: str, local_path: str) -> None:
    """Download a file outside JupyterLab root via shell base64 -> Contents API."""
    # Copy to /workspace first, then download via Contents API
    tmp_workspace = f"/workspace/_tmp_download_{Path(remote_path).name}"
    code = f"""
import subprocess
r = subprocess.run(['cp', {remote_path!r}, {tmp_workspace!r}], capture_output=True, text=True)
print('CP_EXIT', r.returncode)
if r.stderr:
    print('CP_ERR', r.stderr)
"""
    # Run via kernel
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

    await page.evaluate("""
        async (params) => {
            const {base, kernelId, code} = params;
            return new Promise((resolve) => {
                const wsUrl = base.replace(/^http/, 'ws') + `/api/kernels/${kernelId}/channels`;
                const ws = new WebSocket(wsUrl);
                const outputs = [];
                let msgId = null;
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
                    else if (m.msg_type === 'status' && m.content.execution_state === 'idle' && msgId) {
                        try { ws.close(); } catch (e) {} resolve(outputs.join('\\n'));
                    }
                };
                setTimeout(() => { try { ws.close(); } catch (e) {} resolve(outputs.join('\\n')); }, 15000);
            });
        }
    """, {"base": base_url, "kernelId": kernel_id, "code": code})

    await page.evaluate("""
        async (params) => {
            await fetch(`${params.base}/api/kernels/${params.kid}`, {
                method: 'DELETE', headers: {'X-Requested-With': 'XMLHttpRequest'}
            });
        }
    """, {"base": base_url, "kid": kernel_id})

    # Now download via Contents API
    await download_file(page, tmp_workspace, local_path)


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
            print("[connect] no JupyterLab page", file=sys.stderr)
            sys.exit(1)
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(2)

        for remote, local in REMOTE_FILES:
            try:
                await download_file(page, remote, local)
            except Exception as e:
                print(f"[download] ERROR {remote}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
