"""Live tax cards from Vision Government Solutions (VGSI) — no browser.

Most Maine towns publish assessment data through VGSI at
`gis.vgsi.com/<town>me/`. The site looks like a classic ASP.NET app, but its
search box is backed by a JSON web service (`async.asmx/GetDataAddress`) and
the parcel page is plain server-rendered HTML with labeled spans — so the
whole pull is two HTTP requests:

  1. POST async.asmx/GetDataAddress  {"inVal": "22 PENOBSCOT", ...} -> PID
  2. GET  Parcel.aspx?pid=NNNN       -> owner, MBLU, assessment, land,
                                        last sale (price + deed book/page!),
                                        year built, living area, beds/baths

Everything the card states gets cross-checked against the transaction
record — assessed value, map/lot, deed book/page, year built — and
mismatches are flagged ⚠️ for reconciliation, mirroring the source-conflict
conventions in the hand-written master docs.

This is the first vendor adapter in the tax-card registry: towns not on VGSI
(or with a different slug) raise, and callers fall back to the pull sheet.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field

from realtorai.integrations.maine_parcels import normalize_map_lot
from realtorai.integrations.spark.record_bridge import split_street_address

logger = structlog.get_logger()

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "RealtorAI/0.1 (transaction-coordinator tooling; tax card lookup)"

# Towns whose VGSI slug differs from strip-spaces-and-append-"me".
SLUG_OVERRIDES: dict[str, str] = {}


class CrossCheck(BaseModel):
    field: str
    tax_card_value: str
    record_value: str
    matches: bool


class TaxCard(BaseModel):
    """Parsed VGSI property card."""

    town: str
    pid: str
    account: str | None = None
    mblu: str | None = None
    location: str | None = None
    owner: str | None = None
    owner_mailing: str | None = None
    assessment_total: Decimal | None = None
    assessment_land: Decimal | None = None
    last_sale_price: Decimal | None = None
    last_sale_date: str | None = None
    deed_book_page: str | None = None
    use_code: str | None = None
    use_description: str | None = None
    assessment_year: int | None = None
    land_acres: Decimal | None = None
    year_built: int | None = None
    living_area_sqft: int | None = None
    style: str | None = None
    heat_fuel: str | None = None
    bedrooms: int | None = None
    full_baths: int | None = None
    half_baths: int | None = None
    building_count: int | None = None
    source_url: str
    cross_checks: list[CrossCheck] = Field(default_factory=list)
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    source: str = "Vision Government Solutions (town assessor)"

    @property
    def summary(self) -> str:
        bits = []
        if self.assessment_total is not None:
            bits.append(f"assessed ${self.assessment_total:,.0f}")
        if self.use_description:
            bits.append(self.use_description.title())
        mismatches = [c for c in self.cross_checks if not c.matches]
        if self.cross_checks and not mismatches:
            bits.append(f"{len(self.cross_checks)} record cross-checks pass")
        elif mismatches:
            fields = ", ".join(c.field for c in mismatches)
            bits.append(f"MISMATCH vs record: {fields} - reconcile")
        return "; ".join(bits) or "tax card retrieved"


def town_slug(town: str) -> str:
    key = town.strip().lower()
    if key in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[key]
    return re.sub(r"[^a-z0-9]", "", key) + "me"


def base_url_for(town: str) -> str:
    return f"https://gis.vgsi.com/{town_slug(town)}/"


# ---------------------------------------------------------------------------
# Parsing (pure functions — tested offline)
# ---------------------------------------------------------------------------


def _strip_tags(value: str) -> str:
    import html as html_lib

    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", text).strip()


def _span(html: str, label_id: str) -> str | None:
    """Value of a `MainContent_*` span; ctl indices vary, so match loosely."""
    pattern = rf'<span[^>]*id="MainContent_(?:ctl\d+_)?{label_id}"[^>]*>(.*?)</span>'
    match = re.search(pattern, html, re.S)
    if not match:
        return None
    return _strip_tags(match.group(1)) or None


def _table_value(html: str, label: str) -> str | None:
    """Value cell following a `<td>Label</td>` in the building-attribute table."""
    pattern = rf"<td[^>]*>\s*{re.escape(label)}\s*</td>\s*<td[^>]*>(.*?)</td>"
    match = re.search(pattern, html, re.S)
    if not match:
        return None
    value = _strip_tags(match.group(1)).replace("\xa0", "").strip()
    return value or None


def _money(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace("$", "").replace(",", "").strip())
    except InvalidOperation:
        return None


def _num(value: str | None) -> int | None:
    if not value:
        return None
    digits = value.replace(",", "").strip()
    return int(digits) if digits.isdigit() else None


def _assessment_year(html: str) -> int | None:
    """Latest year in the Valuation History table (the assessment year)."""
    idx = html.find("Valuation History")
    if idx < 0:
        return None
    match = re.search(r"<td[^>]*>\s*((?:19|20)\d{2})\s*</td>", html[idx : idx + 3000])
    return int(match.group(1)) if match else None


def parse_parcel_html(html: str) -> dict[str, Any]:
    """Extract the card fields from a VGSI Parcel.aspx page."""
    mblu = _span(html, "lblMblu")
    if mblu:
        mblu = re.sub(r"\s+", "", mblu).rstrip("/")
    acres = _span(html, "lblLndSize")
    try:
        land_acres = Decimal(acres) if acres else None
    except InvalidOperation:
        land_acres = None
    return {
        "location": _span(html, "lblLocation"),
        "mblu": mblu,
        "account": _span(html, "lblAcctNum"),
        "pid": _span(html, "lblPid"),
        "owner": _span(html, "lblGenOwner") or _span(html, "lblOwner"),
        "owner_mailing": _span(html, "lblAddr1"),
        "assessment_total": _money(_span(html, "lblGenAssessment")),
        "assessment_land": _money(_span(html, "lblLndAsmt")),
        "last_sale_price": _money(_span(html, "lblPrice")),
        "last_sale_date": _span(html, "lblSaleDate"),
        "deed_book_page": _span(html, "lblBp"),
        "use_code": _span(html, "lblUseCode"),
        "use_description": _span(html, "lblUseCodeDescription"),
        "assessment_year": _assessment_year(html),
        "land_acres": land_acres,
        "year_built": _num(_span(html, "lblYearBuilt")),
        "living_area_sqft": _num(_span(html, "lblBldArea")),
        "style": _table_value(html, "Style:") or _table_value(html, "Style"),
        "heat_fuel": _table_value(html, "Heating Fuel") or _table_value(html, "Heat Fuel"),
        "bedrooms": _num(_table_value(html, "Bedrooms")),
        "full_baths": _num(_table_value(html, "Full Baths")),
        "half_baths": _num(_table_value(html, "Half Baths")),
        "building_count": _num(_span(html, "lblBldCount")),
    }


# ---------------------------------------------------------------------------
# Cross-checks against the transaction record
# ---------------------------------------------------------------------------


def _page_overlaps(card_page: str, record_page: str) -> bool:
    """'156' matches record '156-157' (registries list ranges, cards list first)."""
    card_numbers = set(re.findall(r"\d+", card_page))
    record_numbers = set(re.findall(r"\d+", record_page))
    return bool(card_numbers & record_numbers)


def build_cross_checks(
    card_fields: dict[str, Any],
    *,
    record_assessed: Decimal | None = None,
    record_map_lot: str | None = None,
    record_deed_book: str | None = None,
    record_deed_page: str | None = None,
    record_year_built: int | None = None,
) -> list[CrossCheck]:
    checks: list[CrossCheck] = []

    if record_assessed is not None and card_fields.get("assessment_total") is not None:
        card_value = card_fields["assessment_total"]
        checks.append(
            CrossCheck(
                field="assessed_value",
                tax_card_value=f"${card_value:,.0f}",
                record_value=f"${record_assessed:,.0f}",
                matches=card_value == record_assessed,
            )
        )
    if record_map_lot and card_fields.get("mblu"):
        checks.append(
            CrossCheck(
                field="map_lot",
                tax_card_value=card_fields["mblu"],
                record_value=record_map_lot,
                matches=normalize_map_lot(card_fields["mblu"]) == normalize_map_lot(record_map_lot),
            )
        )
    if record_deed_book and card_fields.get("deed_book_page"):
        card_bp = card_fields["deed_book_page"]
        book_part = card_bp.split("/")[0].strip()
        book_ok = book_part == str(record_deed_book).strip()
        page_ok = True
        if record_deed_page and "/" in card_bp:
            page_ok = _page_overlaps(card_bp.split("/", 1)[1], str(record_deed_page))
        record_bp = f"{record_deed_book}/{record_deed_page or '?'}"
        checks.append(
            CrossCheck(
                field="deed_book_page",
                tax_card_value=card_bp,
                record_value=record_bp,
                matches=book_ok and page_ok,
            )
        )
    if record_year_built is not None and card_fields.get("year_built") is not None:
        checks.append(
            CrossCheck(
                field="year_built",
                tax_card_value=str(card_fields["year_built"]),
                record_value=str(record_year_built),
                matches=card_fields["year_built"] == record_year_built,
            )
        )
    return checks


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def render_tax_card_markdown(card: TaxCard) -> str:
    lines = [
        f"# Tax Card — {card.location or 'parcel'}, {card.town}",
        "",
        f"**{card.summary}**",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Owner | {card.owner or 'n/a'} |",
        f"| Owner mailing address | {card.owner_mailing or 'n/a'} |",
        f"| MBLU (Map/Block/Lot) | {card.mblu or 'n/a'} |",
        f"| Account # / PID | {card.account or 'n/a'} / {card.pid} |",
        "| Total assessment | "
        + (f"${card.assessment_total:,.0f}" if card.assessment_total is not None else "n/a")
        + " |",
        "| Land assessment | "
        + (f"${card.assessment_land:,.0f}" if card.assessment_land is not None else "n/a")
        + " |",
        f"| Use code | {card.use_code or 'n/a'} — {card.use_description or ''} |",
        f"| Land (acres) | {card.land_acres if card.land_acres is not None else 'n/a'} |",
        f"| Year built | {card.year_built or 'n/a'} |",
        "| Living area | "
        + (f"{card.living_area_sqft:,} sqft" if card.living_area_sqft else "n/a")
        + " |",
        f"| Style / Heat | {card.style or 'n/a'} / {card.heat_fuel or 'n/a'} |",
        f"| Beds / Full baths / Half | {card.bedrooms or '?'} / {card.full_baths or '?'} / "
        f"{card.half_baths or 0} |",
        "| Last sale | "
        + (f"${card.last_sale_price:,.0f}" if card.last_sale_price else "n/a")
        + f" on {card.last_sale_date or 'n/a'} |",
        f"| Deed (Book/Page per card) | {card.deed_book_page or 'n/a'} |",
        f"| Source | [{card.source}]({card.source_url}), "
        f"fetched {card.fetched_at.date().isoformat()} |",
    ]
    if card.cross_checks:
        lines += [
            "",
            "## Cross-checks vs transaction record",
            "",
            "| Field | Tax card | Record | |",
            "|---|---|---|---|",
        ]
        for check in card.cross_checks:
            mark = "✓" if check.matches else "⚠️ reconcile"
            lines.append(
                f"| {check.field} | {check.tax_card_value} | {check.record_value} | {mark} |"
            )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


async def search_pid(
    client: httpx.AsyncClient, base_url: str, street_address: str
) -> tuple[str, str | None]:
    """Find the PID via the address-autocomplete web service."""
    parts = split_street_address(street_address)
    number = (parts["street_number"] or "").upper()
    name = (parts["street_name"] or street_address).upper()
    query = f"{number} {name}".strip()

    response = await client.post(
        f"{base_url}async.asmx/GetDataAddress",
        json={"inVal": query, "src": "i_address"},
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    response.raise_for_status()
    items = response.json().get("d", [])
    if not items:
        raise ValueError(f"VGSI: no address match for '{query}'")

    def _preferred(item: dict[str, Any]) -> bool:
        return bool(number) and item.get("value", "").upper().startswith(number + " ")

    best = next((i for i in items if _preferred(i)), items[0])
    mblu = re.sub(r"\s+", "", best.get("mblu") or "").rstrip("/") or None
    return str(best["id"]), mblu


async def fetch_tax_card(
    street_address: str,
    town: str,
    out_dir: Path,
    *,
    record_assessed: Decimal | None = None,
    record_map_lot: str | None = None,
    record_deed_book: str | None = None,
    record_deed_page: str | None = None,
    record_year_built: int | None = None,
) -> tuple[TaxCard, Path, Path]:
    """Full pull: address -> PID -> parsed card + saved page + cross-checked report.

    Raises when the town isn't on VGSI or the address doesn't match —
    callers fall back to the manual pull sheet.
    """
    base_url = base_url_for(town)
    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        probe = await client.get(base_url)
        if probe.status_code != 200:
            raise ValueError(f"Town '{town}' not found on VGSI ({base_url})")

        pid, _ = await search_pid(client, base_url, street_address)
        page = await client.get(f"{base_url}Parcel.aspx", params={"pid": pid})
        page.raise_for_status()
        html = page.text

    fields = parse_parcel_html(html)
    checks = build_cross_checks(
        fields,
        record_assessed=record_assessed,
        record_map_lot=record_map_lot,
        record_deed_book=record_deed_book,
        record_deed_page=record_deed_page,
        record_year_built=record_year_built,
    )
    card = TaxCard(
        town=town,
        pid=fields.get("pid") or pid,
        source_url=f"{base_url}Parcel.aspx?pid={pid}",
        cross_checks=checks,
        **{k: v for k, v in fields.items() if k != "pid"},
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "tax_card.html"
    html_path.write_text(html)
    md_path = out_dir / "tax_card.md"
    md_path.write_text(render_tax_card_markdown(card))
    (out_dir / "tax_card.json").write_text(card.model_dump_json(indent=2))

    logger.info(
        "tax_card_fetched",
        town=town,
        pid=card.pid,
        assessed=str(card.assessment_total),
        mismatches=sum(1 for c in checks if not c.matches),
    )
    return card, html_path, md_path
