"""VGSI tax card — pure-function tests against an HTML fixture (no network)."""

from decimal import Decimal

from realtorai.integrations.vgsi_tax_card import (
    TaxCard,
    build_cross_checks,
    parse_parcel_html,
    render_tax_card_markdown,
    town_slug,
)

# Minimal excerpt of a real gis.vgsi.com Parcel.aspx page structure
FIXTURE_HTML = """
<span id="MainContent_lblLocation">22 PENOBSCOT STREET</span>
<span id="MainContent_lblMblu">020/&nbsp; 003/ 082/ /</span>
<span id="MainContent_lblAcctNum">865</span>
<span id="MainContent_lblPid">2202</span>
<span id="MainContent_lblGenOwner">ZEIGLER, BRETT D</span>
<span id="MainContent_lblAddr1">605 COLLEGE AVENUE OLD TOWN, ME 04468</span>
<span id="MainContent_lblGenAssessment">$264,200</span>
<span id="MainContent_lblLndAsmt">$40,300</span>
<span id="MainContent_lblPrice">$202,000</span>
<span id="MainContent_lblSaleDate">08/29/2022</span>
<span id="MainContent_lblBp">16601/156</span>
<span id="MainContent_lblUseCode">1050</span>
<span id="MainContent_lblUseCodeDescription">3 UNIT</span>
<span id="MainContent_lblLndSize">0.22</span>
<span id="MainContent_lblBldCount">1</span>
<td class="plabel"> Year Built: </td>
<td class="data"><span id="MainContent_ctl02_lblYearBuilt">1920</span></td>
<td class="plabel"> Living Area: </td>
<td class="data"><span id="MainContent_ctl02_lblBldArea">3,676</span></td>
<tr class="RowStyle"> <td>Bedrooms</td><td>6</td> </tr>
<tr class="AltRowStyle"> <td>Full Baths</td><td>3</td> </tr>
<tr class="RowStyle"> <td>Half Baths</td><td>&nbsp;</td> </tr>
<tr class="RowStyle"> <td>Style</td><td>Family Conver.</td> </tr>
<tr class="AltRowStyle"> <td>Heating Fuel</td><td>Oil</td> </tr>
"""


def test_town_slug():
    assert town_slug("Orono") == "oronome"
    assert town_slug("Old Town") == "oldtownme"


def test_parse_parcel_html():
    fields = parse_parcel_html(FIXTURE_HTML)
    assert fields["location"] == "22 PENOBSCOT STREET"
    assert fields["mblu"] == "020/003/082"  # whitespace + trailing slashes cleaned
    assert fields["owner"] == "ZEIGLER, BRETT D"
    assert fields["assessment_total"] == Decimal("264200")
    assert fields["assessment_land"] == Decimal("40300")
    assert fields["last_sale_price"] == Decimal("202000")
    assert fields["deed_book_page"] == "16601/156"
    assert fields["use_description"] == "3 UNIT"
    assert fields["land_acres"] == Decimal("0.22")
    assert fields["year_built"] == 1920
    assert fields["living_area_sqft"] == 3676
    assert fields["bedrooms"] == 6
    assert fields["full_baths"] == 3
    assert fields["half_baths"] is None  # &nbsp; cell
    assert fields["style"] == "Family Conver."
    assert fields["heat_fuel"] == "Oil"


def test_cross_checks_all_match():
    fields = parse_parcel_html(FIXTURE_HTML)
    checks = build_cross_checks(
        fields,
        record_assessed=Decimal("264200"),
        record_map_lot="020/003/082",
        record_deed_book="16601",
        record_deed_page="156-157",  # card lists first page of the range
        record_year_built=1920,
    )
    assert len(checks) == 4
    assert all(c.matches for c in checks)


def test_cross_checks_flag_mismatches():
    fields = parse_parcel_html(FIXTURE_HTML)
    checks = build_cross_checks(
        fields,
        record_assessed=Decimal("999999"),
        record_deed_book="11111",
        record_year_built=1836,  # the property-disclosure conflict
    )
    assert [c.matches for c in checks] == [False, False, False]


def test_summary_and_markdown():
    fields = parse_parcel_html(FIXTURE_HTML)
    checks = build_cross_checks(
        fields, record_assessed=Decimal("264200"), record_year_built=1836
    )
    card = TaxCard(
        town="Orono",
        pid=fields.pop("pid"),
        source_url="https://gis.vgsi.com/oronome/Parcel.aspx?pid=2202",
        cross_checks=checks,
        **fields,
    )
    assert "MISMATCH vs record: year_built" in card.summary
    text = render_tax_card_markdown(card)
    assert "ZEIGLER, BRETT D" in text
    assert "$264,200" in text
    assert "16601/156" in text
    assert "⚠️ reconcile" in text
    assert "✓" in text
