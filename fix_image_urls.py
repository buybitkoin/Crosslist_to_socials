"""One-time fix: upgrade stored image URLs from 350px thumbnails (p2.jpg)
to full-resolution originals (p1.jpg). Safe to run multiple times."""
import json
import sqlite3

import config

conn = sqlite3.connect(config.DATABASE_PATH)
conn.row_factory = sqlite3.Row


def upgrade(urls: list[str]) -> list[str]:
    import re
    return [re.sub(r'/p2\.(jpg|jpeg|png|webp)$', r'/p1.\1', u) for u in urls]


fixed_listings = 0
for row in conn.execute("SELECT id, images FROM listings").fetchall():
    images = json.loads(row["images"])
    upgraded = upgrade(images)
    if upgraded != images:
        conn.execute("UPDATE listings SET images = ? WHERE id = ?", (json.dumps(upgraded), row["id"]))
        fixed_listings += 1

fixed_posts = 0
for row in conn.execute("SELECT id, image_urls FROM posts WHERE status != 'published'").fetchall():
    urls = json.loads(row["image_urls"])
    upgraded = upgrade(urls)
    if upgraded != urls:
        conn.execute("UPDATE posts SET image_urls = ? WHERE id = ?", (json.dumps(upgraded), row["id"]))
        fixed_posts += 1

conn.commit()
conn.close()
print(f"Upgraded {fixed_listings} listings and {fixed_posts} unpublished posts to full-resolution images.")
