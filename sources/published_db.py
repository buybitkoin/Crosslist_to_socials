"""Read finished listings from CrossListingAgent's published.db.

This is a read-only consumer of the data contract documented in
published_db_integration.md. We never write to published.db; posting state is
tracked in this app's own database, keyed by listing id (derived from SKU).
"""
import json
import os
import sqlite3
from datetime import datetime

import config
from scraper.models import DepopListing


def is_available() -> bool:
    """True if the CrossListingAgent published database exists and is readable."""
    return os.path.exists(config.PUBLISHED_DB_PATH)


def _connect():
    # Open read-only with a timeout so a concurrent export doesn't make us error.
    uri = f"file:{config.PUBLISHED_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_published_listings() -> list[DepopListing]:
    """Return all exported listings as DepopListing objects with local image paths.

    Listings whose image files are all missing on disk are skipped — there's
    nothing to post without an image.
    """
    if not is_available():
        return []

    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM published_listings ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()

    listings = []
    for r in rows:
        base = r["image_dir"] or config.PUBLISHED_IMAGES_DIR
        names = [n for n in (r["image_files"] or "").split("|") if n]
        paths = [os.path.join(base, n) for n in names]
        paths = [p for p in paths if os.path.exists(p)]
        if not paths:
            continue

        extra = {}
        try:
            extra = json.loads(r["fields_json"] or "{}")
        except (ValueError, TypeError):
            pass

        price = 0.0
        try:
            price = float(r["price"]) if r["price"] else 0.0
        except (ValueError, TypeError):
            pass

        listings.append(DepopListing(
            id=f"cla-{r['sku']}",
            title=(r["title"] or "Untitled")[:200],
            description=r["description"] or (r["title"] or ""),
            price=price,
            currency="USD",
            images=paths,
            url="",  # CrossListingAgent has no live marketplace URL
            brand=r["brand"] or None,
            size=extra.get("Size") or None,
            condition=extra.get("Condition") or None,
            scraped_at=datetime.now(),
        ))

    return listings
