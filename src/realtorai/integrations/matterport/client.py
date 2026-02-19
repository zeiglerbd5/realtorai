"""Matterport GraphQL API client."""

from typing import Any

import httpx
import structlog

from realtorai.integrations.matterport.auth import matterport_auth

logger = structlog.get_logger()

# Matterport API endpoint
MATTERPORT_API_URL = "https://api.matterport.com/api/models/graph"


class MatterportClient:
    """HTTP client for Matterport GraphQL API requests."""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with auth headers."""
        credentials = await matterport_auth.get_credentials()
        if not credentials:
            raise RuntimeError("Not authenticated with Matterport")

        token, secret = credentials

        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
            )

        # Set auth headers for token-based auth
        self._client.headers["Authorization"] = f"Basic {self._encode_credentials(token, secret)}"
        self._client.headers["Content-Type"] = "application/json"
        return self._client

    def _encode_credentials(self, token: str, secret: str) -> str:
        """Encode token:secret as base64 for Basic auth."""
        import base64
        credentials = f"{token}:{secret}"
        return base64.b64encode(credentials.encode()).decode()

    async def query(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query against the Matterport API.

        Args:
            query: GraphQL query string
            variables: Optional query variables

        Returns:
            The 'data' portion of the GraphQL response

        Raises:
            RuntimeError: If not authenticated
            httpx.HTTPStatusError: If API returns error status
            ValueError: If GraphQL returns errors
        """
        client = await self._get_client()

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        response = await client.post(MATTERPORT_API_URL, json=payload)
        response.raise_for_status()

        result = response.json()

        # Check for GraphQL errors
        if "errors" in result:
            error_messages = [e.get("message", str(e)) for e in result["errors"]]
            logger.error("matterport_graphql_errors", errors=error_messages)
            raise ValueError(f"GraphQL errors: {'; '.join(error_messages)}")

        logger.debug("matterport_api_query", query_preview=query[:100])
        return result.get("data", {})

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton client
_client: MatterportClient | None = None


def get_matterport_client() -> MatterportClient:
    """Get the Matterport API client instance."""
    global _client
    if _client is None:
        _client = MatterportClient()
    return _client
