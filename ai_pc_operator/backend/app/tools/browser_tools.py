"""Browser tools - open, search, click, type, download."""

from __future__ import annotations

import asyncio
import base64
import html
import re
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from typing import Dict, Any, Optional


DEFAULT_IDLE_TIMEOUT_SEC = 120


class BrowserTools:
    """Browser control tools using Playwright."""

    def __init__(self):
        """Initialize browser tools."""
        self.browser = None
        self.page = None
        self._playwright = None
        self.last_used = 0.0
        self.idle_timeout_sec = DEFAULT_IDLE_TIMEOUT_SEC

    async def _ensure_browser(self):
        """Ensure browser is initialized."""
        await self.unload_idle()
        if self.browser is None:
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self.browser = await self._playwright.chromium.launch(
                    headless=False
                )
                self.page = await self.browser.new_page()
            except ImportError:
                raise RuntimeError(
                    "Playwright not installed. Run: pip install playwright"
                )
        self.last_used = time.monotonic()

    async def prepare(self) -> Dict[str, Any]:
        """Warm import Playwright without launching Chromium."""
        try:
            await asyncio.to_thread(__import__, "playwright.async_api")
            return {"status": "success", "prepared": "playwright-import"}
        except ImportError:
            return {
                "status": "skipped",
                "reason": "Playwright is not installed",
            }

    async def unload_idle(self) -> None:
        """Close Chromium after idle timeout to free 400MB+ on small machines."""
        if not self.browser:
            return
        if time.monotonic() - self.last_used >= self.idle_timeout_sec:
            await self.close()

    async def open(self, url: str) -> Dict[str, Any]:
        """Open a URL in browser."""
        url = self._normalize_url(url)
        try:
            await self._ensure_browser()
            await self.page.goto(url)
            self.last_used = time.monotonic()
            return {
                "status": "success",
                "url": url,
                "title": await self.page.title(),
            }
        except Exception as e:
            return await self._open_system_browser(url, error=str(e))

    async def search(self, query: str, engine: str = "google") -> Dict[str, Any]:
        """Search the web."""
        try:
            await self._ensure_browser()

            encoded_query = quote_plus(query)
            if engine == "google":
                url = f"https://www.google.com/search?q={encoded_query}"
            elif engine == "bing":
                url = f"https://www.bing.com/search?q={encoded_query}"
            elif engine == "duckduckgo":
                url = f"https://duckduckgo.com/?q={encoded_query}"
            else:
                url = f"https://www.google.com/search?q={encoded_query}"

            await self.page.goto(url)
            self.last_used = time.monotonic()
            return {
                "status": "success",
                "query": query,
                "engine": engine,
                "url": url,
            }
        except Exception as e:
            encoded_query = quote_plus(query)
            url = f"https://www.google.com/search?q={encoded_query}"
            result = await self._open_system_browser(url, error=str(e))
            result.update({"query": query, "engine": engine})
            return result

    async def click(self, selector: str) -> Dict[str, Any]:
        """Click an element by selector."""
        try:
            await self._ensure_browser()
            await self.page.click(selector)
            self.last_used = time.monotonic()
            return {
                "status": "success",
                "selector": selector,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    def _normalize_url(self, url: str) -> str:
        """Add a scheme when the planner extracted a bare domain."""
        parsed = urlparse(url)
        if parsed.scheme:
            return url
        return f"https://{url}"

    async def _open_system_browser(
        self,
        url: str,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fallback to the OS default browser when Playwright is unavailable."""
        opened = await asyncio.to_thread(webbrowser.open, url)
        if opened:
            response = {
                "status": "success",
                "url": url,
                "mode": "system-browser-fallback",
            }
            if error:
                response["warning"] = (
                    "Playwright browser was unavailable; opened with the "
                    f"system browser instead. Details: {error}"
                )
            return response

        return {
            "status": "failed",
            "url": url,
            "error": error or "System browser refused the URL",
        }

    async def type(self, selector: str, text: str) -> Dict[str, Any]:
        """Type text into an element."""
        try:
            await self._ensure_browser()
            await self.page.fill(selector, text)
            self.last_used = time.monotonic()
            return {
                "status": "success",
                "selector": selector,
                "text": text,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def read(self, selector: str = "body") -> Dict[str, Any]:
        """Read page content."""
        try:
            await self._ensure_browser()
            content = await self.page.text_content(selector)
            self.last_used = time.monotonic()
            return {
                "status": "success",
                "content": content,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def research_collect(
        self,
        query: str,
        max_sites: int = 5,
        save_dir: Optional[str] = None,
        max_chars_per_site: int = 12000,
    ) -> Dict[str, Any]:
        """Search the web, visit result pages, extract visible text, and save a report."""
        max_sites = max(1, min(int(max_sites), 10))
        try:
            await self._ensure_browser()
            links = await self._search_result_links(query, max_sites * 3)
            if not links:
                links = await asyncio.to_thread(self._search_result_links_http, query, max_sites * 3)
            collected = []

            for url in links[:max_sites]:
                try:
                    await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    title = await self.page.title()
                    text = await self.page.text_content("body") or ""
                    text = self._clean_text(text)[:max_chars_per_site]
                    if len(text) < 200:
                        continue
                    collected.append({"url": url, "title": title, "text": text})
                except Exception as exc:
                    collected.append({"url": url, "title": "", "error": str(exc), "text": ""})

            path = await asyncio.to_thread(self._save_research_report, query, collected, save_dir)
            self.last_used = time.monotonic()
            return {
                "status": "success",
                "query": query,
                "visited": len(collected),
                "saved_path": str(path),
                "sources": [
                    {"url": item["url"], "title": item.get("title", ""), "chars": len(item.get("text", ""))}
                    for item in collected
                ],
            }
        except Exception as e:
            return {
                "status": "failed",
                "query": query,
                "error": str(e),
            }

    async def download(self, url: str, filename: Optional[str] = None) -> Dict[str, Any]:
        """Download a file."""
        try:
            import urllib.request
            ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
            DOWNLOAD_DIR = ROOT / "ai_pc_operator" / "data" / "downloads"
            DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

            if not filename:
                filename = url.split("/")[-1]
            filename = self._safe_download_name(filename)
            if self._is_dangerous_download(filename):
                return {
                    "status": "blocked",
                    "url": url,
                    "filename": filename,
                    "reason": "Dangerous executable/script download requires a dedicated approved installer flow.",
                }

            download_path = DOWNLOAD_DIR / filename

            urllib.request.urlretrieve(url, str(download_path))

            return {
                "status": "success",
                "url": url,
                "path": str(download_path),
                "size": download_path.stat().st_size,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    def _safe_download_name(self, filename: str) -> str:
        """Keep browser downloads inside the downloads directory."""
        cleaned = re.sub(r"[^a-zA-Z0-9._ -]", "_", filename).strip(" .")
        return cleaned or "download.bin"

    def _is_dangerous_download(self, filename: str) -> bool:
        """Flag file types that should not be silently downloaded/run."""
        dangerous_extensions = {
            ".exe",
            ".msi",
            ".bat",
            ".cmd",
            ".ps1",
            ".vbs",
            ".js",
            ".jar",
            ".scr",
            ".reg",
        }
        return any(filename.lower().endswith(ext) for ext in dangerous_extensions)

    async def _extract_search_links(self, limit: int, selector: str = "a[href]") -> list[str]:
        """Extract likely organic result links from the search page."""
        hrefs = await self.page.eval_on_selector_all(
            selector,
            """els => els.map(a => a.href).filter(Boolean)""",
        )
        blocked_hosts = {
            "accounts.google.com",
            "support.google.com",
            "policies.google.com",
            "maps.google.com",
            "www.google.com",
            "google.com",
            "www.bing.com",
            "bing.com",
            "duckduckgo.com",
            "www.duckduckgo.com",
        }
        links: list[str] = []
        for href in hrefs:
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"}:
                continue
            if parsed.netloc.lower() in blocked_hosts:
                continue
            if any(part in href.lower() for part in ["/search?", "google.com/preferences"]):
                continue
            if href not in links:
                links.append(href)
            if len(links) >= limit:
                break
        return links

    def _search_result_links_http(self, query: str, limit: int) -> list[str]:
        """HTTP fallback that decodes Bing redirect result URLs."""
        import requests

        response = requests.get(
            f"https://www.bing.com/search?q={quote_plus(query)}",
            headers={"User-Agent": "Mozilla/5.0 Screen-AI"},
            timeout=20,
        )
        response.raise_for_status()
        raw_links = re.findall(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"', response.text)
        links: list[str] = []
        for raw in raw_links:
            href = html.unescape(raw)
            decoded = self._decode_bing_redirect(href)
            if decoded and decoded not in links:
                links.append(decoded)
            if len(links) >= limit:
                break
        return links

    def _decode_bing_redirect(self, href: str) -> str | None:
        parsed = urlparse(href)
        if parsed.netloc.lower() not in {"www.bing.com", "bing.com"}:
            return href if parsed.scheme in {"http", "https"} else None
        match = re.search(r"[?&]u=([^&]+)", href)
        if not match:
            return None
        encoded = match.group(1)
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
            parsed_decoded = urlparse(decoded)
            if parsed_decoded.scheme in {"http", "https"}:
                return decoded
        except Exception:
            return None
        return None

    async def _search_result_links(self, query: str, limit: int) -> list[str]:
        """Try multiple search engines because result markup varies by region/session."""
        engines = [
            (f"https://www.google.com/search?q={quote_plus(query)}", "a:has(h3)"),
            (f"https://www.bing.com/search?q={quote_plus(query)}", "li.b_algo h2 a"),
            (f"https://duckduckgo.com/html/?q={quote_plus(query)}", "a.result__a"),
        ]
        links: list[str] = []
        for url, selector in engines:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            for href in await self._extract_search_links(limit, selector):
                if href not in links:
                    links.append(href)
                if len(links) >= limit:
                    return links
        return links

    def _save_research_report(
        self,
        query: str,
        collected: list[dict[str, Any]],
        save_dir: Optional[str],
    ) -> Path:
        root = Path(__file__).resolve().parent.parent.parent.parent.parent
        base = Path(save_dir).expanduser() if save_dir else root / "ai_pc_operator" / "data" / "research"
        base.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_query = re.sub(r"[^a-zA-Z0-9_-]+", "_", query).strip("_")[:60] or "research"
        path = base / f"research_{safe_query}_{stamp}.txt"
        lines = [
            "Screen-AI Research Report",
            f"Query: {query}",
            f"Created: {datetime.now().isoformat(timespec='seconds')}",
            "",
        ]
        for idx, item in enumerate(collected, start=1):
            lines.extend(
                [
                    "=" * 80,
                    f"Source {idx}: {item.get('title') or '(untitled)'}",
                    f"URL: {item.get('url')}",
                    "",
                    item.get("error") or item.get("text") or "",
                    "",
                ]
            )
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"\r\n?", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    async def close(self) -> Dict[str, Any]:
        """Close browser."""
        try:
            if self.browser:
                await self.browser.close()
            if self._playwright:
                await self._playwright.stop()
                self.browser = None
                self.page = None
                self._playwright = None
                self.last_used = 0.0
            return {"status": "success"}
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }
