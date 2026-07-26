"""Maine parcels tax map — pure-function tests (no network)."""

from realtorai.integrations.maine_parcels import (
    _where_for_address,
    normalize_map_lot,
    parcel_info_from_feature,
    render_parcel_markdown,
)

FEATURE = {
    "attributes": {
        "TOWN": "Orono",
        "COUNTY": "Penobscot",
        "STATE_ID": "19490_20-03-082",
        "MAP_BK_LOT": "20-03-082",
        "PROP_LOC": "22 PENOBSCOT STREET",
        "FMSRCORG": "SEWALL",
        "FMUPDAT": "4/1/2011",
    },
    "geometry": {
        "rings": [[
            [-68.6612, 44.8846],
            [-68.6605, 44.8846],
            [-68.6605, 44.8851],
            [-68.6612, 44.8851],
            [-68.6612, 44.8846],
        ]]
    },
}


def test_normalize_map_lot_formats_agree():
    # Tax card, state layer, and prose forms all normalize identically
    assert normalize_map_lot("020/003/082") == ("20", "3", "82")
    assert normalize_map_lot("20-03-082") == ("20", "3", "82")
    assert normalize_map_lot("Map 20 Lot 3-82") == ("20", "3", "82")
    assert normalize_map_lot("020/003/082") == normalize_map_lot("20-03-082")
    assert normalize_map_lot(None) is None
    assert normalize_map_lot("") is None


def test_where_clause_building():
    where = _where_for_address("Orono", "22 Penobscot Street")
    assert where == "TOWN='Orono' AND UPPER(PROP_LOC) LIKE '22 PENOBSCOT%'"
    # SQL-quote escaping
    assert "''" in _where_for_address("Owl's Head", "5 Main Street")
    # No street number -> no attribute query possible
    assert _where_for_address("Orono", "Penobscot Street") is None


def test_parcel_info_match_check():
    info = parcel_info_from_feature(FEATURE, "address", record_map_lot="020/003/082")
    assert info.map_bk_lot == "20-03-082"
    assert info.map_lot_matches_record is True
    assert "matches tax-card map/lot" in info.summary

    mismatch = parcel_info_from_feature(FEATURE, "address", record_map_lot="020/003/081")
    assert mismatch.map_lot_matches_record is False
    assert "DOES NOT match" in mismatch.summary

    unchecked = parcel_info_from_feature(FEATURE, "point", record_map_lot=None)
    assert unchecked.map_lot_matches_record is None
    assert unchecked.matched_by == "point"


def test_render_parcel_markdown():
    info = parcel_info_from_feature(FEATURE, "address", record_map_lot="020/003/082")
    text = render_parcel_markdown(info)
    assert "20-03-082" in text
    assert "19490_20-03-082" in text
    assert "Matches the record's map/lot" in text
    assert "not a recorded survey" in text

    mismatch = parcel_info_from_feature(FEATURE, "address", record_map_lot="99/99/99")
    assert "reconcile" in render_parcel_markdown(mismatch)
