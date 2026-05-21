import httpx

from publishers.base import Publisher
from queue.models import Post


class PinterestPublisher(Publisher):
    API_BASE = "https://api.pinterest.com/v5"

    def __init__(self, access_token: str, board_id: str):
        self.access_token = access_token
        self.board_id = board_id
        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def publish(self, post: Post) -> str:
        """Create a pin on Pinterest. Returns the pin ID."""
        image_url = post.image_urls[0] if post.image_urls else ""

        payload = {
            "board_id": self.board_id,
            "title": post.caption[:100],
            "description": post.caption,
            "link": post.destination_url,
            "media_source": {
                "source_type": "image_url",
                "url": image_url,
                "is_standard": True,
            },
            "alt_text": post.caption[:500],
        }

        response = self.client.post(f"{self.API_BASE}/pins", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["id"]

    def validate_credentials(self) -> bool:
        """Check if the access token is valid by fetching user info."""
        try:
            response = self.client.get(f"{self.API_BASE}/user_account")
            return response.status_code == 200
        except Exception:
            return False

    def get_boards(self) -> list[dict]:
        """List all boards for the authenticated user."""
        response = self.client.get(f"{self.API_BASE}/boards")
        response.raise_for_status()
        return response.json().get("items", [])

    def close(self):
        self.client.close()
