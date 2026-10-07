"""Upload eval_sort_smolvla.py to the remote JupyterLab instance via Contents API.

Usage:
    python scripts/upload_eval_sort.py
"""
import asyncio
import sys
import base64
from pathlib import Path

from playwright.async_api import async_playwright

JUPYTER_URL = "https://radeon-global.anruicloud.com/instances/u-13944-c577fd88/lab"
LOCAL_FILE = Path(__file__).resolve().parent.parent / "remote_files" / "eval_sort_smolvla.py"
REMOTE_PATH = "/workspace/franka_fruit_pick_demo/franka_fruit_pick/eval_sort_smolvla.py"


async def upload(page, remote_path: str, content: str) -> dict:
    """Upload a file via JupyterLab Contents API."""
    base_url = page.url.split("/lab")[0]
    # Contents API expects path relative to JupyterLab root_dir (=/workspace), no leading slash
    api_path = remote_path.lstrip("/")
    if api_path.startswith("workspace/"):
        api_path = api_path[len("workspace/"):]
    url = f"{base_url}/api/contents/{api_path}"

    body = {
        "type": "file",
        "format": "text",
        "content": content,
    }

    result = await page.evaluate("""
        async (params) => {
            const resp = await fetch(params.url, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                body: JSON.stringify(params.body),
            });
            const text = await resp.text();
            return {status: resp.status, body: text};
        }
    """, {"url": url, "body": body})
    return result


async def main():
    content = LOCAL_FILE.read_text(encoding="utf-8")
    print(f"[local] read {len(content)} bytes from {LOCAL_FILE}")

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

        result = await upload(page, REMOTE_PATH, content)
        print(f"[upload] HTTP {result['status']}")
        if result['status'] >= 400:
            print(f"[upload] error body: {result['body'][:500]}")
            sys.exit(2)
        print(f"[upload] OK -> {REMOTE_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
