"""Spark API buyer alerts - monitors MLS for new listings matching buyer criteria.

This module manages saved searches in the Spark API and periodically scans
for new listings that match buyer client preferences. When matches are found,
it creates pending items in the dashboard for agent review.

Workflow:
1. Create/update saved searches for each buyer client based on their criteria
2. Periodically poll for new listings matching each search
3. Create dashboard notifications for new matches
4. Track which listings have already been shown to avoid duplicates

API Reference: https://sparkplatform.com/docs/api_services/saved_searches
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from realtorai.integrations.spark.client import get_spark_client
from realtorai.storage.database import get_database

logger = structlog.get_logger()


# Default polling interval (can be overridden in settings)
DEFAULT_POLL_INTERVAL_MINUTES = 30

# File to track seen listings per buyer
SEEN_LISTINGS_DIR = Path("data/buyer_alerts")


class BuyerCriteria:
    """Buyer search criteria for MLS alerts."""

    def __init__(
        self,
        client_id: int,
        client_name: str,
        # Location
        cities: list[str] | None = None,
        postal_codes: list[str] | None = None,
        counties: list[str] | None = None,
        # Price
        min_price: int | None = None,
        max_price: int | None = None,
        # Property
        property_types: list[str] | None = None,
        min_beds: int | None = None,
        max_beds: int | None = None,
        min_baths: int | None = None,
        min_sqft: int | None = None,
        max_sqft: int | None = None,
        min_year_built: int | None = None,
        # Features
        garage_required: bool = False,
        pool_required: bool = False,
        # Custom SparkQL filter (advanced)
        custom_filter: str | None = None,
    ):
        self.client_id = client_id
        self.client_name = client_name
        self.cities = cities or []
        self.postal_codes = postal_codes or []
        self.counties = counties or []
        self.min_price = min_price
        self.max_price = max_price
        self.property_types = property_types or []
        self.min_beds = min_beds
        self.max_beds = max_beds
        self.min_baths = min_baths
        self.min_sqft = min_sqft
        self.max_sqft = max_sqft
        self.min_year_built = min_year_built
        self.garage_required = garage_required
        self.pool_required = pool_required
        self.custom_filter = custom_filter

    def to_sparkql(self) -> str:
        """Convert criteria to SparkQL filter string.

        Returns:
            SparkQL filter expression for the Spark API
        """
        filters = []

        # Always filter for active listings
        filters.append("MlsStatus Eq 'Active'")

        # Location filters (OR within category, AND between categories)
        if self.cities:
            city_filters = [f"City Eq '{city}'" for city in self.cities]
            filters.append(f"({' Or '.join(city_filters)})")

        if self.postal_codes:
            zip_filters = [f"PostalCode Eq '{z}'" for z in self.postal_codes]
            filters.append(f"({' Or '.join(zip_filters)})")

        if self.counties:
            county_filters = [f"CountyOrParish Eq '{c}'" for c in self.counties]
            filters.append(f"({' Or '.join(county_filters)})")

        # Price range
        if self.min_price:
            filters.append(f"ListPrice Ge {self.min_price}")
        if self.max_price:
            filters.append(f"ListPrice Le {self.max_price}")

        # Property types
        if self.property_types:
            type_filters = [f"PropertyType Eq '{t}'" for t in self.property_types]
            filters.append(f"({' Or '.join(type_filters)})")

        # Bedrooms
        if self.min_beds:
            filters.append(f"BedroomsTotal Ge {self.min_beds}")
        if self.max_beds:
            filters.append(f"BedroomsTotal Le {self.max_beds}")

        # Bathrooms
        if self.min_baths:
            filters.append(f"BathroomsFull Ge {self.min_baths}")

        # Square footage
        if self.min_sqft:
            filters.append(f"LivingArea Ge {self.min_sqft}")
        if self.max_sqft:
            filters.append(f"LivingArea Le {self.max_sqft}")

        # Year built
        if self.min_year_built:
            filters.append(f"YearBuilt Ge {self.min_year_built}")

        # Garage
        if self.garage_required:
            filters.append("GarageSpaces Ge 1")

        # Custom filter (appended as-is)
        if self.custom_filter:
            filters.append(f"({self.custom_filter})")

        return " And ".join(filters)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "client_id": self.client_id,
            "client_name": self.client_name,
            "cities": self.cities,
            "postal_codes": self.postal_codes,
            "counties": self.counties,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "property_types": self.property_types,
            "min_beds": self.min_beds,
            "max_beds": self.max_beds,
            "min_baths": self.min_baths,
            "min_sqft": self.min_sqft,
            "max_sqft": self.max_sqft,
            "min_year_built": self.min_year_built,
            "garage_required": self.garage_required,
            "pool_required": self.pool_required,
            "custom_filter": self.custom_filter,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BuyerCriteria":
        """Create from dictionary."""
        return cls(**data)

    def summary(self) -> str:
        """Human-readable summary of criteria."""
        parts = []

        if self.cities:
            parts.append(f"Cities: {', '.join(self.cities)}")
        if self.postal_codes:
            parts.append(f"ZIP: {', '.join(self.postal_codes)}")
        if self.min_price or self.max_price:
            price_range = f"${self.min_price or 0:,} - ${self.max_price or 999999999:,}"
            parts.append(f"Price: {price_range}")
        if self.min_beds:
            parts.append(f"{self.min_beds}+ beds")
        if self.min_baths:
            parts.append(f"{self.min_baths}+ baths")
        if self.min_sqft:
            parts.append(f"{self.min_sqft:,}+ sqft")

        return " | ".join(parts) if parts else "No criteria set"


async def create_saved_search(
    criteria: BuyerCriteria,
) -> dict[str, Any]:
    """Create a saved search in Spark API for buyer criteria.

    Args:
        criteria: Buyer search criteria

    Returns:
        Dict with search ID and details
    """
    client = get_spark_client()

    search_name = f"RealtorAI: {criteria.client_name}"
    filter_string = criteria.to_sparkql()

    logger.info(
        "creating_saved_search",
        client_id=criteria.client_id,
        filter_length=len(filter_string),
    )

    try:
        # Build request - Spark API uses {"D": {...}} wrapper
        from realtorai.integrations.spark.auth import spark_auth, SPARK_API_BASE
        import httpx

        token = await spark_auth.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated with Spark API")

        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.post(
                f"{SPARK_API_BASE}/savedsearches",
                json={
                    "D": {
                        "Name": search_name[:50],  # Max 50 chars
                        "Filter": filter_string,
                        "Description": f"Auto-generated for buyer {criteria.client_name}",
                    }
                },
                headers={"Authorization": f"OAuth {token}"},
            )

            data = response.json()

            if response.status_code == 200 and data.get("D", {}).get("Success"):
                result = data["D"]["Results"][0]
                search_id = result.get("Id")

                logger.info(
                    "saved_search_created",
                    client_id=criteria.client_id,
                    search_id=search_id,
                )

                return {
                    "search_id": search_id,
                    "name": search_name,
                    "filter": filter_string,
                }

            else:
                errors = data.get("D", {}).get("Errors", [])
                logger.error("saved_search_create_failed", errors=errors)
                raise RuntimeError(f"Failed to create saved search: {errors}")

    except Exception as e:
        logger.exception("saved_search_error", error=str(e))
        raise


async def get_saved_searches() -> list[dict[str, Any]]:
    """Get all saved searches for the authenticated user.

    Returns:
        List of saved search objects
    """
    client = get_spark_client()

    try:
        data = await client.get("/savedsearches")
        results = data.get("D", {}).get("Results", [])

        logger.info("saved_searches_fetched", count=len(results))
        return results

    except Exception as e:
        logger.error("saved_searches_fetch_error", error=str(e))
        return []


async def delete_saved_search(search_id: str) -> bool:
    """Delete a saved search.

    Args:
        search_id: ID of the saved search to delete

    Returns:
        True if deleted successfully
    """
    from realtorai.integrations.spark.auth import spark_auth, SPARK_API_BASE
    import httpx

    try:
        token = await spark_auth.get_access_token()
        if not token:
            return False

        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.delete(
                f"{SPARK_API_BASE}/savedsearches/{search_id}",
                headers={"Authorization": f"OAuth {token}"},
            )

            success = response.status_code in (200, 204)
            logger.info("saved_search_deleted", search_id=search_id, success=success)
            return success

    except Exception as e:
        logger.error("saved_search_delete_error", search_id=search_id, error=str(e))
        return False


async def search_new_listings(
    criteria: BuyerCriteria,
    since: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search for listings matching criteria, optionally filtered by date.

    Args:
        criteria: Buyer search criteria
        since: Only return listings modified after this time
        limit: Maximum results

    Returns:
        List of matching listings
    """
    client = get_spark_client()

    # Build filter from criteria
    filters = [criteria.to_sparkql()]

    # Add time filter if specified
    if since:
        since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
        filters.append(f"ModificationTimestamp Gt {since_str}")

    filter_string = " And ".join(filters)

    params = {
        "_filter": filter_string,
        "_limit": limit,
        "_orderby": "ModificationTimestamp Desc",
    }

    try:
        data = await client.get("/listings", params=params)
        results = data.get("D", {}).get("Results", [])

        logger.info(
            "new_listings_search",
            client_id=criteria.client_id,
            count=len(results),
            since=since.isoformat() if since else None,
        )

        return results

    except Exception as e:
        logger.error("new_listings_search_error", error=str(e))
        return []


