"""Spark API integration for FlexMLS/MREIS MLS data.

Provides OAuth authentication and access to MLS listings,
property data, and market statistics via RESO-compliant API.
"""

from realtorai.integrations.spark.auth import spark_auth, SparkAuth
from realtorai.integrations.spark.client import get_spark_client, SparkClient
from realtorai.integrations.spark.listings import (
    search_listings,
    get_listing,
    get_listing_photos,
    find_comps,
    get_market_stats,
    format_listing_summary,
)

__all__ = [
    # Auth
    "spark_auth",
    "SparkAuth",
    # Client
    "get_spark_client",
    "SparkClient",
    # Listings
    "search_listings",
    "get_listing",
    "get_listing_photos",
    "find_comps",
    "get_market_stats",
    "format_listing_summary",
]
