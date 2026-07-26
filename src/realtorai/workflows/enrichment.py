"""Auto-fill the transaction record from fetched public records.

Every fetcher already cross-checks its data against the record; this module
closes the loop the other way — when the record is BLANK, fill it from the
authoritative source. The rule is strict **fill-if-None**: a value the
extraction (or a human) already set is never overwritten. Conflicts between
sources keep surfacing through the fetchers' cross-check reports instead.

Each function returns the list of canonical field names it filled, so
workflow steps can report "enriched: tax_year, year_built" in their detail.
"""

import re
from typing import Any

import structlog

from realtorai.schemas.transaction import TransactionRecord

logger = structlog.get_logger()


def _fill(record: TransactionRecord, field: str, value: Any, filled: list[str]) -> None:
    if value is None or value == "":
        return
    if getattr(record, field) is None:
        setattr(record, field, value)
        filled.append(field)


def enrich_from_tax_card(record: TransactionRecord, card) -> list[str]:
    """Fill from the VGSI property card (assessments, structure facts)."""
    filled: list[str] = []
    _fill(record, "assessed_value", card.assessment_total, filled)
    _fill(record, "tax_year", card.assessment_year, filled)
    _fill(record, "year_built", card.year_built, filled)
    _fill(record, "bedrooms", card.bedrooms, filled)
    _fill(record, "lot_size_acres", card.land_acres, filled)
    _fill(record, "heat_type", card.heat_fuel, filled)
    _fill(record, "parcel_id", card.mblu, filled)
    if card.living_area_sqft is not None and record.square_footage is None:
        from decimal import Decimal

        record.square_footage = Decimal(card.living_area_sqft)
        filled.append("square_footage")
    # Anything sized from the card is Public Records-sourced
    if "square_footage" in filled:
        _fill(record, "sqft_source", "Public Records", filled)
    if "lot_size_acres" in filled:
        _fill(record, "acreage_source", "Public Records", filled)
    if filled:
        logger.info("record_enriched", source="tax_card", fields=filled)
    return filled


def enrich_from_parcel(record: TransactionRecord, parcel) -> list[str]:
    """Fill from the state parcel layer (map/lot, county, town)."""
    filled: list[str] = []
    _fill(record, "map_lot", parcel.map_bk_lot, filled)
    _fill(record, "county", parcel.county, filled)
    _fill(record, "town", parcel.town, filled)
    if filled:
        logger.info("record_enriched", source="parcel_layer", fields=filled)
    return filled


def enrich_from_flood(record: TransactionRecord, determination) -> list[str]:
    """Fill disclosure section VI facts from the FEMA determination."""
    filled: list[str] = []
    _fill(record, "flood_zone", determination.flood_zone, filled)
    _fill(record, "in_sfha", determination.in_sfha, filled)
    _fill(record, "firm_panel", determination.firm_panel, filled)
    if filled:
        logger.info("record_enriched", source="fema_nfhl", fields=filled)
    return filled


def enrich_from_deed(record: TransactionRecord, deed_record) -> list[str]:
    """Fill from the registry index (year acquired; owner names)."""
    filled: list[str] = []
    if deed_record.recorded_date and record.year_acquired is None:
        match = re.search(r"(19|20)\d{2}", deed_record.recorded_date)
        if match:
            record.year_acquired = int(match.group(0))
            filled.append("year_acquired")
    # NOTE: deed_type_offered is deliberately NOT filled — the conveyance
    # type offered at sale is the seller's choice, not the current deed's type.
    if filled:
        logger.info("record_enriched", source="registry_deed", fields=filled)
    return filled