def _get_seen_listings_path(client_id: int) -> Path:
    """Get path to seen listings file for a client."""
    SEEN_LISTINGS_DIR.mkdir(parents=True, exist_ok=True)
    return SEEN_LISTINGS_DIR / f"client_{client_id}_seen.json"


def _load_seen_listings(client_id: int) -> set[str]:
    """Load set of listing IDs already shown to a buyer."""
    path = _get_seen_listings_path(client_id)

    if not path.exists():
        return set()

    try:
        with open(path) as f:
            data = json.load(f)
            return set(data.get("listing_ids", []))
    except Exception as e:
        logger.warning("seen_listings_load_error", client_id=client_id, error=str(e))
        return set()


def _save_seen_listings(client_id: int, listing_ids: set[str]) -> None:
    """Save set of seen listing IDs."""
    path = _get_seen_listings_path(client_id)

    try:
        with open(path, "w") as f:
            json.dump({
                "listing_ids": list(listing_ids),
                "updated_at": datetime.utcnow().isoformat(),
            }, f)
    except Exception as e:
        logger.error("seen_listings_save_error", client_id=client_id, error=str(e))


async def check_for_new_matches(
    criteria: BuyerCriteria,
    create_notifications: bool = True,
) -> list[dict[str, Any]]:
    """Check for new listings matching buyer criteria.

    Compares against previously seen listings and optionally creates
    dashboard notifications for new matches.

    Args:
        criteria: Buyer search criteria
        create_notifications: Whether to create pending items in dashboard

    Returns:
        List of NEW matching listings (not previously seen)
    """
    # Get listings from last 24 hours (catches anything from last poll cycle)
    since = datetime.utcnow() - timedelta(hours=24)
    listings = await search_new_listings(criteria, since=since)

    # Filter out already-seen listings
    seen = _load_seen_listings(criteria.client_id)
    new_listings = []

    for listing in listings:
        listing_key = listing.get("ListingKey")
        if listing_key and listing_key not in seen:
            new_listings.append(listing)
            seen.add(listing_key)

    # Save updated seen list
    if new_listings:
        _save_seen_listings(criteria.client_id, seen)

    # Create notifications
    if create_notifications and new_listings:
        await _create_match_notifications(criteria, new_listings)

    logger.info(
        "buyer_alert_check",
        client_id=criteria.client_id,
        total_found=len(listings),
        new_matches=len(new_listings),
    )

    return new_listings


