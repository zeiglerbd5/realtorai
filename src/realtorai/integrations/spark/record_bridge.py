"""Bridge from the canonical TransactionRecord to the MLS feeder.

The MLS feeder (mls_feeder.py) is the accumulator the submission pipeline
validates and converts to a Spark payload. This module populates it from a
TransactionRecord, so the listing workflow needs a single source of truth:

    TransactionRecord --record_to_feeder_updates()--> feeder --> Spark payload
"""

import re
from decimal import Decimal
from typing import Any

from realtorai.schemas.transaction import TransactionRecord

# Street-suffix vocabulary for splitting "22 Penobscot Street" into the
# number/name/suffix parts Spark expects.
_SUFFIXES = (
    "Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Court|Ct|Circle|Cir|"
    "Boulevard|Blvd|Terrace|Ter|Place|Pl|Way|Highway|Hwy|Route|Rte|Trail|Trl|Loop"
)
_ADDRESS_RE = re.compile(
    rf"^\s*(?P<number>\d+[A-Za-z]?)\s+(?P<name>.+?)(?:\s+(?P<suffix>{_SUFFIXES}))?\.?\s*$",
    re.IGNORECASE,
)


def split_street_address(street_address: str) -> dict[str, str | None]:
    """Split a street address into number / name / suffix parts."""
    match = _ADDRESS_RE.match(street_address or "")
    if not match:
        return {"street_number": None, "street_name": street_address or None, "street_suffix": None}
    return {
        "street_number": match.group("number"),
        "street_name": match.group("name"),
        "street_suffix": match.group("suffix"),
    }


def _split_bathrooms(bathrooms: Decimal | None) -> tuple[int | None, int | None]:
    """Split a decimal bath count into (full, half). 2.5 -> (2, 1)."""
    if bathrooms is None:
        return None, None
    full = int(bathrooms)
    half = 1 if (bathrooms - full) > 0 else 0
    return full, half


# Canonical transaction_type -> feeder property type (submission.PROPERTY_TYPE_MAP keys)
_PROPERTY_TYPE_BRIDGE = {
    "Residential": "Residential",
    "Multi-Family": "Multi-Family",
    "Commercial": "Commercial",
    "Land": "Land",
}


def record_to_feeder_updates(record: TransactionRecord) -> dict[str, Any]:
    """Build an MLS-feeder `updates` dict from a TransactionRecord.

    Only fields present on the record are included, so this composes with
    data already accumulated in the feeder from other sources.
    """
    full_baths, half_baths = _split_bathrooms(record.bathrooms)

    address: dict[str, Any] = {}
    if record.street_address:
        address.update(split_street_address(record.street_address))
    if record.city:
        address["city"] = record.city
    if record.state:
        address["state"] = record.state.removeprefix("US-")
    if record.zip:
        address["postal_code"] = record.zip
    if record.county:
        address["county"] = record.county

    prop: dict[str, Any] = {}
    if record.transaction_type in _PROPERTY_TYPE_BRIDGE:
        prop["type"] = _PROPERTY_TYPE_BRIDGE[record.transaction_type]
    if record.year_built is not None:
        prop["year_built"] = record.year_built
    if record.bedrooms is not None:
        prop["bedrooms"] = record.bedrooms
    if full_baths is not None:
        prop["bathrooms_full"] = full_baths
        prop["bathrooms_half"] = half_baths
    if record.square_footage is not None:
        prop["living_area_sqft"] = int(record.square_footage)
    if record.lot_size_sqft is not None:
        prop["lot_size_sqft"] = int(record.lot_size_sqft)
    if record.lot_size_acres is not None:
        prop["lot_size_acres"] = float(record.lot_size_acres)
    if record.garage_spaces is not None:
        prop["garage_spaces"] = record.garage_spaces
    if record.garage is not None:
        prop["garage_yn"] = record.garage
    if record.rooms_total is not None:
        prop["rooms_total"] = record.rooms_total
    if record.fireplaces_total is not None:
        prop["fireplaces_total"] = record.fireplaces_total

    listing: dict[str, Any] = {}
    if record.estimated_sale_price is not None:
        listing["price"] = int(record.estimated_sale_price)
    if record.effective_date is not None:
        listing["list_date"] = record.effective_date.isoformat()
    if record.listing_expiration_date is not None:
        listing["expiration_date"] = record.listing_expiration_date.isoformat()
    if record.listing_status is not None:
        listing["status"] = record.listing_status

    features: dict[str, Any] = {}
    if record.water_source is not None:
        features["water_source"] = record.water_source
    if record.sewer is not None:
        features["sewer"] = record.sewer

    financial: dict[str, Any] = {}
    if record.annual_tax_amount is not None:
        financial["tax_amount"] = int(record.annual_tax_amount)
    if record.tax_year is not None:
        financial["tax_year"] = record.tax_year

    marketing: dict[str, Any] = {}
    if record.comments:
        # Working notes double as a first-draft private description until an
        # agent-reviewed public_remarks is written.
        marketing["private_remarks"] = record.comments

    updates: dict[str, Any] = {}
    if address:
        updates["address"] = address
    if prop:
        updates["property"] = prop
    if listing:
        updates["listing"] = listing
    if features:
        updates["features"] = features
    if financial:
        updates["financial"] = financial
    if marketing:
        updates["marketing"] = marketing
    return updates
