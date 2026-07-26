"""County Registry of Deeds adapters — fetch recorded deeds by book/page.

Maine's 18 registries run a handful of vendor systems, so adapters are
per-vendor, not per-county:

  - Browntech ALIS  (penobscotdeeds.com — plain HTTP, no login for search
    and watermarked view copies): Penobscot today; other Browntech counties
    are a base-URL away.
  - AcclaimWeb (records.hancockcountymaine.gov): Hancock — adapter TBD.
  - Waldo: vendor TBD.

Counties without an adapter raise LookupError; workflow callers skip the
fetch step with a note.
"""

from pathlib import Path

from realtorai.integrations.registry.browntech_alis import (
    BrowntechALIS,
    DeedIndexRecord,
)

__all__ = ["BrowntechALIS", "DeedIndexRecord", "REGISTRIES", "registry_for", "fetch_deed"]

# county (lowercase) -> adapter instance
REGISTRIES: dict[str, BrowntechALIS] = {
    "penobscot": BrowntechALIS(
        base_url="https://penobscotdeeds.com",
        county="Penobscot",
    ),
}


def registry_for(county: str | None) -> BrowntechALIS | None:
    if not county:
        return None
    return REGISTRIES.get(county.strip().lower())


async def fetch_deed(
    county: str,
    book: str,
    page: str,
    out_dir: Path,
    *,
    expect_town: str | None = None,
    expect_owner: str | None = None,
) -> tuple[DeedIndexRecord, Path, Path]:
    """Fetch a recorded deed by book/page. Returns (index record, pdf, report).

    Raises LookupError when no adapter exists for the county; ValueError when
    the document can't be found.
    """
    adapter = registry_for(county)
    if adapter is None:
        raise LookupError(f"No registry adapter for {county} County yet")
    return await adapter.fetch(
        book, page, out_dir, expect_town=expect_town, expect_owner=expect_owner
    )
