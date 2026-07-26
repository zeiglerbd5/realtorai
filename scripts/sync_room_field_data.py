"""End-to-end smoke test: canonical TransactionRecord <-> DocuSign Room field_data.

Walks the full loop:
    1. Construct a sample TransactionRecord with realistic Maine data.
    2. Translate to DocuSign Rooms payload via the field mapper.
    3. PUT to a real sandbox room (default: room 1938258).
    4. GET the room field data back.
    5. Translate back to TransactionRecord.
    6. Diff to verify what round-tripped vs. what was dropped.

Usage:
    python scripts/sync_room_field_data.py                  # use default room
    python scripts/sync_room_field_data.py <room_id>        # specify room
"""

import asyncio
import sys
from datetime import date
from decimal import Decimal

from realtorai.integrations.docusign.field_mapper import (
    SCALAR_MAP,
    from_room_field_data,
    to_room_field_data,
)
from realtorai.integrations.docusign.rooms import (
    get_room_field_data,
    update_room_field_data,
)
from realtorai.schemas.transaction import Party, TransactionRecord

DEFAULT_ROOM_ID = 1938258  # 123 Main St, Boston (existing sandbox room)


def sample_record() -> TransactionRecord:
    """A representative Maine transaction record."""
    return TransactionRecord(
        mls_number="1234567",
        transaction_type="Residential",
        representation_side="Listing",
        street_address="42 Penobscot St",
        city="Bangor",
        town="Bangor",
        state="US-ME",
        zip="04401",
        county="Penobscot",
        parcel_id="045-012",
        map_lot="Map 45 Lot 12",  # canonical-only
        deed_book="14823",         # canonical-only
        deed_page="217",           # canonical-only
        year_built=1962,
        bedrooms=3,
        bathrooms=Decimal("1.5"),
        lot_size_acres=Decimal("0.34"),
        effective_date=date(2026, 6, 15),
        estimated_closing_date=date(2026, 8, 1),
        inspection_deadline=date(2026, 6, 25),
        financing_commitment_deadline=date(2026, 7, 20),
        estimated_sale_price=Decimal("295000"),
        emd_amount=Decimal("5000"),
        entity_holding_emd="The Agency",
        # financing_type omitted: DocuSign expects a select-list value
        # ("Conventional", "FHA", "VA", etc.) — needs separate enum mapping
        # in a follow-up pass.
        title_provider="Penobscot Title Co.",
        mortgage_provider="Bangor Savings Bank",
        seller_1=Party(
            name="Jane Doe",
            email="jane.doe@example.com",
            cell_phone="207-555-0142",
        ),
        buyer_1=Party(
            name="John Smith",
            email="john.smith@example.com",
            cell_phone="207-555-0188",
        ),
        listing_agent_1=Party(
            name="Agent One",
            company="The Agency",
            email="agent.one@agency.example",
        ),
    )


def diff_records(before: TransactionRecord, after: TransactionRecord) -> list[str]:
    """Compare two records field-by-field. Returns list of mismatch descriptions."""
    mismatches: list[str] = []
    b = before.model_dump()
    a = after.model_dump()
    for key, before_val in b.items():
        after_val = a.get(key)
        if before_val is None and after_val is None:
            continue
        # Empty Party objects come back as Party() — compare via model_dump
        if isinstance(before_val, dict) and isinstance(after_val, dict):
            if all(v is None for v in before_val.values()) and all(
                v is None for v in after_val.values()
            ):
                continue
        if before_val != after_val:
            mismatches.append(f"  {key}: sent={before_val!r}  back={after_val!r}")
    return mismatches


async def main() -> int:
    room_id = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ROOM_ID

    print(f"=== Sync test against room {room_id} ===\n")

    # 1. Build canonical record
    record = sample_record()
    print(f"Built sample record:")
    print(f"  property: {record.street_address}, {record.city}, {record.state} {record.zip}")
    print(f"  effective: {record.effective_date}  closing: {record.estimated_closing_date}")
    print(f"  price: ${record.estimated_sale_price}  EMD: ${record.emd_amount}")
    print(f"  seller: {record.seller_1.name}  buyer: {record.buyer_1.name}\n")

    # 2. Translate to DocuSign payload
    payload = to_room_field_data(record)
    print(f"Mapped to {len(payload)} DocuSign fields. Coverage:")
    print(f"  scalars in record  : {sum(1 for k in SCALAR_MAP if getattr(record, k, None) is not None)}")
    print(f"  scalars in payload : {sum(1 for k in payload if not isinstance(payload[k], dict))}")
    print(f"  party objects      : {sum(1 for v in payload.values() if isinstance(v, dict))}\n")

    # 3. PUT to room
    print(f"Writing to room {room_id}...")
    ok = await update_room_field_data(room_id, payload)
    if not ok:
        print("  FAILED — see error above")
        return 1
    print("  OK\n")

    # 4. GET back
    print(f"Reading field data from room {room_id}...")
    data_back = await get_room_field_data(room_id)
    print(f"  Got {len(data_back)} top-level keys\n")

    # 5. Translate back
    record_back = from_room_field_data(data_back)

    # 6. Diff
    print("=== Diff (sent vs received) ===")
    mismatches = diff_records(record, record_back)
    if not mismatches:
        print("  All mapped fields round-tripped cleanly. ✓\n")
    else:
        print(f"  {len(mismatches)} mismatches (canonical-only fields will show here):")
        for m in mismatches:
            print(m)
        print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
