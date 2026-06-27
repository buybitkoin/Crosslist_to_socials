import base64
import mimetypes

import httpx

from publishers.base import Publisher
from queue.models import Post


class PinterestPublisher(Publisher):
    API_BASE = "https://api.pinterest.com/v5"
    SANDBOX_API_BASE = "https://api-sandbox.pinterest.com/v5"

    def __init__(self, access_token: str, board_id: str, sandbox: bool = False):
        self.access_token = access_token
        self.board_id = board_id
        self.api_base = self.SANDBOX_API_BASE if sandbox else self.API_BASE
        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def publish(self, post: Post) -> str:
        """Create a pin on Pinterest. Returns the pin ID."""
        image = post.image_urls[0] if post.image_urls else ""

        payload = {
            "board_id": self.board_id,
            "title": post.caption[:100],
            "description": post.caption,
            "media_source": self._build_media_source(image),
            "alt_text": post.caption[:500],
        }
        # link is optional — only send it if we actually have a destination
        if post.destination_url:
            payload["link"] = post.destination_url

        response = self.client.post(f"{self.api_base}/pins", json=payload)
        if response.status_code >= 400:
            raise Exception(f"Pinterest API error {response.status_code}: {response.text[:500]}")
        data = response.json()
        return data["id"]

    def _build_media_source(self, image: str) -> dict:
        """Build the media_source. Remote URLs are passed through; local file
        paths are read and uploaded inline as base64 (Pinterest API v5)."""
        if image.startswith("http://") or image.startswith("https://"):
            return {"source_type": "image_url", "url": image, "is_standard": True}

        # Local file from CrossListingAgent — upload bytes directly.
        with open(image, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        content_type = mimetypes.guess_type(image)[0] or "image/jpeg"
        return {"source_type": "image_base64", "content_type": content_type, "data": data}

    def validate_credentials(self) -> dict:
        """Check if the access token is valid by fetching user info. Returns status details."""
        try:
            response = self.client.get(f"{self.api_base}/user_account")
            if response.status_code == 200:
                data = response.json()
                return {"valid": True, "username": data.get("username", ""), "message": "Credentials are valid!"}
            else:
                return {"valid": False, "message": f"HTTP {response.status_code}: {response.text[:300]}"}
        except Exception as e:
            return {"valid": False, "message": str(e)}

    def get_boards(self) -> list[dict]:
        """List all boards for the authenticated user."""
        response = self.client.get(f"{self.api_base}/boards")
        response.raise_for_status()
        return response.json().get("items", [])

    def create_board(self, name: str, description: str = "") -> dict:
        """Create a new board. Returns the board data including ID."""
        payload = {"name": name, "description": description, "privacy": "PUBLIC"}
        response = self.client.post(f"{self.api_base}/boards", json=payload)
        response.raise_for_status()
        return response.json()

    def close(self):
        self.client.close()
