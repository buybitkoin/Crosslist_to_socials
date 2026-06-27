import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEPOP_SHOP_USERNAME = os.getenv("DEPOP_SHOP_USERNAME", "")

PINTEREST_APP_ID = os.getenv("PINTEREST_APP_ID", "")
PINTEREST_APP_SECRET = os.getenv("PINTEREST_APP_SECRET", "")
PINTEREST_ACCESS_TOKEN = os.getenv("PINTEREST_ACCESS_TOKEN", "")
PINTEREST_REFRESH_TOKEN = os.getenv("PINTEREST_REFRESH_TOKEN", "")
PINTEREST_BOARD_ID = os.getenv("PINTEREST_BOARD_ID", "")

INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID", "")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")

DATABASE_PATH = os.getenv("DATABASE_PATH", str(DATA_DIR / "posts.db"))
IMAGE_DOWNLOAD_DIR = os.getenv("IMAGE_DOWNLOAD_DIR", str(DATA_DIR / "images"))

Path(IMAGE_DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

# --- CrossListingAgent integration (read-only source of finished listings) ---
# Root of the CrossListingAgent project on the same Mac. See published_db_integration.md.
CROSSLISTING_DIR = os.getenv("CROSSLISTING_DIR", "/Users/Shared/CrossListingAgent")
PUBLISHED_DB_PATH = os.getenv(
    "PUBLISHED_DB_PATH", str(Path(CROSSLISTING_DIR) / "data" / "published.db")
)
PUBLISHED_IMAGES_DIR = os.getenv(
    "PUBLISHED_IMAGES_DIR", str(Path(CROSSLISTING_DIR) / "data" / "published" / "images")
)
