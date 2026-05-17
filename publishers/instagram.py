import time

import httpx

from publishers.base import Publisher
from queue.models import Post


class InstagramPublisher(Publisher):
    """Instagram Graph API publisher (requires Business account + Facebook Page)."""

    GRAPH_URL = "https://graph.facebook.com/v19.0"

    def __init__(self, user_id: str, access_token: str):
        self.user_id = user_id
        self.access_token = access_token
        self.client = httpx.Client(timeout=60.0)

    def publish(self, post: Post) -> str:
        """Publish a photo post to Instagram. Returns the media ID."""
        image_url = post.image_urls[0] if post.image_urls else ""

        # Step 1: Create a media container
        container_id = self._create_container(image_url, post.caption)

        # Step 2: Wait for container to be ready
        self._wait_for_container(container_id)

        # Step 3: Publish the container
        return self._publish_container(container_id)

    def validate_credentials(self) -> bool:
        """Check if the access token is valid."""
        try:
            response = self.client.get(
                f"{self.GRAPH_URL}/{self.user_id}",
                params={"access_token": self.access_token, "fields": "id,username"},
            )
            return response.status_code == 200
        except Exception:
            return False

    def _create_container(self, image_url: str, caption: str) -> str:
        response = self.client.post(
            f"{self.GRAPH_URL}/{self.user_id}/media",
            params={
                "access_token": self.access_token,
                "image_url": image_url,
                "caption": caption,
            },
        )
        response.raise_for_status()
        return response.json()["id"]

    def _wait_for_container(self, container_id: str, max_wait: int = 30):
        """Poll until the container is ready for publishing."""
        for _ in range(max_wait):
            response = self.client.get(
                f"{self.GRAPH_URL}/{container_id}",
                params={"access_token": self.access_token, "fields": "status_code"},
            )
            data = response.json()
            if data.get("status_code") == "FINISHED":
                return
            time.sleep(1)
        raise TimeoutError("Instagram media container not ready after 30s")

    def _publish_container(self, container_id: str) -> str:
        response = self.client.post(
            f"{self.GRAPH_URL}/{self.user_id}/media_publish",
            params={
                "access_token": self.access_token,
                "creation_id": container_id,
            },
        )
        response.raise_for_status()
        return response.json()["id"]

    def close(self):
        self.client.close()
