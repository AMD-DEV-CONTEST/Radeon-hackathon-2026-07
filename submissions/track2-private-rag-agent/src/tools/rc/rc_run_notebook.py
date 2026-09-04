# -*- coding: utf-8 -*-
"""用 playwright 在 RC JupyterLab 中执行笔记本（Run All）。

更可靠的执行方式：
1. 聚焦第一个 cell 的 CodeMirror 编辑器
2. 打开命令面板 (Ctrl+Shift+P) → 输入 "Run All" → Enter
3. 兜底：逐格 Shift+Enter（聚焦编辑器后）

用法：python tools/rc/rc_run_notebook.py --notebook private-rag-agent-benchmark.ipynb --wait 420
"""
import argparse
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

INST = "https://developer.amd.com.cn/radeon/instances/u-7102-1179e4d5"
TOKEN = "amd-oneclick"
COOKIE_PATH = "tools/rc/rc_cookies.txt"


def session_value():
    raw = open(COOKIE_PATH, encoding="utf-8").read().strip()
    return raw.split("session=")[1].split(";")[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--notebook", default="private-rag-agent-benchmark.ipynb")
    ap.add_argument("--out-png", default="tools/rc/rc_notebook_result.png")
    ap.add_argument("--wait", type=int, default=420)
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1500, "height": 950})
        ctx.add_cookies([{"name": "session", "value": session_value(),
                          "domain": "developer.amd.com.cn", "path": "/"}])
        page = ctx.new_page()
        page.set_default_timeout(20000)
        page.goto(f"{INST}/lab/tree/{args.notebook}?token={TOKEN}",
                  wait_until="domcontentloaded", timeout=60000)
        time.sleep(10)

        # 等待 notebook 面板 + 编辑器
        for _ in range(30):
            try:
                page.wait_for_selector(".jp-NotebookPanel", timeout=3000)
                time.sleep(2)
                ed = page.locator(".jp-CodeMirrorEditor, .cm-content, .jp-Editor").first
                if ed.count() > 0:
                    print("editor found")
                    break
            except Exception:
                time.sleep(3)
        page.screenshot(path="tools/rc/rc_lab_loaded.png")

        # 聚焦第一个 cell 的编辑器
        focused = False
        for sel in [".jp-CodeMirrorEditor", ".cm-content", ".jp-Editor",
                    ".jp-Cell-inputWrapper .jp-Editor"]:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.click()
                    focused = True
                    print("focused:", sel)
                    break
            except Exception:
                continue
        if not focused:
            page.locator(".jp-Cell").first.click()
            print("clicked first cell")

        # 命令面板 → Run All Cells
        ran = False
        try:
            page.keyboard.press("Control+Shift+P")
            time.sleep(1.5)
            page.keyboard.type("run all", delay=50)
            time.sleep(1.5)
            # 选第一个匹配的命令
            page.keyboard.press("Enter")
            time.sleep(1)
            print("command palette executed (run all)")
            ran = True
        except Exception as e:
            print("command palette failed:", str(e)[:100])

        if not ran:
            # 兜底：逐格执行
            print("fallback: per-cell Shift+Enter")
            n = page.locator(".jp-Cell").count()
            for i in range(n):
                try:
                    page.locator(".jp-Cell").nth(i).locator(".cm-content, .jp-CodeMirrorEditor").first.click()
                    page.keyboard.press("Shift+Enter")
                    time.sleep(2)
                except Exception:
                    page.locator(".jp-Cell").nth(i).click()
                    page.keyboard.press("Shift+Enter")
                    time.sleep(2)

        # 等待执行（轮询最后一个 cell 的输出）
        print("waiting for execution up to", args.wait, "s...")
        waited = 0
        while waited < args.wait:
            time.sleep(15)
            waited += 15
            try:
                # JupyterLab 运行指示：每个 running cell 有灰色播放三角
                busy = page.locator(".jp-Notebook-running, [class*=running], .jp-mod-running")
                has_busy = busy.count() > 0
                outs = page.locator(".jp-OutputArea-output, .jp-OutputArea-stdout")
                print(f"  waited {waited}s: outputs={outs.count()} busy={has_busy}")
                if outs.count() > 0 and not has_busy:
                    time.sleep(5)
                    break
                if waited >= 90 and outs.count() > 0:
                    break
            except Exception:
                pass
        page.screenshot(path=args.out_png)
        print("done; screenshot:", args.out_png)
        browser.close()


if __name__ == "__main__":
    main()
