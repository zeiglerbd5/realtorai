"""The 49 MLS-required fields gate."""

from decimal import Decimal

from realtorai.fixtures import build_22_penobscot
from realtorai.schemas.mls_required import (
    REQUIRED_FIELDS,
    SELLER_ONLY_LABELS,
    missing_required,
    readiness,
)
from realtorai.schemas.transaction import TransactionRecord


def test_exactly_49_required_fields():
    assert len(REQUIRED_FIELDS) == 49


def test_penobscot_fixture_gaps_match_the_master_doc():
    """The fixture's TBDs mirror the hand-written doc's blocker list."""
    missing = missing_required(build_22_penobscot())
    assert missing == [
        "Property Sub-Type",       # multi-family dropdown question — confirm with MLS
        "Full Tax Amount $",       # current mill rate x assessment — CALC
        "HERS Certified",          # seller
        "Comp Listing",            # MLS
        "Showing Service Name",    # seller
    ]


def test_false_and_zero_are_valid_answers():
    """Leased Land: No and # Fireplaces: 0 must NOT count as missing."""
    record = build_22_penobscot()
    missing = missing_required(record)
    assert "Leased Land" not in missing         # False
    assert "Tree Growth Y/N" not in missing     # False
    assert "# Full Baths — Basement" not in missing  # 0
    assert "SqFt Finished Below Grade" not in missing  # Decimal(0)


def test_empty_record_missing_almost_everything():
    record = TransactionRecord()
    filled, total, missing = readiness(record)
    assert total == 49
    # state has a default (US-ME); everything else is blank
    assert filled == 1
    assert "Street #" in missing and "Listing Agreement" in missing


def test_seller_only_labels_are_required_fields():
    labels = {label for label, _ in REQUIRED_FIELDS}
    assert SELLER_ONLY_LABELS <= labels


def test_completable():
    """Filling the fixture's five gaps yields a fully-ready record."""
    record = build_22_penobscot()
    record.property_sub_type = "Single Family Residence"  # stand-in pending MLS confirm
    record.annual_tax_amount = Decimal("5230")
    record.hers_certified = "Unknown"
    record.comp_listing = False
    record.showing_service = "BrokerBay"
    assert missing_required(record) == []
    assert readiness(record) == (49, 49, [])
