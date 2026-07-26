"""Master Information Document generator.

Renders the canonical TransactionRecord in the format of the hand-written
master docs in the Transactions folder (e.g. "22 Penobscot St - Master
Information Document.md"), which are organized around the two places the data
ends up:

    PART A — MLS LISTING DATA, ordered to the Maine Listings / FlexMLS entry
             screen (listing side only)
    PART B — LISTING DOCUMENTS, in DocuSign Rooms fill order
             (Brokerage form → ERTS → Lead Paint → Property Disclosure;
              buyer side: Brokerage form → EBRA)
    PART C — TC working data (parties, dates, financials, deed review,
             supporting docs, verification notes)

Conventions carried over from the real documents:
    TBD          — needs input/verification (missing fields render as TBD
                   rather than being silently dropped when they're required)
    ⚠️           — flagged item (conflicts, compliance triggers)
    [SELLER✋]   — the seller answers this in DocuSign; the bot leaves it blank
    Compensation — NEVER guessed; rendered blank unless explicitly on record

IMPORTANT: this document is the TC's internal working file. It is saved to the
transaction's artifacts directory but is deliberately NEVER uploaded to the
DocuSign Transaction Room — clients and cooperating agents should not see it.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from realtorai.integrations.spark.record_bridge import split_street_address
from realtorai.schemas.transaction import Party, TransactionRecord

MASTER_DOC_FILENAME = "Master Information Document.md"

TBD = "TBD"


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"${value:,.0f}" if value == value.to_integral_value() else f"${value:,.2f}"


def _fmt(value: Any) -> str:
    if isinstance(value, date):
        return value.strftime("%m/%d/%Y")
    return str(value)


def _line(label: str, value: Any, *, required: bool = False, note: str = "") -> str | None:
    """One `- **Label:** value` line. Missing optional fields render nothing;
    missing required fields render TBD (the real docs surface gaps, not hide
    them)."""
    star = "\\*" if required else ""
    if value in (None, ""):
        if not required:
            return None
        value = TBD
    suffix = f"  {note}" if note else ""
    return f"- **{label}{star}:** {_fmt(value)}{suffix}"


def _lines(items: list[str | None]) -> list[str]:
    return [line for line in items if line is not None]


def _party_name(party: Party) -> str | None:
    return party.name


def _party_contact(party: Party) -> str | None:
    bits = [b for b in (party.email, party.cell_phone or party.business_phone) if b]
    return " · ".join(bits) or None


def _address_line(record: TransactionRecord) -> str:
    state = (record.state or "").removeprefix("US-")
    return ", ".join(
        p
        for p in (
            record.street_address,
            record.city,
            f"{state} {record.zip}".strip() if (state or record.zip) else None,
        )
        if p
    )


# ---------------------------------------------------------------------------
# Header + TBD blockers
# ---------------------------------------------------------------------------

def _header(record: TransactionRecord) -> list[str]:
    return [
        f"# Master Information Document — {_address_line(record)}",
        "",
        "> **Internal TC working document — never filed to the DocuSign Transaction Room.**",
        "> Ordered to the Maine Listings / FlexMLS entry screen (Part A) and the",
        "> DocuSign Rooms form-fill order (Part B). `TBD` = needs input/verification ·",
        "> `⚠️` = flagged, confirm · `[SELLER✋]` = seller answers in DocuSign (left blank).",
        "",
    ]


def _tbd_section(record: TransactionRecord) -> list[str]:
    if record.representation_side not in (None, "Listing", "Dual"):
        return []
    from realtorai.schemas.mls_required import SELLER_ONLY_LABELS, readiness

    filled, total, missing = readiness(record)
    if not missing:
        return []
    out = [
        f"## ⚠️ MLS-required fields still TBD ({filled}/{total} ready) — "
        "clear these before an MLS save",
        "",
    ]
    for i, label in enumerate(missing, 1):
        ask = "  — ask seller / walkthrough" if label in SELLER_ONLY_LABELS else ""
        out.append(f"{i}. **{label}\\***{ask}")
    out.append("")
    return out


# ---------------------------------------------------------------------------
# PART A — MLS listing data (FlexMLS entry order)
# ---------------------------------------------------------------------------


def _part_a(record: TransactionRecord) -> list[str]:
    if record.representation_side not in (None, "Listing", "Dual"):
        return []

    street = split_street_address(record.street_address or "")
    out = [
        "# PART A — MLS LISTING DATA (FlexMLS entry order)",
        "",
        "## Section 1 — General Listing Information",
        "",
    ]
    out += _lines([
        _line("Property Type", record.transaction_type, required=True),
        _line("Listing Member", _party_name(record.listing_agent_1), required=True),
        _line("Co-listing Member", _party_name(record.listing_agent_2)),
    ])
    def _yn(value: bool | None) -> str | None:
        if value is None:
            return None
        return "Yes" if value else "No"

    out += ["", "## Section 2 — Address & Property Sub-Type", ""]
    out += _lines([
        _line("Property Sub-Type", record.property_sub_type, required=True),
        _line("Street #", street["street_number"], required=True),
        _line("Street Name", street["street_name"], required=True),
        _line("Street Type", street["street_suffix"]),
        _line("Unit #", record.unit_number),
        _line("County", record.county, required=True),
        _line("Town", record.town or record.city, required=True),
        _line("State/Province", (record.state or "").removeprefix("US-"), required=True),
        _line("Zip Code", record.zip, required=True),
        _line("Zip +4", record.zip4),
        _line("Tax ID", record.parcel_id, required=True),
    ])
    out += ["", "## Section 3 — Main Fields", "", "### Location Information", ""]
    out += _lines([
        _line("Leased Land", _yn(record.leased_land), required=True),
        _line("Book", record.deed_book, required=True),
        _line("Page", record.deed_page, required=True),
        _line("Map/Lot", record.map_lot, required=True),
        _line("Zoning", record.zoning, required=True),
        _line("Zoning Overlay", record.zoning_overlay, required=True),
        _line("Neighborhood Association", record.neighborhood_association),
        _line("Association", _yn(record.association), required=True),
        _line("School District", record.school_district),
        _line("Full Tax Amount $", _money(record.annual_tax_amount), required=True),
        _line("Tax Year", record.tax_year, required=True),
        _line("Tree Growth Y/N", _yn(record.tree_growth), required=True),
        _line("HERS Certified", record.hers_certified, required=True),
        _line("Assessed Value", _money(record.assessed_value)),
    ])
    out += ["", "### Contract Information", ""]
    out += _lines([
        _line("Status", record.listing_status, required=True),
        _line("Comp Listing", _yn(record.comp_listing), required=True),
        _line("Kick-Out", _yn(record.kick_out)),
        _line("List Date", record.effective_date, required=True, note="(per listing term)"),
        _line("Expiration Date", record.listing_expiration_date, required=True),
        _line("List Price", _money(record.estimated_sale_price), required=True),
        _line("Showing Service Name", record.showing_service, required=True),
    ])
    out += ["", "### Property Information", ""]
    lead_note = ""
    if record.year_built is not None and record.year_built < 1978:
        lead_note = "⚠️ pre-1978 — lead paint disclosure required"
    baths = " / ".join(
        f"{level}: {full or 0}F+{half or 0}H"
        for level, full, half in [
            ("Bsmt", record.full_baths_basement, record.half_baths_basement),
            ("L1", record.full_baths_level_1, record.half_baths_level_1),
            ("L2", record.full_baths_level_2, record.half_baths_level_2),
            ("L3", record.full_baths_level_3, record.half_baths_level_3),
            ("Upper", record.full_baths_upper, record.half_baths_upper),
        ]
        if full is not None or half is not None
    )
    out += _lines([
        _line("Surveyed", record.surveyed, required=True),
        _line("Seasonal", record.seasonal, required=True),
        _line("Occupant Type", record.occupant_type),
        _line("Deed/Conveyance Type Offered", record.deed_type_offered),
        _line("Deed", record.deed_all_or_partial),
        _line("Deed Restrictions", record.deed_restrictions),
        _line("Bank Owned REO", _yn(record.bank_owned_reo)),
        _line("2 Detached Houses on 1 Lot", _yn(record.two_houses_on_lot)),
        _line("# Rooms", record.rooms_total, required=True, note="(excl. baths)"),
        _line("# Bedrooms", record.bedrooms, required=True),
        _line("# Fireplaces", record.fireplaces_total, required=True),
        _line("Baths by level", baths or None, required=True),
        _line("Furniture", record.furniture),
        _line("Color", record.color),
        _line("Year Built", record.year_built, required=True, note=lead_note),
        _line("SqFt Finished Above Grade", record.square_footage, required=True),
        _line("SqFt Finished Below Grade", record.sqft_below_grade, required=True),
        _line("SqFt Source", record.sqft_source, required=True),
        _line("Garage", _yn(record.garage), required=True),
        _line("Garage Spaces", record.garage_spaces),
        _line("Lot Size Acres +/-", record.lot_size_acres, required=True),
        _line("Source of Acreage", record.acreage_source, required=True),
        _line("Road Frontage", _yn(record.road_frontage)),
        _line("Road Frontage +/-", record.road_frontage_feet),
        _line("Source of Road Frontage", record.road_frontage_source),
    ])
    out += ["", "### Misc Info", ""]
    out += _lines([
        _line("Owner Name", record.seller_1.name),
        _line("Owner Name 2", record.seller_2.name),
        _line("Listing Agreement", record.listing_agreement_type, required=True),
    ])
    systems = _lines([
        _line("Water", record.water_source),
        _line("Sewer", record.sewer),
        _line("Heat", record.heat_type),
        _line("Electrical", record.electrical),
        _line("Waterfront", _yn(record.waterfront)),
        _line("Water Views", _yn(record.water_views)),
        _line("Year Seller Acquired", record.year_acquired),
    ])
    if systems:
        out += ["", "### Systems & Supporting Detail", ""] + systems
    out.append("")
    if record.legal_description:
        out += [
            "### Supporting detail",
            "",
            f"- **Legal Description:** {record.legal_description}",
            "",
        ]
    return out


# ---------------------------------------------------------------------------
# PART B — documents in DocuSign Rooms fill order
# ---------------------------------------------------------------------------


def _doc_brokerage(record: TransactionRecord, client_parties: list[Party]) -> list[str]:
    names = " / ".join(p.name for p in client_parties if p.name) or TBD
    buyer_side = record.representation_side == "Buyer"
    agent = record.buyer_agent_1 if buyer_side else record.listing_agent_1
    return _lines([
        "## DOC 1 — Brokerage Relationships Form (MREC #3)",
        "",
        _line("Client name(s)", names, required=True),
        _line("Licensee's name", _party_name(agent), required=True),
        _line("Company/Agency", agent.company, required=True),
        "",
    ])


def _doc_erts(record: TransactionRecord) -> list[str]:
    seller = record.seller_1
    return _lines([
        "## DOC 2 — Exclusive Right to Sell Listing Agreement",
        "",
        _line("Municipality", record.town or record.city, required=True),
        _line("County", record.county, required=True),
        _line("Located at", _address_line(record), required=True),
        _line("Deed Book(s) / Page(s)",
              f"{record.deed_book} / {record.deed_page}" if record.deed_book else None,
              required=True),
        _line("List price $", _money(record.estimated_sale_price), required=True),
        _line(
            "Listing commission",
            f"{record.list_side_commission_pct}%" if record.list_side_commission_pct else None,
            note="⚠️ never guessed — agent provides if blank",
            required=True,
        ),
        _line("Begins on (List Date)", record.effective_date, required=True),
        _line("Expiration Date", None, required=True, note="(per listing term)"),
        _line("Seller(s)", _party_name(seller), required=True),
        _line(
            "Seller mailing address",
            ", ".join(
                p
                for p in (seller.address1, seller.city, seller.state, seller.postal_code)
                if p
            )
            or None,
        ),
        _line("Seller phone / email", _party_contact(seller)),
        "- **Authorizations** (sign, advertising, lockbox, MLS, photos, internet): "
        "_(default Yes)_  [SELLER✋]",
        "- **Fixtures / personal property included-excluded:** _(blank)_  [SELLER✋]",
        "",
    ])


def _doc_lead_paint(record: TransactionRecord) -> list[str]:
    if record.year_built is None or record.year_built >= 1978:
        return []
    return _lines([
        f"## DOC 3 — Lead Paint Disclosure  ⚠️ Lead paint disclosure required "
        f"(built {record.year_built})",
        "",
        _line("Property located at", _address_line(record), required=True),
        _line("Seller name(s)", _party_name(record.seller_1), required=True),
        "- **(a) Lead-paint presence:** _(blank)_  [SELLER✋]",
        "- **(b) Records/reports:** _(blank)_  [SELLER✋]",
        "",
    ])


def _doc_property_disclosure(record: TransactionRecord) -> list[str]:
    return _lines([
        "## DOC 4 — Property Disclosure (Sections I–VII)",
        "",
        _line("Property located at", _address_line(record), required=True),
        _line("Seller name(s)", _party_name(record.seller_1), required=True),
        _line("Year built", record.year_built, required=True),
        "- **Water / waste / heating / hazardous material / flood sections:** "
        "_(blank — seller answers in DocuSign)_  [SELLER✋]",
        "",
    ])


def _doc_ebra(record: TransactionRecord) -> list[str]:
    buyers = " / ".join(p.name for p in (record.buyer_1, record.buyer_2) if p.name) or TBD
    agent = record.buyer_agent_1
    return _lines([
        "## DOC 2 — Exclusive Buyer Representation Agreement",
        "",
        _line("Buyer(s)", buyers, required=True),
        _line("Appointed Agent", _party_name(agent), required=True),
        _line("Company/Agency", agent.company, required=True),
        _line(
            "Buyer agency compensation",
            f"{record.buyer_side_commission_pct}%" if record.buyer_side_commission_pct else None,
            note="⚠️ never guessed — agent provides if blank",
            required=True,
        ),
        _line("Term begins", record.effective_date, required=True),
        _line("Expiration Date", None, required=True, note="(per agreement term)"),
        "",
    ])


def _part_b(record: TransactionRecord) -> list[str]:
    buyer_side = record.representation_side == "Buyer"
    out = [
        "# PART B — DOCUMENTS (DocuSign Rooms fill order)",
        "",
        "> Order = Brokerage form → "
        + (
            "EBRA."
            if buyer_side
            else "Exclusive Right to Sell → Lead Paint (if pre-1978) → Property Disclosure."
        )
        + " `[SELLER✋]` fields are left blank for the client to answer in DocuSign."
        " Compensation is **never** guessed.",
        "",
    ]
    if buyer_side:
        out += _doc_brokerage(record, [record.buyer_1, record.buyer_2])
        out += _doc_ebra(record)
    else:
        out += _doc_brokerage(record, [record.seller_1, record.seller_2])
        out += _doc_erts(record)
        out += _doc_lead_paint(record)
        out += _doc_property_disclosure(record)
    return out


# ---------------------------------------------------------------------------
# PART C — TC working data
# ---------------------------------------------------------------------------


def _party_block(label: str, party: Party) -> list[str]:
    fields = [
        ("Name", party.name),
        ("Company", party.company),
        ("Email", party.email),
        ("Cell", party.cell_phone),
        ("Business phone", party.business_phone),
        (
            "Address",
            ", ".join(
                p
                for p in (
                    party.address1,
                    party.address2,
                    party.city,
                    party.state,
                    party.postal_code,
                )
                if p
            )
            or None,
        ),
    ]
    present = [(k, v) for k, v in fields if v]
    if not present:
        return []
    return [f"**{label}**", ""] + [f"- {k}: {v}" for k, v in present] + [""]


def _part_c(
    record: TransactionRecord,
    deed_findings: list[dict[str, Any]] | None,
    supporting_documents: list[dict[str, Any]] | None,
    verification_notes: list[str] | None,
) -> list[str]:
    out = ["# PART C — TC WORKING DATA", ""]

    out += ["## Parties", ""]
    for label, party in [
        ("Seller 1", record.seller_1),
        ("Seller 2", record.seller_2),
        ("Buyer 1", record.buyer_1),
        ("Buyer 2", record.buyer_2),
        ("Listing agent 1", record.listing_agent_1),
        ("Listing agent 2", record.listing_agent_2),
        ("Buyer agent 1", record.buyer_agent_1),
        ("Buyer agent 2", record.buyer_agent_2),
    ]:
        out += _party_block(label, party)

    dates = _lines([
        _line("Effective date (Contract Date)", record.effective_date),
        _line("Offer date", record.offer_date),
        _line("Inspection deadline", record.inspection_deadline),
        _line("Appraisal deadline", record.appraisal_deadline),
        _line("Financing commitment deadline", record.financing_commitment_deadline),
        _line("Contingency removal", record.contingency_removal_date),
        _line("Estimated closing", record.estimated_closing_date),
        _line("Closing date", record.closing_date),
    ])
    if dates:
        out += ["## Critical Dates", ""] + dates + [""]

    fin = _lines([
        _line("List / estimated sale price", _money(record.estimated_sale_price)),
        _line("Contract amount", _money(record.contract_amount)),
        _line("Final sale price", _money(record.final_sale_price)),
        _line("EMD amount", _money(record.emd_amount)),
        _line("EMD held by", record.entity_holding_emd),
        _line("Seller concession", _money(record.seller_concession_amount)),
        _line("Financing type", record.financing_type),
    ])
    if fin:
        out += ["## Financial", ""] + fin + [""]

    providers = _lines([
        _line("Title", record.title_provider),
        _line("Escrow", record.escrow_provider),
        _line("Mortgage", record.mortgage_provider),
        _line("Homeowners insurance", record.homeowners_insurance_provider),
        _line("Home warranty", record.home_warranty_provider),
        _line("Survey", record.survey_provider),
    ])
    if providers:
        out += ["## Service Providers", ""] + providers + [""]

    if deed_findings:
        out += ["## Deed Review — Restrictions & Rights of Way", ""]
        for finding in deed_findings:
            kind = finding.get("kind", "finding").replace("_", " ").title()
            severity = finding.get("severity", "info")
            out.append(f"- **⚠️ [{severity.upper()}] {kind}** — {finding.get('explanation', '')}")
            if finding.get("excerpt"):
                out.append(f"  > {finding['excerpt']}")
        out.append("")

    if supporting_documents:
        out += ["## Supporting Documents", ""]
        for doc in supporting_documents:
            line = f"- **{doc.get('name')}**"
            if doc.get("source_url"):
                line += f" — [{doc.get('source_label', 'source')}]({doc['source_url']})"
            out.append(line)
        out.append("")

    if verification_notes:
        out += ["## Verification Notes (second-model audit)", ""]
        out += [f"- ⚠️ {note}" for note in verification_notes]
        out.append("")

    meta = _lines([
        _line("Origin of lead", record.origin_of_lead),
        _line("Special circumstances", record.special_circumstances),
    ])
    if meta:
        out += ["## Meta", ""] + meta + [""]

    if record.comments:
        out += ["## Working Notes", "", record.comments, ""]

    return out


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def render_master_info_document(
    record: TransactionRecord,
    *,
    deed_findings: list[dict[str, Any]] | None = None,
    supporting_documents: list[dict[str, Any]] | None = None,
    verification_notes: list[str] | None = None,
) -> str:
    """Render the record as the Master Information Document (markdown)."""
    out: list[str] = []
    out += _header(record)
    out += _tbd_section(record)
    out += _part_a(record)
    out += _part_b(record)
    out += _part_c(record, deed_findings, supporting_documents, verification_notes)
    return "\n".join(out).rstrip() + "\n"


def write_master_info_document(
    record: TransactionRecord,
    out_dir: Path,
    **render_kwargs: Any,
) -> Path:
    """Render and write the master info document into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / MASTER_DOC_FILENAME
    path.write_text(render_master_info_document(record, **render_kwargs))
    return path
