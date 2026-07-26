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
        """Get the Rooms API base URL.

        Demo: https://demo.rooms.docusign.com  |  Prod: https://rooms.docusign.com
        """
        base = self.settings.docusign_base_uri.rstrip("/")
        return f"{base}/restapi/v2"

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

    async def post_multipart(
        self, endpoint: str, file_name: str, file_content: bytes
    ) -> dict[str, Any]:
        """Make a multipart/form-data POST (document uploads)."""
        token = await docusign_auth.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated with DocuSign")

        account_id = self.settings.docusign_account_id
        url = f"{self._get_base_url()}/accounts/{account_id}{endpoint}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (file_name, file_content)},
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

        logger.debug("docusign_api_post_multipart", endpoint=endpoint)
        return data

    async def get_global(self, endpoint: str) -> dict[str, Any]:
        """Make a GET request to a global endpoint (no account ID prefix)."""
        token = await docusign_auth.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated with DocuSign")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._get_base_url()}{endpoint}",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton client — real or mock depending on settings.docusign_backend
_client: Any = None


def get_docusign_client() -> Any:
    """Get the Rooms API client.

    Returns the mock simulator when DOCUSIGN_BACKEND=mock (the default until
    broker API approval lands); both expose the same async interface.
    """
    global _client
    if _client is None:
        if get_settings().docusign_backend == "mock":
            from realtorai.integrations.docusign.mock import MockDocuSignClient

            _client = MockDocuSignClient()
            logger.info("docusign_client_backend", backend="mock")
        else:
            _client = DocuSignClient()
            logger.info("docusign_client_backend", backend="live")
    return _client


def reset_docusign_client() -> None:
    """Drop the cached client (tests / backend switches)."""
    global _client
    _client = None
