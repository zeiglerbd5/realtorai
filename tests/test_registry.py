"""Registry of deeds (Browntech ALIS) — pure-function tests (no network)."""

import pytest

from realtorai.integrations.registry import registry_for
from realtorai.integrations.registry.browntech_alis import (
    DeedIndexRecord,
    name_matches,
    parse_index,
    parse_viewer,
    render_deed_markdown,
)

# Condensed from the real penobscotdeeds.com LR09AP response for Bk 16601 Pg 156
INDEX_HTML = (
    "<td>Search Document ID</td><td>16601-156</td>\n"
    "Bk-Pg:16601-156 &#160;&#160; &#160;&#160;Recorded: 08-29-2022&#160;@&#160;1:15:53pm"
    "&#160;&#160;Doc date: 08-26-2022&#160;&#160;Inst #25033\n"
    "<td>Pages in document: 2</td>\n"
    "<td>Grp: 1  Type:&#160;Deeds</td>\n"
    "<td>Town: ORONO</td>\n"
    '<a href="/ALIS/WW400R.HTM?WSIQTP=LR01L&W9SNM=LEPAGE">LEPAGE, GAIL M (Gtor)</a>\n'
    '<a href="/ALIS/WW400R.HTM?WSIQTP=LR01L&W9SNM=ZEIGLER">ZEIGLER, BRETT D (Gtee)</a>\n'
    '<a href="/ALIS/WW400R.HTM?WSIQTP=LR09I&W9RCCY=2022&W9RCMM=08&W9RCDD=29&W9CTLN=00429'
    '&WSKYCD=B&W9IMID=B22241AA.AH1" target="_blank" title="View Document Image">'
    '<img src="/HTML/PENOBSCT/Graphics2/icon_details.png"></a>\n'
)

VIEWER_HTML = """
<a href="/WwwImg/D38E.PDF" target="_blank">View the Image</a>
<a href="/WwwImg/D38E0001.PDF" target="_blank">View the Image</a>
<a href="/WwwImg/D38E0002.PDF" target="_blank">View the Image</a>
"""


def test_parse_index():
    index = parse_index(INDEX_HTML)
    assert index["book"] == "16601"
    assert index["page"] == "156"
    assert index["recorded_date"] == "08-29-2022"
    assert index["doc_date"] == "08-26-2022"
    assert index["doc_number"] == "25033"
    assert index["page_count"] == 2
    assert index["doc_type"] == "Deeds"
    assert index["town"] == "ORONO"
    assert index["grantors"] == ["LEPAGE, GAIL M"]
    assert index["grantees"] == ["ZEIGLER, BRETT D"]
    assert "LR09I" in index["view_href"]


def test_parse_index_missing_document():
    with pytest.raises(ValueError, match="may not exist"):
        parse_index("<html>Your search returned nothing</html>")


def test_parse_viewer_picks_all_pages_pdf():
    assert parse_viewer(VIEWER_HTML) == "/WwwImg/D38E.PDF"


def test_name_matches():
    assert name_matches("ZEIGLER, BRETT D", "Brett D. Zeigler")
    assert name_matches("ZEIGLER, BRETT D", "Brett Zeigler")
    assert not name_matches("LEPAGE, GAIL M", "Brett D. Zeigler")


def test_registry_router():
    assert registry_for("Penobscot") is not None
    assert registry_for("penobscot") is not None
    assert registry_for("Hancock") is None  # AcclaimWeb adapter TBD
    assert registry_for(None) is None


def test_render_deed_markdown_flags_mismatches():
    index = parse_index(INDEX_HTML)
    record = DeedIndexRecord(
        county="Penobscot",
        source_url="https://penobscotdeeds.com/ALIS/WW400R.HTM",
        town_matches_record=True,
        owner_matches_grantee=False,
        **{k: v for k, v in index.items() if k != "view_href"},
    )
    assert "owner not the grantee" in record.summary
    text = render_deed_markdown(record)
    assert "LEPAGE, GAIL M" in text
    assert "ZEIGLER, BRETT D" in text
    assert "⚠️ MISMATCH" in text
    assert "NOT AN OFFICIAL COPY" in text
