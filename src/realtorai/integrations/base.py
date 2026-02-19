"""Base class for external integrations."""

from abc import ABC, abstractmethod

import structlog

logger = structlog.get_logger()


class Integration(ABC):
    """Base class for external API integrations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Integration name for logging and display."""
        ...

    @abstractmethod
    async def is_configured(self) -> bool:
        """Check if the integration is properly configured."""
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if the integration is connected/authenticated."""
        ...

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection/authentication."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect/cleanup."""
        ...

    async def health_check(self) -> dict:
        """Perform a health check on the integration."""
        return {
            "name": self.name,
            "configured": await self.is_configured(),
            "connected": await self.is_connected(),
        }
