"""Auto-fill from public records — fill-if-None semantics."""

from decimal import Decimal

from realtorai.fixtures import build_22_penobscot
from realtorai.integrations.fema_flood import FloodDetermination
from realtorai.integrations.registry.browntech_alis import DeedIndexRecord
from realtorai.integrations.vgsi_tax_card import TaxCard
from realtorai.schemas.mls_required import missing_required
from realtorai.schemas.transaction import TransactionRecord
from realtorai.workflows.enrichment import (
    enrich_from_deed,
    enrich_from_flood,
    enrich_from_tax_card,
)


def _card(**overrides) -> TaxCard:
    base = dict(
        town="Orono",
        pid="2202",
        source_url="https://gis.vgsi.com/oronome/Parcel.aspx?pid=2202",
        assessment_total=Decimal("264200"),
        assessment_year=2025,
        year_built=1920,
        bedrooms=6,
        living_area_sqft=3676,
        land_acres=Decimal("0.22"),
        heat_fuel="Oil",
        mblu="020/003/082",
    )
    base.update(overrides)
    return TaxCard(**base)


def _flood() -> FloodDetermination:
    return FloodDetermination(
        address="22 Penobscot St",
        latitude=44.88,
        longitude=-68.66,
        flood_zone="X",
        in_sfha=False,
        firm_panel="23019C1943D",
    )


def test_blank_record_gets_filled():
    record = TransactionRecord()
    filled = enrich_from_tax_card(record, _card())
    assert record.tax_year == 2025
    assert record.assessed_value == Decimal("264200")
    assert record.square_footage == Decimal("3676")
    assert record.sqft_source == "Public Records"   # provenance rides along
    assert record.acreage_source == "Public Records"
    assert "tax_year" in filled and "square_footage" in filled


def test_never_overwrites_existing_values():
    record = build_22_penobscot()  # already carries tax card facts
    before = record.model_dump()
    filled = enrich_from_tax_card(record, _card(year_built=1999, bedrooms=2))
    # Everything present stays untouched; only genuinely-blank fields fill
    assert record.year_built == before["year_built"] == 1920
    assert record.bedrooms == before["bedrooms"] == 6
    assert "year_built" not in filled and "bedrooms" not in filled


def test_flood_enrichment_fills_disclosure_facts():
    record = TransactionRecord()
    filled = enrich_from_flood(record, _flood())
    assert record.flood_zone == "X"
    assert record.in_sfha is False
    assert record.firm_panel == "23019C1943D"
    assert set(filled) == {"flood_zone", "in_sfha", "firm_panel"}


def test_deed_enrichment_fills_year_acquired_only():
    record = TransactionRecord()
    deed = DeedIndexRecord(
        county="Penobscot", book="16601", page="156",
        recorded_date="08-29-2022", doc_type="Deeds",
        grantees=["ROWE, MORGAN T"],
    )
    filled = enrich_from_deed(record, deed)
    assert record.year_acquired == 2022
    assert filled == ["year_acquired"]
    # Conveyance type offered is the seller's CHOICE — never auto-filled
    assert record.deed_type_offered is None


def test_enrichment_improves_mls_readiness():
    """A record missing tax-card facts gains required fields from the pull."""
    record = build_22_penobscot()
    record.tax_year = None
    record.year_built = None
    record.sqft_source = None
    before = len(missing_required(record))
    enrich_from_tax_card(record, _card())
    after = len(missing_required(record))
    assert after < before
