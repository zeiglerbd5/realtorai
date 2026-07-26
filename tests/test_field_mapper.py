"""Round-trip tests for the DocuSign Rooms field mapper (pure, no I/O)."""

from datetime import date
from decimal import Decimal

from realtorai.integrations.docusign.field_mapper import (
    CANONICAL_ONLY,
    SCALAR_MAP,
    from_room_field_data,
    to_room_field_data,
)
from realtorai.schemas.transaction import Party, TransactionRecord


def sample_record() -> TransactionRecord:
    return TransactionRecord(
        mls_number="1234567",
        transaction_type="Residential",
        representation_side="Listing",
        street_address="42 Penobscot St",
        city="Bangor",
        state="US-ME",
        zip="04401",
        county="Penobscot",
        parcel_id="045-012",
        map_lot="Map 45 Lot 12",  # canonical-only
        deed_book="14823",
        deed_page="217",
        year_built=1962,
        bedrooms=3,
        bathrooms=Decimal("1.5"),
        lot_size_acres=Decimal("0.34"),
        effective_date=date(2026, 6, 15),
        estimated_sale_price=Decimal("295000"),
        emd_amount=Decimal("5000"),
        seller_1=Party(name="Jane Doe", email="jane@example.com"),
        listing_agent_1=Party(name="Agent One", company="The Agency"),
    )


def test_scalar_round_trip():
    record = sample_record()
    payload = to_room_field_data(record)
    back = from_room_field_data(payload)

    for canonical in SCALAR_MAP:
        assert getattr(back, canonical) == getattr(record, canonical), canonical


def test_party_round_trip():
    record = sample_record()
    back = from_room_field_data(to_room_field_data(record))
    assert back.seller_1.name == "Jane Doe"
    assert back.seller_1.email == "jane@example.com"
    assert back.listing_agent_1.company == "The Agency"
    # Unset parties stay empty
    assert back.buyer_1.name is None


def test_canonical_only_fields_not_sent():
    payload = to_room_field_data(sample_record())
    docusign_keys = set(payload.keys())
    # None of the canonical-only field names leak into the payload
    for field in CANONICAL_ONLY:
        assert field not in docusign_keys


def test_string_typed_numerics_serialize_as_strings():
    payload = to_room_field_data(sample_record())
    assert isinstance(payload["lotSizeAcres"], str)
    assert payload["lotSizeAcres"] == "0.34"
    # Regular numerics stay numeric
    assert isinstance(payload["earnestMoneyAmount"], float)


def test_dates_strip_time_component():
    payload = to_room_field_data(sample_record())
    payload["contractDate"] = "2026-06-15T00:00:00Z"  # DocuSign sometimes adds time
    back = from_room_field_data(payload)
    assert back.effective_date == date(2026, 6, 15)
