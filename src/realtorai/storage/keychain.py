"""macOS Keychain integration for secure credential storage."""

import json
from typing import Any

import keyring
import structlog

logger = structlog.get_logger()

# Service name used in Keychain
SERVICE_NAME = "com.realtorai.app"


class KeychainStore:
    """Secure storage using macOS Keychain via keyring library."""

    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self.service_name = service_name

    def get(self, key: str) -> str | None:
        """Retrieve a value from Keychain."""
        try:
            value = keyring.get_password(self.service_name, key)
            logger.debug("keychain_get", key=key, found=value is not None)
            return value
        except Exception as e:
            logger.error("keychain_get_error", key=key, error=str(e))
            return None

    def set(self, key: str, value: str) -> bool:
        """Store a value in Keychain."""
        try:
            keyring.set_password(self.service_name, key, value)
            logger.info("keychain_set", key=key)
            return True
        except Exception as e:
            logger.error("keychain_set_error", key=key, error=str(e))
            return False

    def delete(self, key: str) -> bool:
        """Delete a value from Keychain."""
        try:
            keyring.delete_password(self.service_name, key)
            logger.info("keychain_delete", key=key)
            return True
        except keyring.errors.PasswordDeleteError:
            # Key didn't exist
            return True
        except Exception as e:
            logger.error("keychain_delete_error", key=key, error=str(e))
            return False

    def get_json(self, key: str) -> dict[str, Any] | None:
        """Retrieve and parse a JSON value from Keychain."""
        value = self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError as e:
                logger.error("keychain_json_parse_error", key=key, error=str(e))
        return None

    def set_json(self, key: str, value: dict[str, Any]) -> bool:
        """Serialize and store a JSON value in Keychain."""
        try:
            return self.set(key, json.dumps(value))
        except (TypeError, ValueError) as e:
            logger.error("keychain_json_serialize_error", key=key, error=str(e))
            return False


# Predefined key names for consistency
class KeychainKeys:
    """Standard key names used in the application."""

    # Microsoft Graph OAuth tokens
    GRAPH_ACCESS_TOKEN = "graph_access_token"
    GRAPH_REFRESH_TOKEN = "graph_refresh_token"
    GRAPH_TOKEN_EXPIRY = "graph_token_expiry"

    # Spark API (FlexMLS) OAuth tokens
    SPARK_ACCESS_TOKEN = "spark_access_token"
    SPARK_REFRESH_TOKEN = "spark_refresh_token"
    SPARK_TOKEN_EXPIRY = "spark_token_expiry"

    # DocuSign
    DOCUSIGN_ACCESS_TOKEN = "docusign_access_token"
    DOCUSIGN_REFRESH_TOKEN = "docusign_refresh_token"

    # Matterport API (token-based auth)
    MATTERPORT_API_TOKEN = "matterport_api_token"
    MATTERPORT_API_SECRET = "matterport_api_secret"


# Default instance
keychain = KeychainStore()


def get_graph_tokens() -> dict[str, Any] | None:
    """Get Microsoft Graph OAuth tokens from Keychain.

    Returns a dict with access_token, refresh_token, and expiry if available.
    Returns None if not authenticated.
    """
    access_token = keychain.get(KeychainKeys.GRAPH_ACCESS_TOKEN)
    if not access_token:
        return None

    return {
        "access_token": access_token,
        "refresh_token": keychain.get(KeychainKeys.GRAPH_REFRESH_TOKEN),
        "expiry": keychain.get(KeychainKeys.GRAPH_TOKEN_EXPIRY),
    }


def save_graph_tokens(
    access_token: str,
    refresh_token: str | None = None,
    expiry: str | None = None,
) -> bool:
    """Save Microsoft Graph OAuth tokens to Keychain."""
    success = keychain.set(KeychainKeys.GRAPH_ACCESS_TOKEN, access_token)

    if refresh_token:
        keychain.set(KeychainKeys.GRAPH_REFRESH_TOKEN, refresh_token)
    if expiry:
        keychain.set(KeychainKeys.GRAPH_TOKEN_EXPIRY, expiry)

    return success


def clear_graph_tokens() -> bool:
    """Clear Microsoft Graph OAuth tokens from Keychain."""
    keychain.delete(KeychainKeys.GRAPH_ACCESS_TOKEN)
    keychain.delete(KeychainKeys.GRAPH_REFRESH_TOKEN)
    keychain.delete(KeychainKeys.GRAPH_TOKEN_EXPIRY)
    return True
