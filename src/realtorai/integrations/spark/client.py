"""Spark API client for MLS data access.

Provides methods for querying listings, properties, and market data
from FlexMLS via the Spark API.
"""

from typing import Any

import httpx
import structlog

from realtorai.integrations.spark.auth import spark_auth

# Re-export for convenience
SPARK_API_BASE = "https://sparkapi.com/v1"

logger = structlog.get_logger()


class SparkClient:
    """HTTP client for Spark API requests."""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with auth headers."""
        token = await spark_auth.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated with Spark API")

        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=SPARK_API_BASE,
                timeout=30.0,
            )

        # Update auth header (Spark uses "OAuth" not "Bearer")
        self._client.headers["Authorization"] = f"OAuth {token}"
        return self._client

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make GET request to Spark API."""
        client = await self._get_client()

        response = await client.get(endpoint, params=params)
        response.raise_for_status()

        data = response.json()
        logger.debug("spark_api_get", endpoint=endpoint, results=len(data.get("D", {}).get("Results", [])))
        return data

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton client
_client: SparkClient | None = None


def get_spark_client() -> SparkClient:
    """Get the Spark API client instance."""
    global _client
    if _client is None:
        _client = SparkClient()
    return _client
