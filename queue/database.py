import json
import sqlite3
from datetime import datetime
from pathlib import Path

from scraper.models import DepopListing
from queue.models import Post, PostStatus, Platform


class Database:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                price REAL,
                currency TEXT,
                images TEXT,
                url TEXT,
                brand TEXT,
                size TEXT,
                condition TEXT,
                scraped_at DATETIME
            );

            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                status TEXT DEFAULT 'draft',
                caption TEXT NOT NULL,
                image_urls TEXT NOT NULL,
                destination_url TEXT NOT NULL,
                scheduled_at DATETIME,
                published_at DATETIME,
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS publish_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER REFERENCES posts(id),
                platform TEXT,
                platform_post_id TEXT,
                published_at DATETIME,
                response_data TEXT
            );
        """)
        self.conn.commit()

    def save_listing(self, listing: DepopListing) -> bool:
        """Save a listing. Returns True if new, False if already exists."""
        existing = self.conn.execute(
            "SELECT id FROM listings WHERE id = ?", (listing.id,)
        ).fetchone()
        if existing:
            return False

        self.conn.execute(
            """INSERT INTO listings (id, title, description, price, currency, images, url, brand, size, condition, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                listing.id,
                listing.title,
                listing.description,
                listing.price,
                listing.currency,
                json.dumps(listing.images),
                listing.url,
                listing.brand,
                listing.size,
                listing.condition,
                listing.scraped_at.isoformat(),
            ),
        )
        self.conn.commit()
        return True

    def get_listing(self, listing_id: str) -> DepopListing | None:
        row = self.conn.execute(
            "SELECT * FROM listings WHERE id = ?", (listing_id,)
        ).fetchone()
        if not row:
            return None
        return DepopListing(
            id=row["id"],
            title=row["title"],
            description=row["description"] or "",
            price=row["price"],
            currency=row["currency"],
            images=json.loads(row["images"]),
            url=row["url"],
            brand=row["brand"],
            size=row["size"],
            condition=row["condition"],
            scraped_at=row["scraped_at"],
        )

    def get_unprocessed_listings(self, platform: Platform) -> list[DepopListing]:
        """Get listings that don't have a post for the given platform yet."""
        rows = self.conn.execute(
            """SELECT l.* FROM listings l
               WHERE l.id NOT IN (
                   SELECT listing_id FROM posts WHERE platform = ?
               )""",
            (platform.value,),
        ).fetchall()
        return [
            DepopListing(
                id=r["id"],
                title=r["title"],
                description=r["description"] or "",
                price=r["price"],
                currency=r["currency"],
                images=json.loads(r["images"]),
                url=r["url"],
                brand=r["brand"],
                size=r["size"],
                condition=r["condition"],
                scraped_at=r["scraped_at"],
            )
            for r in rows
        ]

    def add_post(self, post: Post) -> int:
        cursor = self.conn.execute(
            """INSERT INTO posts (listing_id, platform, status, caption, image_urls, destination_url, scheduled_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                post.listing_id,
                post.platform.value,
                post.status.value,
                post.caption,
                json.dumps(post.image_urls),
                post.destination_url,
                post.scheduled_at.isoformat() if post.scheduled_at else None,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_posts(self, status: PostStatus | None = None, platform: Platform | None = None) -> list[Post]:
        query = "SELECT * FROM posts WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if platform:
            query += " AND platform = ?"
            params.append(platform.value)
        query += " ORDER BY created_at DESC"

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_post(r) for r in rows]

    def approve_post(self, post_id: int):
        self.conn.execute(
            "UPDATE posts SET status = ?, updated_at = ? WHERE id = ?",
            (PostStatus.APPROVED.value, datetime.now().isoformat(), post_id),
        )
        self.conn.commit()

    def reject_post(self, post_id: int):
        self.conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        self.conn.commit()

    def unapprove_post(self, post_id: int):
        self.conn.execute(
            "UPDATE posts SET status = ?, updated_at = ? WHERE id = ?",
            (PostStatus.DRAFT.value, datetime.now().isoformat(), post_id),
        )
        self.conn.commit()

    def reject_all_drafts(self):
        self.conn.execute("DELETE FROM posts WHERE status = ?", (PostStatus.DRAFT.value,))
        self.conn.commit()

    def clear_all_listings(self):
        self.conn.execute("DELETE FROM posts WHERE status IN (?, ?)", (PostStatus.DRAFT.value, PostStatus.APPROVED.value))
        self.conn.execute("DELETE FROM listings")
        self.conn.commit()

    def update_caption(self, post_id: int, caption: str):
        self.conn.execute(
            "UPDATE posts SET caption = ?, updated_at = ? WHERE id = ?",
            (caption, datetime.now().isoformat(), post_id),
        )
        self.conn.commit()

    def mark_published(self, post_id: int, platform_post_id: str, response_data: dict | None = None):
        now = datetime.now().isoformat()
        self.conn.execute(
            "UPDATE posts SET status = ?, published_at = ?, updated_at = ? WHERE id = ?",
            (PostStatus.PUBLISHED.value, now, now, post_id),
        )
        self.conn.execute(
            """INSERT INTO publish_log (post_id, platform, platform_post_id, published_at, response_data)
               SELECT ?, platform, ?, ?, ? FROM posts WHERE id = ?""",
            (post_id, platform_post_id, now, json.dumps(response_data or {}), post_id),
        )
        self.conn.commit()

    def mark_failed(self, post_id: int, error: str):
        self.conn.execute(
            "UPDATE posts SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
            (PostStatus.FAILED.value, error, datetime.now().isoformat(), post_id),
        )
        self.conn.commit()

    def get_stats(self) -> dict:
        stats = {}
        for status in PostStatus:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM posts WHERE status = ?", (status.value,)
            ).fetchone()[0]
            stats[status.value] = count
        stats["total_listings"] = self.conn.execute(
            "SELECT COUNT(*) FROM listings"
        ).fetchone()[0]
        return stats

    def _row_to_post(self, row) -> Post:
        return Post(
            id=row["id"],
            listing_id=row["listing_id"],
            platform=Platform(row["platform"]),
            status=PostStatus(row["status"]),
            caption=row["caption"],
            image_urls=json.loads(row["image_urls"]),
            destination_url=row["destination_url"],
            scheduled_at=row["scheduled_at"],
            published_at=row["published_at"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def close(self):
        self.conn.close()
