# Integration guide: reading `published.db` (for the Pinterest poster)

This document is **self-contained** — you do not need to read the CrossListingAgent codebase
to integrate. It describes a stable, read-only data contract that CrossListingAgent writes
**on every export**, designed specifically for downstream apps like a Pinterest poster.

---

## 1. What this is

CrossListingAgent turns photos of secondhand women's clothing into finished resale listings
(title, description, price, images). Every time the seller **exports** a batch, the agent also
writes a clean, downstream-friendly record of each finished listing to a **separate SQLite
database** plus a **durable image folder**. That's what you read.

You consume two things on the **host machine** (where CrossListingAgent runs — a Mac):

| Artifact | Path (relative to the CrossListingAgent project root) | What it is |
|---|---|---|
| Database | `data/published.db` | One row per current listing (SQLite) |
| Images | `data/published/images/` | The actual photo files, durable, named to match the DB |

> **Expected setup: this app runs on the same Mac as CrossListingAgent** (the recommended,
> simplest configuration). In that case you read the project's `data/` folder directly and
> everything — including `image_dir` — resolves with no extra wiring. See §7A.
> The cross-machine case is documented as a fallback in §7B in case that ever changes.

---

## 2. The data contract

### Database: `data/published.db`

A standard SQLite 3 file. No password, no extensions. One table:

```sql
CREATE TABLE published_listings (
  sku          TEXT PRIMARY KEY,   -- stable unique id of the item (e.g. "CL250626A3F9X")
  listing_id   TEXT,               -- internal id; ignore
  title        TEXT,               -- < 80 chars, ready to post
  description  TEXT,               -- full listing copy; may contain newlines + emoji + #hashtags
  price        TEXT,               -- decimal string, e.g. "48.00" (USD)
  brand        TEXT,
  color        TEXT,
  tags         TEXT,               -- space-separated hashtags, e.g. "#cottagecore #vintage #y2k"
  category     TEXT,               -- human label, e.g. "Dresses" (NOT an internal id)
  image_dir    TEXT,               -- absolute path on the HOST to the image folder
  image_files  TEXT,               -- pipe-joined filenames, IN DISPLAY ORDER (see below)
  cover_image  TEXT,               -- the first/hero image filename (== first of image_files)
  fields_json  TEXT,               -- JSON: full snapshot, for any field not promoted above
  updated_at   TEXT                -- ISO-8601 UTC, e.g. "2026-06-26T03:56:22+00:00"
);
```

### Key semantics — read these, they matter

- **One row per item, keyed by `sku`.** Re-exporting the same item **updates the same row**
  (upsert) and bumps `updated_at`. There is never more than one row per SKU.
- **A listing appears only after it has been exported.** Newly photographed/analyzed items are
  not here until the seller clicks Export.
- **`updated_at` is your change signal.** Poll it to find new or edited listings (§5).
- **Treat the DB as read-only.** Do not write to it. Track your own posting state in your own
  storage (§5), keyed by `sku`.

---

## 3. Resolving image files

`image_files` is a **pipe-joined** (`|`) list of filenames, already in the order they should
appear (index 0 = the hero shot, same as `cover_image`):

```
CL250626A3F9X_1.jpg|CL250626A3F9X_2.jpg|CL250626A3F9X_3.jpg
```

To get a usable file path, join each name onto the image folder:

- If co-located on the host: `os.path.join(image_dir, name)`.
- If you synced the images elsewhere: join each name onto **your** local copy of
  `data/published/images/` (don't trust `image_dir`'s absolute host path — see §7).

**Guarantees about the files:**
- Formats are web-friendly: `.jpg`, `.png`, or `.webp`. **HEIC/HEIF are already converted to
  `.jpg`** before they land here — you never have to deal with HEIC.
- Filenames are safe (`[A-Za-z0-9._-]` only) and prefixed with the SKU.
- Files are **durable** — copied into `data/published/images/` at export time. Do **not** read
  from `data/work/`; that's a scratch folder the agent overwrites on the next batch.

**Defensive note:** if an individual image copy failed at export, that name may be absent from
`image_files`, or (rarely) present but missing on disk. Always check the file exists before
posting and skip gracefully.

---

## 4. Minimal reader (Python, no dependencies)

```python
import json, os, sqlite3

ROOT = os.environ.get("CROSSLISTING_DIR", "/Users/Shared/CrossListingAgent")  # same Mac (§7A)
PUBLISHED_DB = os.path.join(ROOT, "data", "published.db")
# Same machine -> leave None and trust row["image_dir"]. Off-host -> set to your synced
# copy of published/images/ (see §7B).
IMAGES_BASE = None

def fetch_listings():
    # read-only + wait up to 5s if the agent is mid-write, instead of erroring
    uri = f"file:{PUBLISHED_DB}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM published_listings ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        base = IMAGES_BASE or r["image_dir"]
        names = [n for n in (r["image_files"] or "").split("|") if n]
        paths = [os.path.join(base, n) for n in names]
        paths = [p for p in paths if os.path.exists(p)]   # skip any missing files
        if not paths:
            continue                                       # nothing to post without images
        out.append({
            "sku": r["sku"],
            "title": r["title"],
            "description": r["description"],
            "price": r["price"],
            "tags": (r["tags"] or "").split(),
            "category": r["category"],
            "cover": paths[0],
            "images": paths,
            "updated_at": r["updated_at"],
            "extra": json.loads(r["fields_json"] or "{}"),
        })
    return out
```

