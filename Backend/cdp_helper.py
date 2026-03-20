#!/usr/bin/env python3
"""CDP Helper — Direct browser control via Chrome DevTools Protocol.

Usage from any agent:
    from cdp_helper import CDPBrowser

    async with CDPBrowser() as browser:
        tabs = await browser.list_tabs()
        page = await browser.get_page(0)
        await page.goto("https://example.com")
        await page.screenshot(path="/tmp/screenshot.png")
        content = await page.content()
"""
import asyncio
import json

from playwright.async_api import async_playwright, Browser, Page


class CDPBrowser:
    """Context manager for CDP connection to the owner's Chrome."""

    def __init__(self, port: int = 9222):
        self.port = port
        self._pw = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> "CDPBrowser":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(
            f"http://localhost:{self.port}"
        )
        return self

    async def __aexit__(self, *args):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def list_tabs(self) -> list[dict[str, str]]:
        """List all open tabs."""
        tabs = []
        for ctx in self._browser.contexts:
            for page in ctx.pages:
                tabs.append({"url": page.url, "title": await page.title()})
        return tabs

    async def get_page(self, index: int = 0) -> Page:
        """Get page by index (across all contexts)."""
        pages = []
        for ctx in self._browser.contexts:
            pages.extend(ctx.pages)
        return pages[index]

    async def new_tab(self, url: str = "about:blank") -> Page:
        """Open a new tab."""
        ctx = self._browser.contexts[0]
        page = await ctx.new_page()
        if url != "about:blank":
            await page.goto(url, wait_until="domcontentloaded")
        return page


async def check_cdp(port: int = 9222) -> bool:
    """Check if CDP is available."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://localhost:{port}/json/version")
            data = resp.json()
            print(f"Chrome CDP active: {data.get('Browser', 'unknown')}")
            return True
    except Exception:
        print(f"CDP not available on port {port}")
        return False


if __name__ == "__main__":
    asyncio.run(check_cdp())
