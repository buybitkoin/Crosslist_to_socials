from datetime import datetime
from enum import Enum
from pydantic import BaseModel


class PostStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"


class Platform(str, Enum):
    PINTEREST = "pinterest"
    INSTAGRAM = "instagram"


class Post(BaseModel):
    id: int | None = None
    listing_id: str
    platform: Platform
    status: PostStatus = PostStatus.DRAFT
    caption: str
    image_urls: list[str]
    destination_url: str
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