async def _create_match_notifications(
    criteria: BuyerCriteria,
    listings: list[dict[str, Any]],
) -> None:
    """Create dashboard pending items for matched listings.

    Args:
        criteria: Buyer criteria (contains client info)
        listings: New matching listings
    """
    db = await get_database()

    for listing in listings:
        address = listing.get("UnparsedAddress", "Unknown address")
        city = listing.get("City", "")
        price = listing.get("ListPrice", 0)
        beds = listing.get("BedroomsTotal", 0)
        baths = listing.get("BathroomsTotalInteger", 0)

        description = (
            f"New listing match: {address}, {city} - "
            f"${price:,} | {beds}bd/{baths}ba"
        )

        await db.create_pending_item(
            client_id=criteria.client_id,
            item_type="listing_match",
            description=description,
            waiting_on="agent",  # Agent needs to review and share with buyer
        )

    logger.info(
        "match_notifications_created",
        client_id=criteria.client_id,
        count=len(listings),
    )


# ----- Buyer Criteria Storage -----
# Store buyer search criteria in client data directory

def _get_buyer_criteria_path(client_id: int, name: str) -> Path:
    """Get path to buyer criteria file."""
    from realtorai.storage.client_files import get_client_dir
    client_dir = get_client_dir(client_id, name)
    return client_dir / "buyer_criteria.json"


