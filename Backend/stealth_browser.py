"""
stealth_browser.py — Patchright Stealth Browser Module v1

Protected-site compatibility layer for Bridge IDE browser automation.
Tested: bot.sannysoft.com 57/57 GREEN (V4 config).

Usage (context manager — auto-cleanup):
    from stealth_browser import create_stealth_browser, create_stealth_page, stealth_goto

    async with create_stealth_browser() as browser:
        page = await create_stealth_page(browser)
        await stealth_goto(page, "https://target.com")

Usage (long-lived — for MCP sessions spanning multiple tool calls):
    from stealth_browser import start_stealth_browser, create_stealth_page, stealth_goto

    pw, browser = await start_stealth_browser()
    page = await create_stealth_page(browser)
    await stealth_goto(page, "https://target.com")
    # ... later ...
    await browser.close()
    await pw.stop()

Patches:
    1. --disable-blink-features=AutomationControlled → webdriver=false
    2. CDP Emulation.setUserAgentOverride → clean UA + language + platform
    3. CDP Page.addScriptToEvaluateOnNewDocument → performance.memory spoof
    4. --headless=new → Chrome New Headless Mode

Requirements: pip install patchright
"""

from contextlib import asynccontextmanager
from patchright.async_api import async_playwright

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

_MEMORY_SPOOF = """\
if (!performance.memory) {
    Object.defineProperty(performance, 'memory', {
        get: () => ({
            jsHeapSizeLimit: 2172649472,
            totalJSHeapSize: 35839892,
            usedJSHeapSize: 23292036
        })
    });
}"""


@asynccontextmanager
async def create_stealth_browser(
    headless: bool = True,
    channel: str = "chrome",
    proxy: str | None = None,
):
    """Create a stealth Patchright browser instance.

    Args:
        headless: Use headless mode (default True).
        channel: Browser channel ("chrome" for system Chrome).
        proxy: Optional proxy URL (socks5://host:port or http://host:port).

    Yields:
        Browser instance. Use create_stealth_page() to get pages.
    """
    async with async_playwright() as pw:
        launch_kwargs = _build_launch_kwargs(headless, channel, proxy)
        browser = await pw.chromium.launch(**launch_kwargs)

        try:
            yield browser
        finally:
            await browser.close()


def _build_launch_kwargs(headless, channel, proxy):
    """Build launch kwargs shared by both browser creation functions."""
    args = ["--disable-blink-features=AutomationControlled"]
    if headless:
        args.append("--headless=new")
    launch_kwargs = {
        "headless": False,  # Always False. --headless=new in args controls headless.
        "channel": channel,
        "args": args,
    }
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    return launch_kwargs


async def start_stealth_browser(
    headless: bool = True,
    channel: str = "chrome",
    proxy: str | None = None,
):
    """Start stealth browser without context manager (for long-lived sessions).

    Use this for MCP sessions that span multiple tool calls where a context
    manager would close the browser between calls.

    Args:
        headless: Use headless mode (default True).
        channel: Browser channel ("chrome" for system Chrome).
        proxy: Optional proxy URL (socks5://host:port or http://host:port).

    Returns:
        (pw, browser) tuple. Caller must close:
            await browser.close()
            await pw.stop()
    """
    pw = await async_playwright().start()
    try:
        launch_kwargs = _build_launch_kwargs(headless, channel, proxy)
        browser = await pw.chromium.launch(**launch_kwargs)
    except Exception:
        await pw.stop()
        raise
    return pw, browser


async def create_stealth_page(browser, user_agent: str = DEFAULT_USER_AGENT):
    """Create a new page with stealth patches pre-applied via CDP.

    The CDP patches are set up on the browser context so they persist
    across all navigations on this page.

    Args:
        browser: Browser from create_stealth_browser().
        user_agent: User-Agent string to use.

    Returns:
        Page with stealth patches ready. Use stealth_goto() for first navigation.
    """
    page = await browser.new_page()
    cdp = await page.context.new_cdp_session(page)

    await cdp.send("Emulation.setUserAgentOverride", {
        "userAgent": user_agent,
        "acceptLanguage": "en-US,en;q=0.9,de;q=0.8",
        "platform": "Linux x86_64",
    })
    await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
        "source": _MEMORY_SPOOF,
    })

    return page


async def stealth_goto(page, url: str, timeout: int = 30000):
    """Navigate with stealth. Handles navigate-patch-reload pattern.

    On first call, navigates then reloads to activate CDP patches
    (workaround for DNS issues when patches are applied before navigation).

    Args:
        page: Page from create_stealth_page().
        url: Target URL.
        timeout: Navigation timeout in ms.
    """
    await page.goto(url, timeout=timeout)
    await page.reload(timeout=timeout)
