"""Spark API integration for FlexMLS/MREIS MLS data.

Provides OAuth authentication and access to MLS listings,
property data, and market statistics via RESO-compliant API.

Features:
- OAuth 2.0 authentication with token refresh
- Listing search, retrieval, and photo access
- MLS Feeder for accumulating listing data
- Listing submission to create draft listings in FlexMLS
- Buyer alerts for monitoring new listings matching criteria
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
from realtorai.integrations.spark.submission import (
    create_draft_listing,
    submit_listing_with_photos,
    upload_listing_photos,
    get_listing_status,
    validate_feeder_for_submission,
    feeder_to_spark_payload,
    ListingSubmissionError,
)
from realtorai.integrations.spark.buyer_alerts import (
    BuyerCriteria,
    get_buyer_criteria,
    save_buyer_criteria,
    update_buyer_criteria,
    create_saved_search,
    search_new_listings,
    check_for_new_matches,
    run_manual_scan,
    buyer_alert_scanner,
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
    # Listing Submission
    "create_draft_listing",
    "submit_listing_with_photos",
    "upload_listing_photos",
    "get_listing_status",
    "validate_feeder_for_submission",
    "feeder_to_spark_payload",
    "ListingSubmissionError",
    # Buyer Alerts
    "BuyerCriteria",
    "get_buyer_criteria",
    "save_buyer_criteria",
    "update_buyer_criteria",
    "create_saved_search",
    "search_new_listings",
    "check_for_new_matches",
    "run_manual_scan",
    "buyer_alert_scanner",
]
