"""The 49 MLS-required fields — Maine Listings will not save with any blank.

Mirrors docs "MLS-Required-Fields-49" (FlexMLS new-listing entry order).
This module is the single source of truth for MLS submission readiness:
the master info document's "still TBD" section, the workflow's MLS-draft
step, and feeder validation all call `missing_required()`.

Each entry maps the MLS field label to a check against the canonical
TransactionRecord. Street # / Street Name derive from `street_address`;
Map and Lot both derive from `map_lot`/`parcel_id` (Block is not required).
"""

from collections.abc import Callable
from typing import Any

from realtorai.schemas.transaction import TransactionRecord


def _street_number(record: TransactionRecord) -> Any:
    from realtorai.integrations.spark.record_bridge import split_street_address

    return split_street_address(record.street_address or "")["street_number"]


def _street_name(record: TransactionRecord) -> Any:
    from realtorai.integrations.spark.record_bridge import split_street_address

    return split_street_address(record.street_address or "")["street_name"]


def _map_lot(record: TransactionRecord) -> Any:
    return record.map_lot or record.parcel_id


def _attr(name: str) -> Callable[[TransactionRecord], Any]:
    return lambda record: getattr(record, name)


# (MLS field label, getter) in FlexMLS entry order — all 49 required fields.
REQUIRED_FIELDS: list[tuple[str, Callable[[TransactionRecord], Any]]] = [
    # Section 2 — Address & Property Sub-Type
    ("Property Sub-Type", _attr("property_sub_type")),
    ("Street #", _street_number),
    ("Street Name", _street_name),
    ("County", _attr("county")),
    ("Town", lambda r: r.town or r.city),
    ("State/Province", _attr("state")),
    ("Zip Code", _attr("zip")),
    ("Tax ID", _attr("parcel_id")),
    # Section 3 — Location Information
    ("Leased Land", _attr("leased_land")),
    ("Book", _attr("deed_book")),
    ("Page", _attr("deed_page")),
    ("Map", _map_lot),
    ("Lot", _map_lot),
    ("Zoning", _attr("zoning")),
    ("Zoning Overlay", _attr("zoning_overlay")),
    ("Association", _attr("association")),
    ("Full Tax Amount $", _attr("annual_tax_amount")),
    ("Tax Year", _attr("tax_year")),
    ("Tree Growth Y/N", _attr("tree_growth")),
    ("HERS Certified", _attr("hers_certified")),
    # Section 3 — Contract Information
    ("Status", _attr("listing_status")),
    ("Comp Listing", _attr("comp_listing")),
    ("List Date", _attr("effective_date")),
    ("Expiration Date", _attr("listing_expiration_date")),
    ("List Price", _attr("estimated_sale_price")),
    ("Showing Service Name", _attr("showing_service")),
    # Section 3 — Property Information
    ("Surveyed", _attr("surveyed")),
    ("Seasonal", _attr("seasonal")),
    ("# Rooms", _attr("rooms_total")),
    ("# Bedrooms", _attr("bedrooms")),
    ("# Fireplaces", _attr("fireplaces_total")),
    ("# Full Baths — Basement", _attr("full_baths_basement")),
    ("# Half Baths — Basement", _attr("half_baths_basement")),
    ("# Full Baths — Level 1", _attr("full_baths_level_1")),
    ("# Half Baths — Level 1", _attr("half_baths_level_1")),
    ("# Full Baths — Level 2", _attr("full_baths_level_2")),
    ("# Half Baths — Level 2", _attr("half_baths_level_2")),
    ("# Full Baths — Level 3", _attr("full_baths_level_3")),
    ("# Half Baths — Level 3", _attr("half_baths_level_3")),
    ("# Full Baths — Upper", _attr("full_baths_upper")),
    ("# Half Baths — Upper", _attr("half_baths_upper")),
    ("Year Built", _attr("year_built")),
    ("SqFt Finished Above Grade", _attr("square_footage")),
    ("SqFt Finished Below Grade", _attr("sqft_below_grade")),
    ("SqFt Source", _attr("sqft_source")),
    ("Garage", _attr("garage")),
    ("Lot Size Acres +/-", _attr("lot_size_acres")),
    ("Source of Acreage", _attr("acreage_source")),
    # Section 3 — Misc Info
    ("Listing Agreement", _attr("listing_agreement_type")),
]

assert len(REQUIRED_FIELDS) == 49, "the MLS-required list must stay at exactly 49 entries"

# The fields public records can't supply — walkthrough / seller every time
# (from the required-fields doc). Useful for routing gaps to the right ask.
SELLER_ONLY_LABELS: frozenset[str] = frozenset({
    "# Rooms",
    "# Fireplaces",
    "# Full Baths — Basement", "# Half Baths — Basement",
    "# Full Baths — Level 1", "# Half Baths — Level 1",
    "# Full Baths — Level 2", "# Half Baths — Level 2",
    "# Full Baths — Level 3", "# Half Baths — Level 3",
    "# Full Baths — Upper", "# Half Baths — Upper",
    "Surveyed", "Seasonal", "HERS Certified",
    "Showing Service Name", "Association",
})


def missing_required(record: TransactionRecord) -> list[str]:
    """MLS-required field labels still blank on the record, in entry order.

    `False`, `0`, and `Decimal(0)` are valid answers (e.g. "Leased Land: No",
    "# Fireplaces: 0") — only None/empty-string counts as missing.
    """
    missing: list[str] = []
    for label, getter in REQUIRED_FIELDS:
        value = getter(record)
        if value is None or value == "":
            if label not in missing:
                missing.append(label)
    return missing


def readiness(record: TransactionRecord) -> tuple[int, int, list[str]]:
    """(filled, total, missing labels) for the 49 required fields."""
    missing = missing_required(record)
    return 49 - len(missing), 49, missing
