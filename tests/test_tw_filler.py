"""Transaction Worksheet filler — mapping tests (pure) + fill test (template-gated)."""

import os
from pathlib import Path

import pytest

from realtorai.documents.tw_filler import (
    SOLD_TERMS_CHECKBOXES,
    TYPE_CHECKBOXES,
    fill_transaction_worksheet,
    tw_field_values,
)
from realtorai.fixtures import build_22_penobscot

TEMPLATE = Path("data/templates/Transaction-Worksheet.pdf")

# data/templates/ is gitignored, so this gate is permanently closed in CI —
# `pytest -m template` reports it rather than letting it hide. Set
# REALTORAI_REQUIRE_TEMPLATES=1 locally to turn the skip into a real failure.
template_gated = pytest.mark.skipif(
    not TEMPLATE.exists() and os.environ.get("REALTORAI_REQUIRE_TEMPLATES") != "1",
    reason="TW template not present (internal form)",
)


def test_field_mapping_from_fixture():
    record = build_22_penobscot()
    record.docusign_room_id = 2001
    values = tw_field_values(record)

    assert values["Property Address City State Zip"] == "22 Penobscot Street, Orono, ME 04473"
    assert values["Seller Names 1"] == "Morgan T. Rowe"
    assert values["Listing Agent"] == "Agent One"
    assert values["Listing Agency"] == "The Agency REALTORS"
    assert values["Sellers Email"] == "morgan.rowe@example.com"
    assert values["Contract Date"] == "06/01/2026"
    assert values["Estimated Sale Price"] == "$325,000"
    # Commission lands under the generic name, or the agency's real field
    # name when the gitignored overrides file is present locally
    rate = values.get("Agency Listing Rate") or next(
        (v for k, v in values.items() if k.endswith("Listing Rate")), None
    )
    assert rate == "1.0%"
    assert values["Room ID"] == "2001"
    # Unknowns stay blank, never guessed
    assert values["Buyer Names 1"] == ""
    assert values["Closing Company"] == ""


def test_type_checkboxes_exhaustive():
    record = build_22_penobscot()  # Multi-Family
    values = tw_field_values(record)
    assert values["MultiFamily"] == "/On"
    # Every other type box explicitly off — stale template values can't survive
    for record_type, field in TYPE_CHECKBOXES.items():
        if record_type != "Multi-Family":
            assert values[field] == "/Off", field


def test_sold_terms_checkboxes():
    record = build_22_penobscot()
    record.financing_type = "Conventional"
    values = tw_field_values(record)
    assert values["Conv"] == "/On"
    assert values["Cash"] == "/Off"
    assert values["FHA"] == "/Off"

    record.financing_type = None
    values = tw_field_values(record)
    assert all(values[f] == "/Off" for f in SOLD_TERMS_CHECKBOXES.values())


@pytest.mark.template
@template_gated
def test_fill_round_trip(tmp_path):
    from pypdf import PdfReader

    record = build_22_penobscot()
    record.docusign_room_id = 2001
    out = fill_transaction_worksheet(record, TEMPLATE, tmp_path / "tw.pdf")

    fields = PdfReader(str(out)).get_fields()
    assert fields["Seller Names 1"].get("/V") == "Morgan T. Rowe"
    assert fields["Room ID"].get("/V") == "2001"
    assert str(fields["MultiFamily"].get("/V")) == "/On"
    # Template's stale 'Residential' tick must be cleared
    assert str(fields["Residential"].get("/V")) == "/Off"
    assert fields["Estimated Sale Price"].get("/V") == "$325,000"
