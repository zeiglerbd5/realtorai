"""One-shot flood determination from the command line.

Wraps realtorai.integrations.fema_flood — Census geocoder + FEMA NFHL +
USGS basemap, no browser, no API keys. Runs anywhere with normal internet
access (it does NOT need Cowork or any agent sandbox).

Usage:
    python scripts/flood_lookup.py "22 Penobscot St, Orono, ME 04473"
    python scripts/flood_lookup.py "1 Main St, Belfast, ME" --out ~/Documents/floods
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

from realtorai.integrations.fema_flood import fetch_flood_determination


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "lookup"


async def run(address: str, out_root: Path) -> int:
    out_dir = out_root / _slug(address)
    try:
        det, map_path, md_path = await fetch_flood_determination(address, out_dir)
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        print(
            "Check the address spelling (the Census geocoder needs a street "
            "address, not a map/lot reference) and network access to "
            "geocoding.geo.census.gov / hazards.fema.gov.",
            file=sys.stderr,
        )
        return 1

    print(f"Address : {det.matched_address or det.address}")
    print(f"Zone    : {det.flood_zone or 'unknown'}"
          + (f" — {det.zone_subtype.title()}" if det.zone_subtype else ""))
    if det.in_sfha is None:
        sfha = "unknown"
    else:
        sfha = "YES — flag flood insurance" if det.in_sfha else "No"
    print(f"SFHA    : {sfha}")
    print(f"Panel   : {det.firm_panel or 'n/a'} (eff. {det.panel_effective_date or 'n/a'})")
    if det.static_bfe is not None:
        print(f"BFE     : {det.static_bfe}")
    print(f"Map     : {map_path}")
    print(f"Report  : {md_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="FEMA flood determination for an address")
    parser.add_argument("address", help='e.g. "22 Penobscot St, Orono, ME 04473"')
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/flood_lookups"),
        help="Output root directory (default: data/flood_lookups)",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.address, args.out.expanduser()))


if __name__ == "__main__":
    sys.exit(main())
