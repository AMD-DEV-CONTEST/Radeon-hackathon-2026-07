# -*- coding: utf-8 -*-
"""用 playwright headless 驱动真实 UI，录制演示视频帧序列。

用法：python tools/capture_demo.py [--out demo_frames] [--width 1280 --height 800]
输出：demo_frames/frame_0000.png ...（按时间顺序），之后用 ffmpeg 拼成视频。
"""
import argparse
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7860"


def shot(page, out, name, hold_s=2.0):
    """截图一帧并保持 hold_s 秒（模拟镜头停留）。"""
    page.screenshot(path=os.path.join(out, name), type="png")
    print(f"  shot {name}")
    time.sleep(hold_s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo_frames")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--sample-interval", type=float, default=2.0,
                    help="多 Agent 运行期间每多少秒截一帧")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    idx = [0]

    def fname():
        idx[0] += 1
        return f"frame_{idx[0]:05d}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # ---------------- 镜头 1：开场（空状态） ----------------
        print("[场景1] 开场空状态")
        shot(page, args.out, fname(), hold_s=3.5)

        # ---------------- 镜头 2：单 Agent 问答 ----------------
        print("[场景2] 单 Agent 问答")
        page.fill("textarea", "我的项目用了什么技术栈？")
        page.evaluate("() => { document.querySelector('.send-btn').click(); }")
        # 等待回答完成：轮询 .md.stream 长度稳定
        last_len, stable = -1, 0
        t0 = time.time()
        while time.time() - t0 < 240:
            time.sleep(args.sample_interval)
            ln = page.evaluate("() => { const m = document.querySelector('.msg.assistant:last-of-type .md.stream, .msg.assistant .md.stream'); return m ? m.textContent.length : 0; }")
            if ln == last_len:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
                last_len = ln
            shot(page, args.out, fname(), hold_s=0.1)
        shot(page, args.out, fname(), hold_s=2.5)

        # ---------------- 镜头 3：多 Agent 并行 ----------------
        print("[场景3] 多 Agent 并行")
        page.evaluate("() => { const nb = document.querySelector('.new-chat-btn'); if (nb) nb.click(); }")
        time.sleep(1)
        page.fill("textarea", "分析这个项目的技术栈、优化点和部署方式")
        page.evaluate("() => { const m = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('多 Agent')); if (m) m.click(); document.querySelector('.send-btn').click(); }")
        # 持续采样直到完成（.status-row 消失 or answer 稳定）
        last_len, stable = -1, 0
        t0 = time.time()
        frames = 0
        while time.time() - t0 < 420:
            time.sleep(args.sample_interval)
            ln = page.evaluate("() => { const m = document.querySelector('.msg.assistant:last-of-type .md.stream'); return m ? m.textContent.length : -1; }")
            done = page.evaluate("() => { const msgs = document.querySelectorAll('.msg.assistant'); const a = msgs[msgs.length-1]; return a ? !a.querySelector('.status-row') : false; }")
            if ln == last_len and done:
                stable += 1
                if stable >= 2:
                    break
            elif done:
                last_len = ln
                stable = 0
            else:
                stable = 0
                last_len = ln
            frames += 1
            shot(page, args.out, fname(), hold_s=0.1)
        shot(page, args.out, fname(), hold_s=3.0)

        # ---------------- 镜头 4：GPU 监控面板 ----------------
        print("[场景4] GPU 监控")
        page.evaluate("() => { const t = Array.from(document.querySelectorAll('.panel-tab')).find(x => x.textContent.includes('GPU')); if (t) t.click(); }")
        shot(page, args.out, fname(), hold_s=2.5)
        shot(page, args.out, fname(), hold_s=2.5)

        # ---------------- 镜头 5：来源抽屉 ----------------
        print("[场景5] 来源抽屉")
        page.evaluate("() => { const chip = document.querySelector('.cite-chip'); if (chip) chip.click(); }")
        shot(page, args.out, fname(), hold_s=3.0)
        page.evaluate("() => { const c = document.getElementById('doc-drawer-mask'); if (c) c.classList.add('hidden'); }")

        browser.close()

    print(f"=== 完成：{idx[0]} 帧 -> {args.out}/ ===")


if __name__ == "__main__":
    main()
