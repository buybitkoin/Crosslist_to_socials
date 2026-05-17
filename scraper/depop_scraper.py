import json
import re
import time
from datetime import datetime
from pathlib import Path

from scraper.models import DepopListing


class CrosslistScraper:
    """Scrapes listings from Crosslist dashboard using a persistent browser session.

    First run requires manual login — subsequent runs reuse the saved session cookies.
    Pulls listings from all connected marketplaces (Depop, eBay, Poshmark, etc.).
    """

    DASHBOARD_URL = "https://app.crosslist.com"

    def __init__(self, profile_dir: str | None = None):
        self.profile_dir = profile_dir or str(
            Path(__file__).parent.parent / "data" / "browser_profile"
        )

    def scrape_shop(self) -> list[DepopListing]:
        """Scrape all listings from the Crosslist dashboard."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("Error: playwright required. Run: pip install playwright && python -m playwright install chromium")
            return []

        listings = []
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                self.profile_dir,
                headless=False,
                viewport={"width": 1280, "height": 900},
            )
            page = context.pages[0] if context.pages else context.new_page()

            # Navigate to dashboard
            page.goto(self.DASHBOARD_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # Check if we need to log in
            if self._needs_login(page):
                print("\n[!] Please log in to Crosslist in the browser window.")
                print("    Waiting up to 120 seconds...")
                if not self._wait_for_login(page, timeout=120):
                    print("[!] Login timeout. Run again after logging in (session will be saved).")
                    context.close()
                    return []

            # Navigate to the listings/inventory page
            page.wait_for_timeout(2000)
            listings_url = self._find_listings_page(page)
            if listings_url and listings_url != page.url:
                page.goto(listings_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

            # Scrape listings from the page
            listings = self._extract_listings(page)

            # Scroll to load more if the page uses infinite scroll or pagination
            more = self._load_more_listings(page)
            listings.extend(more)

            # Deduplicate
            seen = set()
            unique = []
            for listing in listings:
                if listing.id not in seen:
                    seen.add(listing.id)
                    unique.append(listing)

            context.close()

        return unique

    def _needs_login(self, page) -> bool:
        """Check if we're on a login page."""
        url = page.url.lower()
        if "login" in url or "signin" in url or "sign-in" in url:
            return True
        content = page.content()[:2000].lower()
        return "log in" in content and "password" in content

    def _wait_for_login(self, page, timeout: int = 120) -> bool:
        """Wait for the user to complete login."""
        for _ in range(timeout):
            if not self._needs_login(page):
                page.wait_for_timeout(3000)
                return True
            time.sleep(1)
        return False

    def _find_listings_page(self, page) -> str | None:
        """Find the URL for the listings/inventory page."""
        # Try common Crosslist navigation patterns
        nav_link = page.evaluate("""
            () => {
                const selectors = [
                    'a[href*="listing"]',
                    'a[href*="inventory"]',
                    'a[href*="product"]',
                    'a[href*="closet"]',
                    'a[href*="items"]',
                ];
                for (const sel of selectors) {
                    const link = document.querySelector(sel);
                    if (link) return link.getAttribute('href');
                }
                // Try text content
                const allLinks = document.querySelectorAll('nav a, [class*="sidebar"] a, [class*="nav"] a');
                for (const a of allLinks) {
                    const text = a.textContent.toLowerCase().trim();
                    if (text.includes('listing') || text.includes('inventory') || text.includes('closet')) {
                        return a.getAttribute('href');
                    }
                }
                return null;
            }
        """)
        if nav_link:
            if nav_link.startswith("/"):
                return f"{self.DASHBOARD_URL}{nav_link}"
            elif nav_link.startswith("http"):
                return nav_link
        return None

    def _extract_listings(self, page) -> list[DepopListing]:
        """Extract listing data from the current page."""
        # Try multiple extraction strategies
        listings = self._try_table_extraction(page)
        if listings:
            return listings

        listings = self._try_card_extraction(page)
        if listings:
            return listings

        listings = self._try_generic_extraction(page)
        return listings

    def _try_table_extraction(self, page) -> list[DepopListing]:
        """Extract from a table-based layout."""
        items = page.evaluate("""
            () => {
                const rows = document.querySelectorAll('table tbody tr, [class*="table"] [class*="row"]:not(:first-child)');
                if (rows.length === 0) return [];

                return Array.from(rows).map(row => {
                    const img = row.querySelector('img');
                    const links = row.querySelectorAll('a[href]');
                    const cells = row.querySelectorAll('td, [class*="cell"]');
                    const text = row.textContent;

                    // Try to find price
                    const priceMatch = text.match(/[$£€]\\s*([\\d,.]+)/);

                    // Try to find title from first text-heavy cell or link
                    let title = '';
                    for (const link of links) {
                        const lt = link.textContent.trim();
                        if (lt.length > 5 && lt.length < 200) { title = lt; break; }
                    }
                    if (!title) {
                        for (const cell of cells) {
                            const ct = cell.textContent.trim();
                            if (ct.length > 5 && ct.length < 200 && !ct.match(/^[$£€]/)) { title = ct; break; }
                        }
                    }

                    return {
                        title: title.substring(0, 100),
                        image: img ? (img.src || img.dataset.src || '') : '',
                        price: priceMatch ? priceMatch[1] : '0',
                        link: links.length > 0 ? links[0].getAttribute('href') : '',
                        text: text.substring(0, 300)
                    };
                }).filter(item => item.title || item.image);
            }
        """)
        return self._items_to_listings(items)

    def _try_card_extraction(self, page) -> list[DepopListing]:
        """Extract from a card/grid layout."""
        items = page.evaluate("""
            () => {
                const selectors = [
                    '[class*="listing"]',
                    '[class*="product"]',
                    '[class*="item-card"]',
                    '[class*="ProductCard"]',
                    '[class*="inventory-item"]',
                    '[data-testid*="listing"]',
                    '[data-testid*="product"]',
                ];

                let cards = [];
                for (const sel of selectors) {
                    cards = document.querySelectorAll(sel);
                    if (cards.length > 1) break;
                }
                if (cards.length <= 1) return [];

                return Array.from(cards).map(card => {
                    const img = card.querySelector('img');
                    const link = card.querySelector('a[href]');
                    const text = card.textContent;
                    const priceMatch = text.match(/[$£€]\\s*([\\d,.]+)/);

                    // Find title-like text
                    const titleEl = card.querySelector('h2, h3, h4, [class*="title"], [class*="name"]');
                    let title = titleEl ? titleEl.textContent.trim() : '';
                    if (!title && link) title = link.textContent.trim();
                    if (!title) title = text.trim().split('\\n')[0];

                    return {
                        title: title.substring(0, 100),
                        image: img ? (img.src || img.dataset.src || '') : '',
                        price: priceMatch ? priceMatch[1] : '0',
                        link: link ? link.getAttribute('href') : '',
                        text: text.substring(0, 300)
                    };
                }).filter(item => item.title.length > 3);
            }
        """)
        return self._items_to_listings(items)

    def _try_generic_extraction(self, page) -> list[DepopListing]:
        """Last resort: find any product-like content on the page."""
        items = page.evaluate("""
            () => {
                // Find all images that look like product photos
                const imgs = document.querySelectorAll('img');
                const productImgs = Array.from(imgs).filter(img => {
                    const src = img.src || '';
                    const w = img.naturalWidth || img.width || 0;
                    return (src.includes('media') || src.includes('product') || src.includes('image') || src.includes('photo') || src.includes('cdn'))
                        && w > 50 && !src.includes('avatar') && !src.includes('logo') && !src.includes('icon');
                });

                return productImgs.slice(0, 50).map(img => {
                    const container = img.closest('a, [class*="item"], [class*="card"], tr, li') || img.parentElement.parentElement;
                    const link = container.querySelector('a[href]') || container.closest('a');
                    const text = container.textContent || '';
                    const priceMatch = text.match(/[$£€]\\s*([\\d,.]+)/);

                    let title = img.alt || '';
                    if (!title) {
                        const titleEl = container.querySelector('h2, h3, h4, [class*="title"], [class*="name"]');
                        title = titleEl ? titleEl.textContent.trim() : text.trim().split('\\n')[0];
                    }

                    return {
                        title: title.substring(0, 100),
                        image: img.src,
                        price: priceMatch ? priceMatch[1] : '0',
                        link: link ? link.getAttribute('href') : '',
                        text: text.substring(0, 200)
                    };
                }).filter(item => item.title.length > 3 || item.image);
            }
        """)
        return self._items_to_listings(items)

    def _load_more_listings(self, page) -> list[DepopListing]:
        """Try to load more listings via scrolling or pagination."""
        all_new = []

        for _ in range(5):
            # Try clicking "Load More" or "Next" buttons
            clicked = page.evaluate("""
                () => {
                    const btns = document.querySelectorAll('button, a');
                    for (const btn of btns) {
                        const text = btn.textContent.toLowerCase().trim();
                        if (text.includes('load more') || text.includes('show more') || text === 'next' || text.includes('next page')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)

            if not clicked:
                # Try scrolling
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            page.wait_for_timeout(2000)

            new_items = self._extract_listings(page)
            if not new_items:
                break

            # Only keep truly new ones
            existing_ids = {l.id for l in all_new}
            for item in new_items:
                if item.id not in existing_ids:
                    all_new.append(item)
                    existing_ids.add(item.id)

        return all_new

    def _items_to_listings(self, items: list[dict]) -> list[DepopListing]:
        """Convert raw extracted items to DepopListing objects."""
        listings = []
        for i, item in enumerate(items):
            title = item.get("title", "").strip()
            if not title and not item.get("image"):
                continue

            price = 0.0
            try:
                price = float(item.get("price", "0").replace(",", ""))
            except (ValueError, AttributeError):
                pass

            images = [item["image"]] if item.get("image") else []
            link = item.get("link", "")

            # Generate an ID from the title or link
            listing_id = ""
            if link:
                listing_id = re.sub(r'[^a-z0-9]', '-', link.lower().split('?')[0])[-60:]
            if not listing_id:
                listing_id = re.sub(r'[^a-z0-9]', '-', title.lower())[:60]
            if not listing_id:
                listing_id = f"item-{i}"

            # Try to extract brand/size from text
            text = item.get("text", "")
            brand = None
            size = None
            size_match = re.search(r'\b(XXS|XS|S|M|L|XL|XXL|2XL|3XL|\d{1,2})\b', text)
            if size_match:
                size = size_match.group(1)

            listings.append(DepopListing(
                id=listing_id,
                title=title or "Untitled",
                description=text[:500] if text else title,
                price=price,
                currency="USD",
                images=images,
                url=link if link.startswith("http") else "",
                brand=brand,
                size=size,
                scraped_at=datetime.now(),
            ))

        return listings

    def close(self):
        pass


# Keep backward compatibility — the CLI and web app import DepopScraper
DepopScraper = CrosslistScraper
