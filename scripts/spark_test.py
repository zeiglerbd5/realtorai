#!/usr/bin/env python3
"""Test Spark API integration.

Usage:
    python scripts/spark_test.py connect     # Authenticate with Spark API
    python scripts/spark_test.py status      # Check connection status
    python scripts/spark_test.py search      # Search active listings
    python scripts/spark_test.py disconnect  # Clear credentials
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from realtorai.integrations.spark import (
    spark_auth,
    search_listings,
    get_listing,
    find_comps,
    get_market_stats,
    format_listing_summary,
)
from realtorai.config.settings import get_settings


async def check_status():
    """Check Spark API connection status."""
    settings = get_settings()

    print("Spark API Status")
    print("-" * 40)

    configured = await spark_auth.is_configured()
    print(f"Configured: {configured}")

    if not configured:
        print("\nMissing credentials. Set these in .env:")
        print("  SPARK_CLIENT_ID=your_client_id")
        print("  SPARK_CLIENT_SECRET=your_client_secret")
        print("\nGet credentials at: https://sparkplatform.com/")
        return

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
    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