def get_buyer_criteria(client_id: int, name: str) -> BuyerCriteria | None:
    """Load buyer criteria for a client.

    Args:
        client_id: Client database ID
        name: Client name

    Returns:
        BuyerCriteria object or None if not set
    """
    path = _get_buyer_criteria_path(client_id, name)

    if not path.exists():
        return None

    try:
        with open(path) as f:
            data = json.load(f)
            return BuyerCriteria.from_dict(data)
    except Exception as e:
        logger.error("buyer_criteria_load_error", client_id=client_id, error=str(e))
        return None


def save_buyer_criteria(
    client_id: int,
    name: str,
    criteria: BuyerCriteria,
) -> None:
    """Save buyer criteria for a client.

    Args:
        client_id: Client database ID
        name: Client name
        criteria: Buyer search criteria
    """
    path = _get_buyer_criteria_path(client_id, name)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        json.dump(criteria.to_dict(), f, indent=2)

    logger.info("buyer_criteria_saved", client_id=client_id)


def update_buyer_criteria(
    client_id: int,
    name: str,
    updates: dict[str, Any],
) -> BuyerCriteria:
    """Update buyer criteria with new values.

    Args:
        client_id: Client database ID
        name: Client name
        updates: Dict of fields to update

    Returns:
        Updated BuyerCriteria object
    """
    existing = get_buyer_criteria(client_id, name)

    if existing:
        data = existing.to_dict()
        data.update(updates)
    else:
        data = {
            "client_id": client_id,
            "client_name": name,
            **updates,
        }

    criteria = BuyerCriteria.from_dict(data)
    save_buyer_criteria(client_id, name, criteria)
    return criteria


# ----- Background Alert Scanner -----

class BuyerAlertScanner:
    """Background task that periodically scans for new listing matches.

    This runs as part of the daemon and checks all buyer clients
    for new listings matching their criteria.
    """

    def __init__(self, poll_interval_minutes: int = DEFAULT_POLL_INTERVAL_MINUTES):
        self.poll_interval = poll_interval_minutes * 60  # Convert to seconds
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background scanner."""
        if self._running:
            logger.warning("buyer_alert_scanner_already_running")
            return

        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        logger.info("buyer_alert_scanner_started", interval_minutes=self.poll_interval // 60)

    async def stop(self) -> None:
        """Stop the background scanner."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("buyer_alert_scanner_stopped")

    async def _scan_loop(self) -> None:
        """Main scanning loop."""
        while self._running:
            try:
                await self._scan_all_buyers()
            except Exception as e:
                logger.exception("buyer_alert_scan_error", error=str(e))

            # Wait for next poll
            await asyncio.sleep(self.poll_interval)

    async def _scan_all_buyers(self) -> None:
        """Scan for matches across all buyer clients."""
        from realtorai.integrations.spark.auth import spark_auth

        # Check if Spark API is connected
        if not await spark_auth.is_connected():
            logger.debug("spark_not_connected_skipping_buyer_scan")
            return

        db = await get_database()

        # Get all clients with type 'buyer'
        # TODO: Add client_type to database schema if not present
        clients = await db.get_all_clients()

        buyer_clients = [c for c in clients if c.get("client_type") == "buyer"]

        if not buyer_clients:
            logger.debug("no_buyer_clients_to_scan")
            return

        total_new = 0

        for client in buyer_clients:
            criteria = get_buyer_criteria(client["id"], client["name"])

            if not criteria:
                continue

            new_matches = await check_for_new_matches(criteria)
            total_new += len(new_matches)

        logger.info(
            "buyer_alert_scan_complete",
            buyers_checked=len(buyer_clients),
            new_matches=total_new,
        )


# Default scanner instance
buyer_alert_scanner = BuyerAlertScanner()


async def run_manual_scan(client_id: int, name: str) -> list[dict[str, Any]]:
    """Manually trigger a scan for a specific buyer client.

    Useful for testing or when buyer updates their criteria.

    Args:
        client_id: Client database ID
        name: Client name

    Returns:
        List of new matching listings
    """
    criteria = get_buyer_criteria(client_id, name)

    if not criteria:
        logger.warning("no_buyer_criteria", client_id=client_id)
        return []

    return await check_for_new_matches(criteria)
