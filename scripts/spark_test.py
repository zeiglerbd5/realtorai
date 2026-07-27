#!/usr/bin/env python3
"""Test Spark API integration.

Usage:
    python scripts/spark_test.py status      # Check connection status
    python scripts/spark_test.py connect     # Authenticate with Spark API
    python scripts/spark_test.py disconnect  # Clear credentials
    python scripts/spark_test.py search      # Search active listings
    python scripts/spark_test.py market      # Get market stats
    python scripts/spark_test.py submit      # Test listing submission (dry run)
    python scripts/spark_test.py buyer       # Test buyer alert setup
    python scripts/spark_test.py fields      # Explore standard fields
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from realtorai.integrations.spark import (
    # New buyer alert features
    BuyerCriteria,
    feeder_to_spark_payload,
    format_listing_summary,
    get_market_stats,
    get_mls_feeder,
    search_listings,
    spark_auth,
    # New submission features
    validate_feeder_for_submission,
)


async def check_status():
    """Check Spark API connection status."""
    print("Spark API Status")
    print("-" * 40)

    configured = await spark_auth.is_configured()
    print(f"Configured: {configured}")

    if not configured:
        print("\nMissing credentials. Set these in .env:")
        print("  SPARK_CLIENT_ID=your_client_id")
        print("  SPARK_CLIENT_SECRET=your_client_secret")
        print("  (or SPARK_DEMO_TOKEN for testing with example data)")
        print("\nGet credentials at: https://sparkplatform.com/")
        return

    if spark_auth.is_demo_mode:
        print("Mode: DEMO (example data only)")
    else:
        print("Mode: LIVE (OAuth)")

    connected = await spark_auth.is_connected()
    print(f"Connected: {connected}")

    if not connected:
        print("\nNot authenticated. Run: python scripts/spark_test.py connect")


async def connect():
    """Authenticate with Spark API."""
    print("Connecting to Spark API...")
    print("This will open a browser for OAuth authentication.\n")

    if not await spark_auth.is_configured():
        print("Error: Spark API not configured.")
        print("Set SPARK_CLIENT_ID and SPARK_CLIENT_SECRET in .env")
        return False

    success = await spark_auth.connect()

    if success:
        print("\nSuccess! Connected to Spark API.")
    else:
        print("\nFailed to connect. Check credentials and try again.")

    return success


async def disconnect():
    """Clear Spark API credentials."""
    await spark_auth.disconnect()
    print("Disconnected from Spark API. Credentials cleared.")


async def search_demo():
    """Demo listing search."""
    if not await spark_auth.is_connected():
        print("Not connected. Run: python scripts/spark_test.py connect")
        return

    print("Searching for active listings...")
    print("-" * 40)

    # Search for listings (adjust filters as needed)
    results = await search_listings(
        status="Active",
        limit=5,
    )

    if not results:
        print("No results found.")
        return

    print(f"Found {len(results)} listings:\n")

    for listing in results:
        print(format_listing_summary(listing))
        print()


async def market_stats_demo():
    """Demo market stats."""
    if not await spark_auth.is_connected():
        print("Not connected. Run: python scripts/spark_test.py connect")
        return

    city = input("Enter city name: ").strip()
    if not city:
        print("City required.")
        return

    print(f"\nFetching market stats for {city}...")
    stats = await get_market_stats(city=city)

    print(f"\nMarket Statistics for {city}")
    print("-" * 40)
    print(f"Active listings: {stats['active_count']}")
    print(f"Sold (last 30 days): {stats['sold_last_30_days']}")
    print(f"Median list price: ${stats['median_list_price']:,}")
    print(f"Median sold price: ${stats['median_sold_price']:,}")


async def submit_demo():
    """Demo listing submission (dry run - validates only)."""
    print("MLS Listing Submission Test")
    print("-" * 40)

    client_id = input("Enter client ID: ").strip()
    if not client_id.isdigit():
        print("Invalid client ID")
        return

    client_id = int(client_id)

    # Need to get client name from database
    from realtorai.storage.database import get_database
    db = await get_database()
    client = await db.get_client(client_id)

    if not client:
        print(f"Client {client_id} not found")
        return

    name = client["name"]
    print(f"\nClient: {name}")

    # Check if feeder exists
    feeder = get_mls_feeder(client_id, name)
    if not feeder:
        print("No MLS feeder found for this client")
        return

    print(f"Feeder status: {feeder.get('status')}")

    # Validate
    print("\nValidating feeder...")
    is_valid, errors = await validate_feeder_for_submission(client_id, name)

    if is_valid:
        print("Validation PASSED")
    else:
        print("Validation FAILED:")
        for err in errors:
            print(f"  - {err}")
        return

    # Show what would be submitted
    print("\nSpark API payload preview:")
    payload = feeder_to_spark_payload(feeder)
    for key, value in sorted(payload.items()):
        print(f"  {key}: {value}")

    # Check if connected
    if not await spark_auth.is_connected():
        print("\n[DRY RUN] Not connected to Spark API")
        print("Once connected, run this again to actually submit")
    else:
        confirm = input("\nSubmit to FlexMLS as draft? (y/N): ").strip().lower()
        if confirm == 'y':
            from realtorai.integrations.spark import submit_listing_with_photos
            result = await submit_listing_with_photos(client_id, name)
            print(f"\nSubmission result: {result}")
        else:
            print("Submission cancelled")


async def buyer_demo():
    """Demo buyer alert setup."""
    print("Buyer Alert Setup Demo")
    print("-" * 40)

    # Create sample criteria
    print("\nCreating sample buyer criteria...")

    criteria = BuyerCriteria(
        client_id=1,
        client_name="Demo Buyer",
        cities=["Boston", "Cambridge"],
        min_price=400000,
        max_price=800000,
        min_beds=2,
        min_baths=1,
        property_types=["Residential", "Condo"],
    )

    print(f"\nSummary: {criteria.summary()}")
    print(f"\nSparkQL filter:\n{criteria.to_sparkql()}")

    if await spark_auth.is_connected():
        search = input("\nSearch for matching listings? (y/N): ").strip().lower()
        if search == 'y':
            from realtorai.integrations.spark import search_new_listings
            results = await search_new_listings(criteria, limit=5)
            print(f"\nFound {len(results)} listings:")
            for listing in results:
                print(format_listing_summary(listing))
                print()
    else:
        print("\n[Not connected] Connect to Spark API to search")


async def fields_demo():
    """Explore available standard fields."""
    if not await spark_auth.is_connected():
        print("Not connected. Run: python scripts/spark_test.py connect")
        return

    print("Fetching standard fields...")

    from realtorai.integrations.spark.client import get_spark_client
    client = get_spark_client()

    try:
        data = await client.get("/standardfields")
        fields = data.get("D", {}).get("Results", [])

        print(f"\nFound {len(fields)} standard fields:")
        print("-" * 40)

        # Show first 20 fields
        for field in fields[:20]:
            name = field.get("Label", "?")
            ftype = field.get("Type", "?")
            searchable = "searchable" if field.get("Searchable") else ""
            print(f"  {name:<30} {ftype:<15} {searchable}")

        if len(fields) > 20:
            print(f"\n  ... and {len(fields) - 20} more fields")

    except Exception as e:
        print(f"Error: {e}")


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == "status":
        await check_status()
    elif command == "connect":
        await connect()
    elif command == "disconnect":
        await disconnect()
    elif command == "search":
        await search_demo()
    elif command == "market":
        await market_stats_demo()
    elif command == "submit":
        await submit_demo()
    elif command == "buyer":
        await buyer_demo()
    elif command == "fields":
        await fields_demo()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
