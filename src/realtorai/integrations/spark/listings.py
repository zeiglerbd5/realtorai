"""Spark API listings and property data.

Provides functions for searching MLS listings, retrieving property details,
and finding comparable properties.
"""

from typing import Any
from datetime import datetime, timedelta

import structlog

from realtorai.integrations.spark.client import get_spark_client

logger = structlog.get_logger()


async def search_listings(
    city: str | None = None,
    postal_code: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    min_beds: int | None = None,
    min_baths: int | None = None,
    property_type: str | None = None,
    status: str = "Active",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Search MLS listings with filters.

    Args:
        city: City name to search in
        postal_code: ZIP code to search in
        min_price: Minimum list price
        max_price: Maximum list price
        min_beds: Minimum bedrooms
        min_baths: Minimum bathrooms
        property_type: Property type (Residential, Condo, Land, etc.)
        status: Listing status (Active, Pending, Sold, etc.)
        limit: Maximum results to return

    Returns:
        List of listing objects with property details
    """
    client = get_spark_client()

    # Build SparkQL filter
    filters = []

    if status:
        filters.append(f"MlsStatus Eq '{status}'")
    if city:
        filters.append(f"City Eq '{city}'")
    if postal_code:
        filters.append(f"PostalCode Eq '{postal_code}'")
    if min_price:
        filters.append(f"ListPrice Ge {min_price}")
    if max_price:
        filters.append(f"ListPrice Le {max_price}")
    if min_beds:
        filters.append(f"BedroomsTotal Ge {min_beds}")
    if min_baths:
        filters.append(f"BathroomsFull Ge {min_baths}")
    if property_type:
        filters.append(f"PropertyType Eq '{property_type}'")

    params = {
        "_limit": limit,
        "_orderby": "ListPrice Desc",
    }

    if filters:
        params["_filter"] = " And ".join(filters)

    try:
        data = await client.get("/listings", params=params)
        results = data.get("D", {}).get("Results", [])

        logger.info("listings_search", count=len(results), filters=len(filters))
        return results

    except Exception as e:
        logger.error("listings_search_error", error=str(e))
        return []


async def get_listing(listing_id: str) -> dict[str, Any] | None:
    """Get full details for a specific listing.

    Args:
        listing_id: The MLS listing ID

    Returns:
        Full listing object or None if not found
    """
    client = get_spark_client()

    try:
        data = await client.get(f"/listings/{listing_id}")
        result = data.get("D", {}).get("Results", [])

        if result:
            logger.info("listing_retrieved", listing_id=listing_id)
            return result[0]
        return None

    except Exception as e:
        logger.error("listing_get_error", listing_id=listing_id, error=str(e))
        return None


async def get_listing_photos(listing_id: str) -> list[dict[str, Any]]:
    """Get photos for a listing.

    Args:
        listing_id: The MLS listing ID

    Returns:
        List of photo objects with URLs
    """
    client = get_spark_client()

    try:
        data = await client.get(f"/listings/{listing_id}/photos")
        results = data.get("D", {}).get("Results", [])

        logger.info("listing_photos", listing_id=listing_id, count=len(results))
        return results

    except Exception as e:
        logger.error("listing_photos_error", listing_id=listing_id, error=str(e))
        return []


async def find_comps(
    listing_id: str | None = None,
    address: str | None = None,
    city: str | None = None,
    price: int | None = None,
    beds: int | None = None,
    sqft: int | None = None,
    radius_miles: float = 1.0,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Find comparable sold properties.

    Can search based on a listing ID or manual criteria.

    Args:
        listing_id: Source listing ID to find comps for
        address: Street address (if no listing_id)
        city: City name
        price: Target price for comp range (+/- 20%)
        beds: Number of bedrooms (+/- 1)
        sqft: Square footage (+/- 20%)
        radius_miles: Search radius in miles
        limit: Maximum comps to return

    Returns:
        List of comparable sold listings
    """
    client = get_spark_client()

    # If listing_id provided, get the source listing first
    if listing_id:
        source = await get_listing(listing_id)
        if source:
            price = price or source.get("ListPrice")
            beds = beds or source.get("BedroomsTotal")
            sqft = sqft or source.get("LivingArea")
            city = city or source.get("City")

    # Build comp search filters (SparkQL)
    filters = ["MlsStatus Eq 'Closed'"]

    if city:
        filters.append(f"City Eq '{city}'")

    if price:
        min_price = int(price * 0.8)
        max_price = int(price * 1.2)
        filters.append(f"ClosePrice Ge {min_price}")
        filters.append(f"ClosePrice Le {max_price}")

    if beds:
        filters.append(f"BedroomsTotal Ge {beds - 1}")
        filters.append(f"BedroomsTotal Le {beds + 1}")

    if sqft:
        min_sqft = int(sqft * 0.8)
        max_sqft = int(sqft * 1.2)
        filters.append(f"LivingArea Ge {min_sqft}")
        filters.append(f"LivingArea Le {max_sqft}")

    # Only recent sales (last 6 months)
    six_months_ago = datetime.now() - timedelta(days=180)
    filters.append(f"CloseDate Ge {six_months_ago.strftime('%Y-%m-%d')}")

    params = {
        "_limit": limit,
        "_orderby": "CloseDate Desc",
        "_filter": " And ".join(filters),
    }

    try:
        data = await client.get("/listings", params=params)
        results = data.get("D", {}).get("Results", [])

        logger.info("comps_found", count=len(results), city=city)
        return results

    except Exception as e:
        logger.error("comps_search_error", error=str(e))
        return []


async def get_market_stats(
    city: str | None = None,
    postal_code: str | None = None,
) -> dict[str, Any]:
    """Get market statistics for an area.

    Args:
        city: City name
        postal_code: ZIP code

    Returns:
        Dict with market stats (active count, median price, DOM, etc.)
    """
    # Get active listings
    active = await search_listings(
        city=city,
        postal_code=postal_code,
        status="Active",
        limit=100,
    )

    # Get recent sales
    client = get_spark_client()

    filters = ["MlsStatus Eq 'Closed'"]
    if city:
        filters.append(f"City Eq '{city}'")
    if postal_code:
        filters.append(f"PostalCode Eq '{postal_code}'")

    # Last 30 days
    thirty_days_ago = datetime.now() - timedelta(days=30)
    filters.append(f"CloseDate Ge {thirty_days_ago.strftime('%Y-%m-%d')}")

    try:
        data = await client.get("/listings", params={
            "_limit": 100,
            "_filter": " And ".join(filters),
        })
        sold = data.get("D", {}).get("Results", [])

    except Exception:
        sold = []

    # Calculate stats
    active_prices = [l.get("ListPrice", 0) for l in active if l.get("ListPrice")]
    sold_prices = [l.get("ClosePrice", 0) for l in sold if l.get("ClosePrice")]

    stats = {
        "active_count": len(active),
        "sold_last_30_days": len(sold),
        "median_list_price": sorted(active_prices)[len(active_prices) // 2] if active_prices else 0,
        "median_sold_price": sorted(sold_prices)[len(sold_prices) // 2] if sold_prices else 0,
        "city": city,
        "postal_code": postal_code,
    }

    logger.info("market_stats", **stats)
    return stats


def format_listing_summary(listing: dict[str, Any]) -> str:
    """Format a listing as a human-readable summary.

    Args:
        listing: Listing object from API

    Returns:
        Formatted string summary
    """
    address = listing.get("UnparsedAddress", "Unknown address")
    city = listing.get("City", "")
    price = listing.get("ListPrice", 0)
    beds = listing.get("BedroomsTotal", 0)
    baths = listing.get("BathroomsTotalInteger", 0)
    sqft = listing.get("LivingArea", 0)
    status = listing.get("StandardStatus", "Unknown")

    return (
        f"{address}, {city}\n"
        f"${price:,} | {beds} bed, {baths} bath | {sqft:,} sqft\n"
        f"Status: {status}"
    )
