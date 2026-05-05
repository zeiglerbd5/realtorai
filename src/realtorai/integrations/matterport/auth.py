"""Matterport API token-based authentication.

Uses token/secret pair stored in environment and Keychain.
"""


import structlog

from realtorai.config.settings import get_settings
from realtorai.integrations.base import Integration
from realtorai.storage.keychain import KeychainKeys, keychain

logger = structlog.get_logger()


class MatterportAuth(Integration):
    """Matterport API token-based authentication."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._token: str | None = None
        self._secret: str | None = None

    @property
    def name(self) -> str:
        return "Matterport"

    async def is_configured(self) -> bool:
        """Check if Matterport credentials are configured."""
        # First check settings (from .env)
        token = getattr(self.settings, "matterport_api_token", None)
        secret = getattr(self.settings, "matterport_api_secret", None)

        if token and secret:
            return True

        # Fall back to keychain
        token = keychain.get(KeychainKeys.MATTERPORT_API_TOKEN)
        secret = keychain.get(KeychainKeys.MATTERPORT_API_SECRET)

        return bool(token and secret)

    async def is_connected(self) -> bool:
        """Check if we have valid credentials loaded."""
        if self._token and self._secret:
            return True

        # Try to load credentials
        return await self._load_credentials()

    async def connect(self) -> bool:
        """Load and validate credentials."""
        if not await self.is_configured():
            logger.error("matterport_not_configured")
            return False

        if await self._load_credentials():
            logger.info("matterport_connected")
            return True

        return False

    async def disconnect(self) -> None:
        """Clear loaded credentials."""
        self._token = None
        self._secret = None
        logger.info("matterport_disconnected")

    async def get_credentials(self) -> tuple[str, str] | None:
        """Get the API token and secret.

        Returns:
            Tuple of (token, secret) or None if not authenticated.
        """
        if not await self.is_connected():
            return None
        return (self._token, self._secret)

    async def _load_credentials(self) -> bool:
        """Load credentials from settings or keychain."""
        # Try settings first
        token = getattr(self.settings, "matterport_api_token", None)
        secret = getattr(self.settings, "matterport_api_secret", None)

        if token and secret:
            self._token = token
            self._secret = secret
            logger.debug("matterport_credentials_loaded_from_settings")
            return True

        # Fall back to keychain
        token = keychain.get(KeychainKeys.MATTERPORT_API_TOKEN)
        secret = keychain.get(KeychainKeys.MATTERPORT_API_SECRET)

        if token and secret:
            self._token = token
            self._secret = secret
            logger.debug("matterport_credentials_loaded_from_keychain")
            return True

        logger.warning("matterport_no_credentials_found")
        return False

    def save_credentials(self, token: str, secret: str) -> bool:
        """Save credentials to keychain for persistence."""
        success = keychain.set(KeychainKeys.MATTERPORT_API_TOKEN, token)
        success = success and keychain.set(KeychainKeys.MATTERPORT_API_SECRET, secret)

        if success:
            self._token = token
            self._secret = secret
            logger.info("matterport_credentials_saved")

        return success

    def clear_credentials(self) -> bool:
        """Clear stored credentials from keychain."""
        keychain.delete(KeychainKeys.MATTERPORT_API_TOKEN)
        keychain.delete(KeychainKeys.MATTERPORT_API_SECRET)
        self._token = None
        self._secret = None
        logger.info("matterport_credentials_cleared")
        return True


# Default instance
matterport_auth = MatterportAuth()