> SQLite is not concurrency-heavy here: the agent's writes are short and commit immediately.
> Opening **read-only** (`mode=ro`) with a `timeout` avoids the rare "database is locked" if you
> happen to read during an export.

---

## 5. Avoiding duplicate posts (incremental processing)

Keep your own small store (a JSON file or your own DB table) mapping `sku -> last_posted_updated_at`.
On each run:

```
for listing in fetch_listings():
    seen = my_state.get(listing["sku"])
    if seen == listing["updated_at"]:
        continue                      # already posted this exact version
    post_to_pinterest(listing)        # new item, or it was re-exported with edits
    my_state[listing["sku"]] = listing["updated_at"]
```

This makes you idempotent: a re-export with no changes won't re-post; a re-export with edits
(new title/price/photos) will, because `updated_at` changed.

---

## 6. Field details & formatting tips for Pinterest

- **`title`** — under 80 chars, already human-ready. Good as the Pin title.
- **`description`** — the full eBay-style listing copy (~1000 chars max). May contain line
  breaks, emoji (e.g. ❤), and trailing hashtags. Usable as-is for the Pin description, or trim
  to Pinterest's limit if needed.
- **`tags`** — space-separated hashtags already embedded in the description too; use them for
  Pinterest tags/keywords. Split on whitespace.
- **`price`** — a decimal **string** in USD ("48.00"). Cast to float if you need a number.
  May be empty only in edge cases — guard for it.
- **`category`** — a human label ("Dresses", "Tops", "Shoes"), handy for board routing.
- **`fields_json`** — everything in one JSON blob (includes `Size`, `Condition`,
  `Secondary color`, `Quantity`, etc.) for anything not promoted to a column.
- **`cover_image`** — use this as the Pin's primary image; `images[1:]` are the rest in order.

---

## 7. Where the app runs

### 7A. Same Mac as CrossListingAgent — RECOMMENDED (your setup)

This is the intended configuration and the simplest: both apps share one filesystem, so you
read the live `data/` folder directly and **`image_dir` from the DB resolves with no extra
config** (leave `IMAGES_BASE = None`).

Point the app at the CrossListingAgent project root via a single config value — don't hardcode
it in code. On this host the project lives under `/Users/Shared/` (it was placed there so it's
reachable across macOS user accounts), so the data dir is typically:

```
/Users/Shared/CrossListingAgent/data/published.db
/Users/Shared/CrossListingAgent/data/published/images/
```

Recommended pattern — read the root from an env var with that as the default:

```python
import os
ROOT = os.environ.get("CROSSLISTING_DIR", "/Users/Shared/CrossListingAgent")
PUBLISHED_DB = os.path.join(ROOT, "data", "published.db")
IMAGES_BASE  = None   # same machine -> trust row["image_dir"] directly
```

Confirm the exact path once with `ls /Users/Shared/CrossListingAgent/data/published.db` (adjust
if the folder name differs), set `CROSSLISTING_DIR` accordingly, and you're done. Because the
files are live and local, there's nothing to sync — a new export is visible to the next poll
immediately.

### 7B. Different machine — fallback (only if this ever changes)

`image_dir` stores an **absolute path on the host Mac**, so it won't resolve from another
machine. If the Pinterest app is ever moved off-host:

1. **Sync the two artifacts** to the app's machine — copy/mount `data/published.db` and
   `data/published/images/`. Re-sync on a schedule; the DB file is tiny and the images folder
   grows over time (never auto-pruned), so an incremental `rsync`-style copy is ideal. The
   row's `updated_at` tells you what changed since last sync.
2. **Set `IMAGES_BASE`** to your local copy of `published/images/` and **ignore `image_dir`**
   (the reader in §4 already prefers `IMAGES_BASE` when set).

Everything else — schema, ordering, dedupe via `updated_at` — is identical; only the two paths
change.

---

## 8. Quick checklist

- [ ] Point `CROSSLISTING_DIR` at the project on the same Mac (default
      `/Users/Shared/CrossListingAgent`); leave `IMAGES_BASE = None` so `image_dir` is used (§7A).
- [ ] Open `data/published.db` **read-only** (`mode=ro`, with a timeout).
- [ ] One row per listing, keyed by **`sku`**; poll **`updated_at`** for changes.
- [ ] Build image paths from **`image_files`** (ordered) joined to the image folder; use
      **`cover_image`** as the hero. Verify each file exists; skip missing.
- [ ] Never read `data/work/`; never write to `published.db`.
- [ ] Track posted `sku -> updated_at` yourself to avoid duplicates.
- [ ] Listings only show up **after export**.
```
