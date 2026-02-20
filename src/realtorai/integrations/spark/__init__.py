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
from realtorai.integrations.spark.mls_feeder import (
    get_mls_feeder,
    create_mls_feeder,
    update_mls_feeder,
    set_feeder_status,
    link_matterport_to_feeder,
    update_photos_in_feeder,
    get_feeder_completeness,
    format_feeder_summary,
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
    # MLS Feeder
    "get_mls_feeder",
    "create_mls_feeder",
    "update_mls_feeder",
    "set_feeder_status",
    "link_matterport_to_feeder",
    "update_photos_in_feeder",
    "get_feeder_completeness",
    "format_feeder_summary",
]
