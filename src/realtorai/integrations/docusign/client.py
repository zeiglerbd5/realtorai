"""DocuSign Rooms API client."""

from typing import Any

import httpx
import structlog

from realtorai.config.settings import get_settings
from realtorai.integrations.docusign.auth import docusign_auth

logger = structlog.get_logger()


class DocuSignClient:
    """HTTP client for DocuSign Rooms API requests."""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self.settings = get_settings()

    def _get_base_url(self) -> str:
        """Get the Rooms API base URL."""
        # Rooms API always uses rooms.docusign.com, not the eSignature URL
        # Demo: https://demo.rooms.docusign.com
        # Prod: https://rooms.docusign.com
        return "https://demo.rooms.docusign.com/restapi/v2"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with auth headers."""
        token = await docusign_auth.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated with DocuSign")

        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._get_base_url(),
                timeout=30.0,
            )

        # Update auth header
        self._client.headers["Authorization"] = f"Bearer {token}"
        self._client.headers["Content-Type"] = "application/json"
        return self._client

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make GET request to DocuSign Rooms API."""
        client = await self._get_client()
        account_id = self.settings.docusign_account_id

        # Prepend account ID to endpoint
        full_endpoint = f"/accounts/{account_id}{endpoint}"

        response = await client.get(full_endpoint, params=params)
        response.raise_for_status()

        data = response.json()
        logger.debug("docusign_api_get", endpoint=endpoint)
        return data

    async def post(self, endpoint: str, json_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make POST request to DocuSign Rooms API."""
        client = await self._get_client()
        account_id = self.settings.docusign_account_id

        full_endpoint = f"/accounts/{account_id}{endpoint}"

        response = await client.post(full_endpoint, json=json_data)
        response.raise_for_status()

        data = response.json()
        logger.debug("docusign_api_post", endpoint=endpoint)
        return data

    async def put(self, endpoint: str, json_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make PUT request to DocuSign Rooms API."""
        client = await self._get_client()
        account_id = self.settings.docusign_account_id

        full_endpoint = f"/accounts/{account_id}{endpoint}"

        response = await client.put(full_endpoint, json=json_data)
        response.raise_for_status()

        data = response.json()
        logger.debug("docusign_api_put", endpoint=endpoint)
        return data

    async def delete(self, endpoint: str) -> bool:
        """Make DELETE request to DocuSign Rooms API."""
        client = await self._get_client()
        account_id = self.settings.docusign_account_id

        full_endpoint = f"/accounts/{account_id}{endpoint}"

        response = await client.delete(full_endpoint)
        response.raise_for_status()

        logger.debug("docusign_api_delete", endpoint=endpoint)
        return True

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton client
_client: DocuSignClient | None = None


def get_docusign_client() -> DocuSignClient:
    """Get the DocuSign API client instance."""
    global _client
    if _client is None:
        _client = DocuSignClient()
    return _client
