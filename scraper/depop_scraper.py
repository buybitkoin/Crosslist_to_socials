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

            page.goto(self.DASHBOARD_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            if self._needs_login(page):
                print("\n[!] Please log in to Crosslist in the browser window.")
                print("    Waiting up to 120 seconds...")
                if not self._wait_for_login(page, timeout=120):
                    print("[!] Login timeout. Run 'setup' first to save your session.")
                    context.close()
                    return []

            page.wait_for_timeout(3000)

            # Extract listings from the current page
            listings = self._extract_listings(page)

            # Paginate to get all listings
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
        url = page.url.lower()
        if "login" in url or "signin" in url or "sign-in" in url:
            return True
        content = page.content()[:2000].lower()
        return "log in" in content and "password" in content

    def _wait_for_login(self, page, timeout: int = 120) -> bool:
        for _ in range(timeout):
            if not self._needs_login(page):
                page.wait_for_timeout(3000)
                return True
            time.sleep(1)
        return False

    def _extract_listings(self, page) -> list[DepopListing]:
        """Extract listing data from Crosslist's table layout."""
        items = page.evaluate(
            """() => {
                const rows = document.querySelectorAll('tbody.table-body tr[data-index]');
                if (rows.length === 0) return [];

                return Array.from(rows).map(row => {
                    // Image: td.images img with crosslist media URL
                    const imgCell = row.querySelector('td.images img');
                    const image = imgCell ? imgCell.src : '';

                    // Title: td.title text content
                    const titleCell = row.querySelector('td.title');
                    const title = titleCell ? titleCell.textContent.trim() : '';

                    // Price: td.price text content
                    const priceCell = row.querySelector('td.price');
                    const priceText = priceCell ? priceCell.textContent.trim() : '';

                    // SKU: td.sku text content
                    const skuCell = row.querySelector('td.sku');
                    const sku = skuCell ? skuCell.textContent.trim() : '';

                    // Created date: td.created span text
                    const createdCell = row.querySelector('td.created span');
                    const created = createdCell ? createdCell.textContent.trim() : '';

                    // Data index for ordering
                    const index = row.getAttribute('data-index');

                    return { title, image, priceText, sku, created, index };
                }).filter(item => item.title || item.image);
            }"""
        )
        return self._items_to_listings(items)

    def _load_more_listings(self, page) -> list[DepopListing]:
        """Click through PrimeVue paginator to load additional pages."""
        all_new = []
        seen_ids = set()
        pages_without_new = 0

        # Safety cap of 200 pages; the real exit is the disabled Next button
        for _ in range(200):
            has_next = page.evaluate(
                """() => {
                    const nextBtn = document.querySelector('.p-paginator-next:not([disabled]):not(.p-disabled)');
                    if (nextBtn) {
                        nextBtn.click();
                        return true;
                    }
                    return false;
                }"""
            )

            if not has_next:
                break

            page.wait_for_timeout(2000)

            new_items = self._extract_listings(page)
            if not new_items:
                break

            added = 0
            for item in new_items:
                if item.id not in seen_ids:
                    all_new.append(item)
                    seen_ids.add(item.id)
                    added += 1

            # If two consecutive pages yield nothing new, we're looping on the last page
            if added == 0:
                pages_without_new += 1
                if pages_without_new >= 2:
                    break
            else:
                pages_without_new = 0

        return all_new

    def _items_to_listings(self, items: list[dict]) -> list[DepopListing]:
        """Convert raw extracted items to DepopListing objects."""
        listings = []
        for i, item in enumerate(items):
            title = item.get("title", "").strip()
            if not title and not item.get("image"):
                continue

            # Parse price
            price = 0.0
            price_text = item.get("priceText", "")
            price_match = re.search(r'[\d,.]+', price_text)
            if price_match:
                try:
                    price = float(price_match.group().replace(",", ""))
                except ValueError:
                    pass

            # Currency from price symbol
            currency = "USD"
            if "£" in price_text:
                currency = "GBP"
            elif "€" in price_text:
                currency = "EUR"

            images = []
            img_url = item.get("image", "")
            if img_url and img_url.startswith("http"):
                # The dashboard serves 350px thumbnails as .../p2.jpg; the
                # full-resolution original (1600px) lives at .../p1.jpg.
                full_url = re.sub(r'/p2\.(jpg|jpeg|png|webp)$', r'/p1.\1', img_url)
                images = [full_url]

            # Generate a stable ID. Prefer the unique listing UUID embedded in the
            # image URL (media-na.crosslist.com/<account>/<listing-uuid>/p2.jpg) —
            # titles can collide when truncated.
            sku = item.get("sku", "")
            uuid_match = re.search(
                r'media[^/]*\.crosslist\.com/[0-9a-f-]+/([0-9a-f-]{36})/', img_url
            )
            if uuid_match:
                listing_id = f"cl-{uuid_match.group(1)}"
            elif sku:
                listing_id = f"cl-{sku}"
            elif title:
                listing_id = "cl-" + re.sub(r'[^a-z0-9]', '-', title.lower())[:80]
            else:
                listing_id = f"cl-item-{i}"

            # Try to extract size from title
            size = None
            size_match = re.search(r'\bsize\s+(XXS|XS|S|M|L|XL|XXL|2XL|3XL|\d{1,2})\b', title, re.IGNORECASE)
            if size_match:
                size = size_match.group(1)

            listings.append(DepopListing(
                id=listing_id,
                title=title[:200] or "Untitled",
                description=title,
                price=price,
                currency=currency,
                images=images,
                url="",
                brand=None,
                size=size,
                scraped_at=datetime.now(),
            ))

        return listings

    def close(self):
        pass


# Backward compatibility alias
DepopScraper = CrosslistScraper
