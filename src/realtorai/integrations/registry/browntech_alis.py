"""Browntech ALIS registry adapter (penobscotdeeds.com and siblings).

The ALIS web frontend looks ancient (AS/400 web gateway, frame shell,
Browntech plugin links) but is entirely driveable with plain GETs once the
`&WSWVER=2` cookie is set — no login, no browser, no Playwright:

  1. GET  WW400R.HTM?WSIQTP=LR09AP&WSKYCD=B&W9BK={book}&W9PG={page}
         -> index record (recorded date, type, town, grantors/grantees,
            page count) + a "View Document Image" link
  2. GET  the view link (LR09I...)  -> viewer page listing /WwwImg/*.PDF
  3. GET  the all-pages PDF

The free view carries a "NOT AN OFFICIAL COPY" overlay — fine for TC
reference and deed review. Un-watermarked official copies require the
subscriber cart/checkout ($0.50/page after 400 free/year); the report
notes this.

Index facts are cross-checked against the transaction record: the town must
match, and on a listing the current owner should appear as the deed's
grantee.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

TIMEOUT = httpx.Timeout(60.0, connect=15.0)
USER_AGENT = "RealtorAI/0.1 (transaction-coordinator tooling; deed retrieval)"


class DeedIndexRecord(BaseModel):
    """Registry index facts for one recorded document."""

    county: str
    book: str
    page: str
    doc_number: str | None = None
    recorded_date: str | None = None
    recorded_time: str | None = None
    doc_date: str | None = None
    page_count: int | None = None
    doc_type: str | None = None
    town: str | None = None
    grantors: list[str] = Field(default_factory=list)
    grantees: list[str] = Field(default_factory=list)
    watermarked: bool = True
    source_url: str = ""
    town_matches_record: bool | None = None
    owner_matches_grantee: bool | None = None
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    source: str = "County Registry of Deeds (Browntech ALIS)"

    @property
    def summary(self) -> str:
        bits = [f"Bk {self.book}/Pg {self.page}"]
        if self.doc_type:
            bits.append(self.doc_type)
        if self.grantors and self.grantees:
            bits.append(f"{self.grantors[0]} -> {self.grantees[0]}")
        problems = []
        if self.town_matches_record is False:
            problems.append("town mismatch")
        if self.owner_matches_grantee is False:
            problems.append("owner not the grantee")
        if problems:
            bits.append("WARNING: " + ", ".join(problems) + " - verify chain of title")
        return "; ".join(bits)


# ---------------------------------------------------------------------------
# Parsing (pure functions — tested offline)
# ---------------------------------------------------------------------------


def parse_index(html: str) -> dict:
    """Extract index facts + the view-image href from the LR09AP result page."""
    bk_pg = re.search(r"Bk-Pg:\s*(\d+)-(\d+)", html)
    if not bk_pg:
        raise ValueError("Registry index parse failed — document may not exist")

    def _find(pattern: str) -> str | None:
        match = re.search(pattern, html)
        return match.group(1).strip() if match else None

    parties: dict[str, list[str]] = {"Gtor": [], "Gtee": []}
    for match in re.finditer(r">([^<]+?)\s*\((Gtor|Gtee)\)</a>", html):
        parties[match.group(2)].append(match.group(1).strip())

    view = re.search(r'<a href="([^"]+)"[^>]*title="View Document Image"', html)

    pages = _find(r"Pages in document:\s*(\d+)")
    return {
        "book": bk_pg.group(1),
        "page": bk_pg.group(2),
        "recorded_date": _find(r"Recorded:\s*([0-9-]+)"),
        "recorded_time": _find(r"Recorded:[^@]*@(?:&#160;|\s)*([0-9:apm\.]+)"),
        "doc_date": _find(r"Doc date:\s*([0-9-]+)"),
        "doc_number": _find(r"#\s*(\d{4,})"),
        "page_count": int(pages) if pages else None,
        "doc_type": _find(r"Type:(?:&#160;|\s)*([A-Za-z /&-]+?)(?:<|$)"),
        "town": _find(r"Town:\s*([A-Z0-9 .'-]+?)(?:<|&#160;|$)"),
        "grantors": parties["Gtor"],
        "grantees": parties["Gtee"],
        "view_href": view.group(1) if view else None,
    }


def parse_viewer(html: str) -> str:
    """Pick the all-pages PDF path from the image-viewer page.

    The viewer lists e.g. D38E.PDF (whole document) plus D38E0001.PDF,
    D38E0002.PDF (single pages) — the shortest name is the full document.
    """
    paths = sorted(set(re.findall(r"(/WwwImg/[A-Z0-9]+\.PDF)", html)), key=len)
    if not paths:
        raise ValueError("Registry viewer parse failed — no PDF links found")
    return paths[0]


def name_matches(deed_name: str, record_name: str) -> bool:
    """'ROWE, MORGAN T' vs 'Morgan T. Rowe' — token-set comparison."""
    def tokens(value: str) -> set[str]:
        return {t for t in re.findall(r"[A-Za-z]+", value.upper()) if len(t) > 1}

    a, b = tokens(deed_name), tokens(record_name)
    if not a or not b:
        return False
    return len(a & b) >= min(2, len(a), len(b))


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class BrowntechALIS:
    def __init__(self, base_url: str, county: str):
        self.base_url = base_url.rstrip("/")
        self.county = county
        self.screen_url = f"{self.base_url}/ALIS/WW400R.HTM"

    async def fetch(
        self,
        book: str,
        page: str,
        out_dir: Path,
        *,
        expect_town: str | None = None,
        expect_owner: str | None = None,
    ) -> tuple[DeedIndexRecord, Path, Path]:
        """Search by book/page, download the (watermarked) PDF, write a report."""
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            client.cookies.set("&WSWVER", "2", domain=self.base_url.split("//")[1])

            search = await client.get(
                self.screen_url,
                params={
                    "WSIQTP": "LR09AP",
                    "WSKYCD": "B",
                    "WSHTNM": "WW409R00",
                    "WSWVER": "2",
                    "W9BK": str(book),
                    "W9PG": str(page),
                },
            )
            search.raise_for_status()
            index = parse_index(search.text)
            if index["view_href"] is None:
                raise ValueError("Document found but no image link — may be pre-imaging era")

            viewer = await client.get(urljoin(self.screen_url, index["view_href"]))
            viewer.raise_for_status()
            pdf_path_remote = parse_viewer(viewer.text)

            pdf_response = await client.get(urljoin(self.base_url, pdf_path_remote))
            pdf_response.raise_for_status()
            if not pdf_response.content.startswith(b"%PDF"):
                raise ValueError("Registry returned a non-PDF response for the image")

        record = DeedIndexRecord(
            county=self.county,
            source_url=str(search.url),
            **{k: v for k, v in index.items() if k != "view_href"},
        )
        if expect_town and record.town:
            record.town_matches_record = (
                record.town.strip().upper() == expect_town.strip().upper()
            )
        if expect_owner and record.grantees:
            record.owner_matches_grantee = any(
                name_matches(g, expect_owner) for g in record.grantees
            )

        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = out_dir / f"deed_bk{record.book}_pg{record.page}.pdf"
        pdf_path.write_bytes(pdf_response.content)
        md_path = out_dir / f"deed_bk{record.book}_pg{record.page}.md"
        md_path.write_text(render_deed_markdown(record))
        (out_dir / f"deed_bk{record.book}_pg{record.page}.json").write_text(
            record.model_dump_json(indent=2)
        )

        logger.info(
            "deed_fetched",
            county=self.county,
            book=record.book,
            page=record.page,
            doc_type=record.doc_type,
            pages=record.page_count,
        )
        return record, pdf_path, md_path


def render_deed_markdown(record: DeedIndexRecord) -> str:
    def check(value: bool | None) -> str:
        if value is None:
            return "not checked"
        return "✓" if value else "⚠️ MISMATCH — verify chain of title"

    lines = [
        f"# Recorded Deed — Book {record.book}, Page {record.page} "
        f"({record.county} County)",
        "",
        f"**{record.summary}**",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Document # | {record.doc_number or 'n/a'} |",
        f"| Type | {record.doc_type or 'n/a'} |",
        f"| Recorded | {record.recorded_date or 'n/a'}"
        + (f" @ {record.recorded_time}" if record.recorded_time else "")
        + " |",
        f"| Document date | {record.doc_date or 'n/a'} |",
        f"| Pages | {record.page_count or 'n/a'} |",
        f"| Town | {record.town or 'n/a'} |",
        f"| Grantor(s) | {'; '.join(record.grantors) or 'n/a'} |",
        f"| Grantee(s) | {'; '.join(record.grantees) or 'n/a'} |",
        f"| Town matches record | {check(record.town_matches_record)} |",
        f"| Owner is grantee | {check(record.owner_matches_grantee)} |",
        f"| Source | [{record.source}]({record.source_url}), "
        f"fetched {record.fetched_at.date().isoformat()} |",
        "",
        "The attached PDF is the registry's free view copy and carries a "
        '"NOT AN OFFICIAL COPY" overlay — sufficient for reference and deed '
        "review. For a clean official copy, use the registry's print cart "
        "(first 400 pages/year free, then $0.50/page).",
    ]
    return "\n".join(lines) + "\n"
