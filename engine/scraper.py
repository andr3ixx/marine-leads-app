"""
Playwright-based scraper.

Captures a desktop screenshot and a mobile-viewport screenshot of the
homepage (per the brief's visual-review priority), plus crawls a handful of
likely internal pages (contact/about/team/etc.) purely for contact discovery
— those pages don't get screenshotted or AI-reviewed, just scanned for emails
/phones/socials, to keep this cheap and fast.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from playwright.async_api import Browser, TimeoutError as PlaywrightTimeoutError

from .contacts import ContactBundle, extract_contacts_from_html, find_internal_links, merge_bundles

NAV_TIMEOUT_MS = 15_000
MAX_CONTACT_PAGES = 3  # beyond the homepage

DESKTOP_VIEWPORT = {"width": 1280, "height": 800}
MOBILE_VIEWPORT = {"width": 390, "height": 844}  # iPhone-ish

USER_AGENT_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
USER_AGENT_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)


@dataclass
class ScrapeResult:
    html: str = ""
    desktop_screenshot: Optional[Path] = None
    mobile_screenshot: Optional[Path] = None
    contacts: ContactBundle = field(default_factory=ContactBundle)
    error: str = ""

    @property
    def succeeded(self) -> bool:
        return bool(self.html) and not self.error


async def _fetch_page(browser: Browser, url: str, viewport: dict, user_agent: str, timeout_ms: int = NAV_TIMEOUT_MS):
    ctx = await browser.new_context(viewport=viewport, user_agent=user_agent)
    page = await ctx.new_page()
    try:
        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        html = await page.content()
        return page, ctx, html, None
    except PlaywrightTimeoutError:
        await ctx.close()
        return None, None, "", f"Timeout after {timeout_ms // 1000}s navigating to {url}"
    except Exception as exc:
        await ctx.close()
        return None, None, "", f"Scrape failed: {exc}"


async def scrape_lead(
    browser: Browser,
    url: str,
    desktop_shot_path: Path,
    mobile_shot_path: Path,
    crawl_contact_pages: bool = True,
) -> ScrapeResult:
    result = ScrapeResult()

    # ---- Desktop pass: main HTML + desktop screenshot ----
    page, ctx, html, err = await _fetch_page(browser, url, DESKTOP_VIEWPORT, USER_AGENT_DESKTOP)
    if err:
        result.error = err
        return result

    try:
        await page.screenshot(path=str(desktop_shot_path), full_page=False)
        result.desktop_screenshot = desktop_shot_path
        result.html = html
    finally:
        await ctx.close()

    home_bundle = extract_contacts_from_html(html, url)
    bundles = [home_bundle]

    # ---- Mobile pass: just the screenshot, same URL ----
    page_m, ctx_m, _html_m, err_m = await _fetch_page(browser, url, MOBILE_VIEWPORT, USER_AGENT_MOBILE)
    if not err_m:
        try:
            await page_m.screenshot(path=str(mobile_shot_path), full_page=False)
            result.mobile_screenshot = mobile_shot_path
        finally:
            await ctx_m.close()
    # if mobile pass fails, we just proceed without a mobile screenshot — not fatal

    # ---- Light crawl of likely contact pages (HTML only, no screenshots) ----
    if crawl_contact_pages:
        internal_links = find_internal_links(html, url, max_links=MAX_CONTACT_PAGES)
        for link in internal_links:
            page_c, ctx_c, html_c, err_c = await _fetch_page(
                browser, link, DESKTOP_VIEWPORT, USER_AGENT_DESKTOP, timeout_ms=10_000
            )
            if err_c:
                continue
            try:
                bundles.append(extract_contacts_from_html(html_c, link))
            finally:
                await ctx_c.close()

    result.contacts = merge_bundles(bundles)
    return result
