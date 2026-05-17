from abc import ABC, abstractmethod

from queue.models import Post


class Publisher(ABC):
    @abstractmethod
    def publish(self, post: Post) -> str:
        """Publish a post. Returns the platform-specific post ID."""
        ...

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Check if credentials are valid."""
        ...
