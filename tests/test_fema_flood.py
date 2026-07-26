"""FEMA flood determination — pure-function tests (no network)."""

from realtorai.integrations.fema_flood import (
    FloodDetermination,
    determination_from_attrs,
    render_flood_markdown,
)


def _det(**overrides) -> FloodDetermination:
    base = dict(
        address="22 Penobscot Street, Orono, ME 04473",
        matched="22 PENOBSCOT ST, ORONO, ME, 04473",
        lat=44.884877,
        lon=-68.660354,
        zone_attrs={
            "FLD_ZONE": "X",
            "ZONE_SUBTY": "AREA OF MINIMAL FLOOD HAZARD",
            "SFHA_TF": "F",
            "STATIC_BFE": -9999.0,
        },
        panel_attrs={"FIRM_PAN": "23019C1943D", "EFF_DATE": 1689724800000},
    )
    base.update(overrides)
    return determination_from_attrs(**base)


def test_determination_from_attrs():
    det = _det()
    assert det.flood_zone == "X"
    assert det.in_sfha is False
    assert det.static_bfe is None  # -9999 sentinel scrubbed
    assert det.firm_panel == "23019C1943D"
    assert det.panel_effective_date == "2023-07-19"  # epoch ms -> ISO date


def test_sfha_true_and_bfe_kept():
    det = _det(
        zone_attrs={"FLD_ZONE": "AE", "ZONE_SUBTY": "FLOODWAY", "SFHA_TF": "T", "STATIC_BFE": 62.0}
    )
    assert det.in_sfha is True
    assert det.static_bfe == 62.0
    assert "IN a Special Flood Hazard Area" in det.summary


def test_missing_layers_handled():
    det = _det(zone_attrs=None, panel_attrs=None)
    assert det.flood_zone is None
    assert det.in_sfha is None
    assert det.firm_panel is None
    assert "unknown" in det.summary.lower()


def test_render_flood_markdown():
    text = render_flood_markdown(_det())
    assert "Zone X" in text
    assert "23019C1943D" in text
    assert "2023-07-19" in text
    assert "msc.fema.gov" in text  # official-FIRMette pointer for lenders

    sfha_text = render_flood_markdown(
        _det(zone_attrs={"FLD_ZONE": "AE", "ZONE_SUBTY": None, "SFHA_TF": "T", "STATIC_BFE": None})
    )
    assert "flag flood insurance disclosure" in sfha_text
