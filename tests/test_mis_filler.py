"""Master Information Sheet filler — mapping tests + fill test (template-gated)."""

from pathlib import Path

import pytest

from realtorai.documents.mis_filler import fill_master_information_sheet, mis_field_values
from realtorai.fixtures import build_22_penobscot

TEMPLATE = Path("data/templates/Master-Information-Sheet.pdf")


def test_field_mapping_from_fixture():
    record = build_22_penobscot()
    values = mis_field_values(record)

    assert values["f1_PropertyAddressCityState"] == "22 Penobscot Street, Orono, ME 04473"
    assert values["f2_ListPrice"] == "$325,000"
    assert values["f3_Status"] == "Coming Soon — No Show"
    assert values["f19_TaxIDTOWNMAPBLOCKLOT"] == "020/003/082"
    assert values["f21_DeedBook"] == "16601"
    assert values["f32_TaxYear"] == "2025"
    assert values["f33_TreeGrowth"] == "No"
    assert values["f35_ExpirationDate"] == "08/31/2026"
    assert values["f36_ListingAgreementEREA"] == "ER"
    assert values["f44_Roomsexclbaths"] == "12"
    assert values["f48_Level1FullHalf"] == "2F / 0H"
    assert values["f49_Level2FullHalf"] == "1F / 0H"
    assert values["f55_Garage"] == "Yes"
    assert values["f60_RoadFrontageft"] == "66"
    assert values["f75_OwnerofRecord"] == "Brett D. Zeigler"
    assert values["f77_AssessedValuetotal"] == "$264,200"
    # Deed vesting composes book/page + year acquired
    assert values["f80_VestingDeedtypeBookPaged"] == "Bk 16601 / Pg 156-157, acquired 2022"


def test_blanks_are_dropped_never_guessed():
    record = build_22_penobscot()
    values = mis_field_values(record)
    # Fixture TBDs must be absent, not empty strings
    assert "f8_PropertySubType" not in values      # sub-type TBD
    assert "f31_FullTaxAmountexcludeexem" not in values  # tax amount TBD
    assert "f37_ShowingService" not in values      # seller answer
    assert "f38_CompListing" not in values         # MLS answer
    # Flood fields appear only once enrichment fills them
    assert "f84_InSpecialFloodHazardArea" not in values
    record.in_sfha = False
    record.flood_zone = "X"
    values = mis_field_values(record)
    assert values["f84_InSpecialFloodHazardArea"] == "No"
    assert values["f85_FloodZone"] == "X"


@pytest.mark.skipif(not TEMPLATE.exists(), reason="MIS template not present (internal form)")
def test_fill_round_trip(tmp_path):
    from pypdf import PdfReader

    record = build_22_penobscot()
    out = fill_master_information_sheet(record, TEMPLATE, tmp_path / "mis.pdf")
    fields = PdfReader(str(out)).get_fields()
    assert fields["f2_ListPrice"].get("/V") == "$325,000"
    assert fields["f75_OwnerofRecord"].get("/V") == "Brett D. Zeigler"
    assert fields["f44_Roomsexclbaths"].get("/V") == "12"
