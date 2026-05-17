from datetime import datetime
from pydantic import BaseModel


class DepopListing(BaseModel):
    id: str
    title: str
    description: str
    price: float
    currency: str = "USD"
    images: list[str]
    url: str
    brand: str | None = None
    size: str | None = None
    condition: str | None = None
    scraped_at: datetime = datetime.now()
