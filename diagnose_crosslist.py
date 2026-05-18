"""Diagnostic script: dumps Crosslist page structure so we can fix the scraper selectors."""
from pathlib import Path
from playwright.sync_api import sync_playwright

profile = str(Path("data/browser_profile"))

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        profile, headless=False, viewport={"width": 1280, "height": 900}
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://app.crosslist.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    # Check if login is needed
    url = page.url.lower()
    if "login" in url or "signin" in url or "sign-in" in url:
        print("Login page detected. Log in to Crosslist in the browser window.")
        print("Once you're logged in and can see your listings, come back here.\n")
        input(">>> Press Enter after you've logged in and navigated to your listings... ")
        page.wait_for_timeout(3000)
    else:
        print("Already logged in!")
        input(">>> Press Enter when the page you want to scrape is fully loaded... ")
        page.wait_for_timeout(2000)

    html = page.content()
    Path("data/crosslist_dump.html").write_text(html, encoding="utf-8")
    print(f"Saved {len(html)} chars to data/crosslist_dump.html")
    print(f"Current URL: {page.url}")
    print()

    summary = page.evaluate(
        """() => {
            const els = document.querySelectorAll('table, [class*="list"], [class*="card"], [class*="item"], [class*="product"], [class*="grid"]');
            return Array.from(els).slice(0, 20).map(e =>
                e.tagName + "." + e.className.split(" ").slice(0, 3).join(".") + " children:" + e.children.length
            );
        }"""
    )
    print("=== Page structure elements ===")
    for s in summary:
        print(" ", s)

    print()
    print("=== Links in nav/sidebar ===")
    nav_links = page.evaluate(
        """() => {
            const links = document.querySelectorAll('nav a, [class*="sidebar"] a, [class*="nav"] a, [class*="menu"] a');
            return Array.from(links).slice(0, 15).map(a => a.textContent.trim().substring(0, 40) + " -> " + (a.getAttribute('href') || ''));
        }"""
    )
    for link in nav_links:
        print(" ", link)

    ctx.close()
