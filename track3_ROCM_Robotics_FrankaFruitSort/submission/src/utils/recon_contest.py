"""Recon the Radeon Cloud contest page using the already-logged-in Chrome.

Navigates to /contest and dumps page text + screenshots.
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

CONTEST_URL = "https://radeon-global.anruicloud.com/contest"
OUT_DIR = Path(r"d:\APPs\amdRadeon\screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()

        # Find an existing Radeon Cloud page, or open one
        page = None
        for pg in context.pages:
            url = pg.url or ""
            if "radeon-global.anruicloud.com" in url:
                page = pg
                print(f"[connect] reuse page: {url}", file=sys.stderr)
                break

        if page is None:
            page = await context.new_page()
            await page.goto("https://radeon-global.anruicloud.com/", wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)
            print(f"[connect] new page: {page.url}", file=sys.stderr)

        # Try clicking the Contest nav tab first
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Dump current page text to see nav options
        text = await page.evaluate("() => document.body.innerText")
        print("=== CURRENT PAGE TEXT (first 2000 chars) ===")
        print(text[:2000])
        print("=== END ===")

        # Try to find and click Contest tab
        clicked = await page.evaluate("""
            () => {
                const els = Array.from(document.querySelectorAll('a, button, .tag-pill, [role="tab"], [class*="nav"]'));
                for (const el of els) {
                    if (el.textContent && el.textContent.trim() === 'Contest') {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        print(f"[contest] clicked Contest tab: {clicked}", file=sys.stderr)
        await asyncio.sleep(3)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Also try direct URL
        if "/contest" not in (page.url or ""):
            await page.goto(CONTEST_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

        print(f"[contest] current url: {page.url}", file=sys.stderr)

        # Screenshot
        await page.screenshot(path=str(OUT_DIR / "contest_page.png"), full_page=True)
        print(f"[screenshot] saved to {OUT_DIR / 'contest_page.png'}")

        # Dump contest page text
        text = await page.evaluate("() => document.body.innerText")
        print("=== CONTEST PAGE TEXT ===")
        print(text[:8000])
        print("=== END ===")

        # Look for links to GitHub / submission repos
        links = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]')).map(a => ({text: a.textContent.trim().slice(0,80), href: a.href})).filter(x => x.href.includes('github') || x.href.includes('submit') || x.href.includes('rule') || x.href.includes('track'))
        """)
        print("=== RELEVANT LINKS ===")
        for l in links[:30]:
            print(f"  {l['text']}: {l['href']}")
        print("=== END ===")


if __name__ == "__main__":
    asyncio.run(main())
