"""
Capture screenshots of the Gradio UI for the demo PPT.
Properly clicks '开始分析' and '生成管理层报告' before capturing.
"""

import asyncio
import os
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:7862"
OUTPUT_DIR = "/workspace/persistence/AMD-hacthon/amd-inventory-agent V1.1/docs/demo_video_materials/slides/demo_video_assets"
os.makedirs(OUTPUT_DIR, exist_ok=True)


async def switch_tab(page, label):
    """Switch Gradio tab via role=tab button."""
    tab = page.locator('button[role="tab"]').filter(has_text=label)
    count = await tab.count()
    if count > 0:
        await tab.first.click(force=True)
        await page.wait_for_timeout(2000)
        return True
    print(f"  ⚠️ Tab '{label}' not found")
    return False


async def capture():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2,
            locale="zh-CN"
        )
        page = await context.new_page()

        print("Navigating to UI...")
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # ═══════════════════════════════════════════
        # Step 1: Click "开始分析" on 指挥舱 tab
        # ═══════════════════════════════════════════
        print("\n[Step 1] Clicking '开始分析'...")
        start_btn = page.locator("button").filter(has_text="开始分析")
        count = await start_btn.count()
        print(f"  Found {count} '开始分析' buttons")
        if count > 0:
            await start_btn.first.click(force=True)
            print("  Waiting 20s for analysis to complete...")
            await page.wait_for_timeout(20000)
            print("  ✅ Analysis should be done")
        else:
            print("  ⚠️ '开始分析' button not found")

        # ═══════════════════════════════════════════
        # Screenshot 1: 指挥舱
        # ═══════════════════════════════════════════
        print("\n[Screenshot 1] 指挥舱...")
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "slide_01_command_center.png"),
            full_page=True
        )
        sz = os.path.getsize(os.path.join(OUTPUT_DIR, "slide_01_command_center.png"))
        print(f"  ✅ slide_01_command_center.png ({sz//1024}KB)")

        # Crop: core metrics area
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "crop_core_metrics.png"),
            clip={"x": 50, "y": 300, "width": 1820, "height": 600}
        )
        print("  ✅ crop_core_metrics.png")

        # ═══════════════════════════════════════════
        # Screenshot 2: 风险可视化
        # ═══════════════════════════════════════════
        print("\n[Screenshot 2] 风险可视化...")
        await switch_tab(page, "风险可视化")
        await page.wait_for_timeout(3000)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "slide_04_risk_visualization.png"),
            full_page=True
        )
        sz = os.path.getsize(os.path.join(OUTPUT_DIR, "slide_04_risk_visualization.png"))
        print(f"  ✅ slide_04_risk_visualization.png ({sz//1024}KB)")

        # Crop: risk chart area
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "crop_risk_chart.png"),
            clip={"x": 50, "y": 200, "width": 1820, "height": 700}
        )
        print("  ✅ crop_risk_chart.png")

        # ═══════════════════════════════════════════
        # Screenshot 3: 审计追踪
        # ═══════════════════════════════════════════
        print("\n[Screenshot 3] 审计追踪...")
        await switch_tab(page, "审计追踪")
        await page.wait_for_timeout(3000)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "slide_05_audit_trace.png"),
            full_page=True
        )
        sz = os.path.getsize(os.path.join(OUTPUT_DIR, "slide_05_audit_trace.png"))
        print(f"  ✅ slide_05_audit_trace.png ({sz//1024}KB)")

        # Crop: quality gate area (middle-lower section)
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "crop_quality_gate.png"),
            clip={"x": 50, "y": 600, "width": 1820, "height": 500}
        )
        print("  ✅ crop_quality_gate.png")

        # ═══════════════════════════════════════════
        # Screenshot 4: 管理层报告 (with generation)
        # ═══════════════════════════════════════════
        print("\n[Screenshot 4] 管理层报告...")
        await switch_tab(page, "管理层报告")
        await page.wait_for_timeout(2000)

        # Click "生成管理层报告"
        print("  Clicking '生成管理层报告'...")
        gen_btn = page.locator("button").filter(has_text="生成管理层报告")
        if await gen_btn.count() > 0:
            await gen_btn.first.click(force=True)
            print("  Waiting 15s for report to generate...")
            await page.wait_for_timeout(15000)
            print("  ✅ Report should be generated")
        else:
            print("  ⚠️ Generate button not found")

        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "slide_06_management_report.png"),
            full_page=True
        )
        sz = os.path.getsize(os.path.join(OUTPUT_DIR, "slide_06_management_report.png"))
        print(f"  ✅ slide_06_management_report.png ({sz//1024}KB)")

        # Crop: report output area
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "crop_management_summary.png"),
            clip={"x": 50, "y": 700, "width": 1820, "height": 500}
        )
        print("  ✅ crop_management_summary.png")

        # ═══════════════════════════════════════════
        # Screenshot 5: 追问 (with Q&A)
        # ═══════════════════════════════════════════
        print("\n[Screenshot 5] 追问...")
        await switch_tab(page, "追问")
        await page.wait_for_timeout(2000)

        # Find text input and send a question
        print("  Sending question...")
        try:
            # Find the visible chat textarea by placeholder
            tb = page.get_by_placeholder("输入你的问题...")
            if await tb.count() > 0:
                await tb.fill("这次差异率是多少？哪个品类最异常？")
                await page.wait_for_timeout(500)
                send_btn = page.locator("button").filter(has_text="发送")
                if await send_btn.count() > 0:
                    await send_btn.first.click(force=True)
                    print("  Waiting 8s for answer...")
                    await page.wait_for_timeout(8000)
                    print("  ✅ Answer received")
        except Exception as e:
            print(f"  ⚠️ Could not send question: {e}")

        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "slide_07_followup_qa.png"),
            full_page=True
        )
        sz = os.path.getsize(os.path.join(OUTPUT_DIR, "slide_07_followup_qa.png"))
        print(f"  ✅ slide_07_followup_qa.png ({sz//1024}KB)")

        # Crop: chat area
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "crop_followup_answer.png"),
            clip={"x": 50, "y": 200, "width": 1820, "height": 600}
        )
        print("  ✅ crop_followup_answer.png")

        # ═══════════════════════════════════════════
        # Screenshot 6: 关于
        # ═══════════════════════════════════════════
        print("\n[Screenshot 6] 关于...")
        await switch_tab(page, "关于")
        await page.wait_for_timeout(2000)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)
        await page.screenshot(
            path=os.path.join(OUTPUT_DIR, "slide_02_about_agent.png"),
            full_page=True
        )
        sz = os.path.getsize(os.path.join(OUTPUT_DIR, "slide_02_about_agent.png"))
        print(f"  ✅ slide_02_about_agent.png ({sz//1024}KB)")

        print("\n" + "=" * 50)
        print("✅ ALL SCREENSHOTS CAPTURED")
        print("=" * 50)

        # Clean up old non-numbered files from previous runs
        for f in os.listdir(OUTPUT_DIR):
            if f.startswith("slide_") and not any(f.startswith(f"slide_{i:02d}_") for i in range(1, 10)):
                os.remove(os.path.join(OUTPUT_DIR, f))
                print(f"  Removed old: {f}")

        # List final output
        for f in sorted(os.listdir(OUTPUT_DIR)):
            fpath = os.path.join(OUTPUT_DIR, f)
            print(f"  {f:40s} {os.path.getsize(fpath)//1024:>4d}KB")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(capture())
