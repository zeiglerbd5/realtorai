"""Maine public-records support documents: tax map, tax card, flood map.

For every new listing the TC pulls three reference documents into the room:

  1. Tax map with the parcel pinned (town GIS / assessor maps)
  2. Tax card (most Maine towns publish via Vision Government Solutions)
  3. FEMA flood map / flood zone determination

These sources have no uniform API, so this module builds the correct lookup
URLs from the transaction record and emits a markdown "pull sheet" artifact
per document — the exact parcel references, links, and verification notes a
human (or a future browser-automation step) needs to complete the pull. The
artifacts are uploaded to the Transaction Room alongside the eventual PDFs.
"""

from pathlib import Path
from urllib.parse import quote_plus

import structlog
from pydantic import BaseModel

from realtorai.schemas.transaction import TransactionRecord

logger = structlog.get_logger()


class SupportingDocument(BaseModel):
    """One public-records pull for a transaction."""

    name: str
    kind: str  # tax_map | tax_card | flood_map
    source_label: str
    source_url: str
    note: str
    artifact_path: str | None = None


def _address(record: TransactionRecord) -> str:
    return " ".join(
        p
        for p in (
            record.street_address,
            record.city,
            (record.state or "").removeprefix("US-"),
            record.zip,
        )
        if p
    )


def _vision_url(record: TransactionRecord) -> str:
    """Vision Government Solutions town database URL (covers most Maine towns)."""
    town = (record.town or record.city or "").lower().replace(" ", "")
    return f"https://gis.vgsi.com/{town}me/" if town else "https://www.vgsi.com/vision-property-cards/"


def build_supporting_documents(record: TransactionRecord) -> list[SupportingDocument]:
    """Build the three standard pulls with correct source URLs and parcel refs."""
    address = _address(record)
    parcel = record.parcel_id or record.map_lot or "(parcel ID not yet on record)"
    town = record.town or record.city or "(town unknown)"
    maps_pin = f"https://www.google.com/maps/search/?api=1&query={quote_plus(address)}"

    return [
        SupportingDocument(
            name=f"Tax Map — {parcel}",
            kind="tax_map",
            source_label=f"Town of {town} assessor tax maps",
            source_url=_vision_url(record),
            note=(
                f"Locate parcel {parcel} on the town tax map and mark the pin. "
                f"Cross-check the lot against the deed description. Map pin: {maps_pin}"
            ),
        ),
        SupportingDocument(
            name=f"Tax Card — {address or parcel}",
            kind="tax_card",
            source_label=f"Vision Government Solutions ({town})",
            source_url=_vision_url(record),
            note=(
                f"Pull the property card for parcel {parcel}. Verify assessed value"
                + (
                    f" (record shows ${record.assessed_value:,.0f})"
                    if record.assessed_value is not None
                    else ""
                )
                + ", year built, land area, and building details against the record."
            ),
        ),
        SupportingDocument(
            name=f"Flood Map — {address or parcel}",
            kind="flood_map",
            source_label="FEMA Map Service Center",
            source_url=f"https://msc.fema.gov/portal/search?AddressQuery={quote_plus(address)}",
            note=(
                "Print the FIRMette for the parcel and note the flood zone. "
                "If in an A/AE/VE zone, flag flood-insurance disclosure to the agent."
            ),
        ),
    ]


def write_pull_sheets(
    documents: list[SupportingDocument],
    record: TransactionRecord,
    out_dir: Path,
) -> list[SupportingDocument]:
    """Write a markdown pull sheet per document; sets artifact_path on each."""
    out_dir.mkdir(parents=True, exist_ok=True)
    address = _address(record)
    for doc in documents:
        lines = [
            f"# {doc.name}",
            "",
            f"**Property:** {address}",
            f"**Parcel:** {record.parcel_id or record.map_lot or 'n/a'}",
            f"**County:** {record.county or 'n/a'}",
            (
                f"**Deed:** Book {record.deed_book}, Page {record.deed_page}"
                if record.deed_book
                else "**Deed:** reference not yet on record"
            ),
            "",
            f"**Source:** [{doc.source_label}]({doc.source_url})",
            "",
            "## Instructions",
            "",
            doc.note,
        ]
        path = out_dir / f"{doc.kind}.md"
        path.write_text("\n".join(lines) + "\n")
        doc.artifact_path = str(path)
    logger.info("pull_sheets_written", count=len(documents), dir=str(out_dir))
    return documents
