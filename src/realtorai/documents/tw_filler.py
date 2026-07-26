"""Transaction Worksheet filler — deterministic AcroForm fill, no LLM.

The The Agency Transaction Worksheet is a genuine fillable PDF (102 AcroForm
fields). This module maps the canonical TransactionRecord onto those fields
and writes a filled copy with pypdf — pure transcription, so the values on
the form are exactly the values on the record (capture once, verify once,
fill everywhere).

The blank template is an internal brokerage form and is NOT committed to the
repo — it lives at `settings.tw_template_path` (default
`data/templates/Transaction-Worksheet.pdf`, gitignored). The fill step skips
politely when the template is missing.

Ambiguous checkbox groups on the form (unlabeled `undefined_*`, the
Cartus/ERA-moves Seller/Buyer/NA cluster) are deliberately left untouched —
only unambiguous fields are written.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import structlog

from realtorai.schemas.transaction import TransactionRecord

logger = structlog.get_logger()

ON = "/On"
OFF = "/Off"

# record.transaction_type -> TW type checkbox field name
TYPE_CHECKBOXES: dict[str, str] = {
    "Residential": "Residential",
    "Multi-Family": "MultiFamily",
    "Commercial": "Commercial",
    "Personal Property": "Personal Property",
    "Land": "Land",
    "Other": "Transaction Worksheet",  # form quirk: "Other" box carries this name
}

# record.financing_type -> TW sold-terms checkbox field name
SOLD_TERMS_CHECKBOXES: dict[str, str] = {
    "Cash": "Cash",
    "Conventional": "Conv",
    "Conventional Insured": "Conv Ins",
    "FHA": "FHA",
    "FMHA-RD": "FMHARD",
    "MSHA": "MSHA",
    "Private": "Private",
    "VA": "VA",
    "Bank Owned": "Bank Owned",
    "Court Ordered": "Court Ordered",
    "Estate Sale": "Estate Sale",
    "Foreclosure": "Foreclosure",
    "Relocation": "Relocation",
    "Short Sale": "Short Sale",
}


def _fmt_date(value: date | None) -> str:
    return value.strftime("%m/%d/%Y") if value else ""


def _fmt_money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"${value:,.0f}" if value == value.to_integral_value() else f"${value:,.2f}"


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


def _party_address(party) -> str:
    return ", ".join(
        p
        for p in (party.address1, party.address2, party.city, party.state, party.postal_code)
        if p
    )


def tw_field_values(record: TransactionRecord) -> dict[str, str]:
    """TW field name -> value. Text fields and checkbox states together.

    Checkbox groups we own (type, sold terms) are written exhaustively —
    every box explicitly On or Off — so stale template values can't survive.
    """
    values: dict[str, str] = {
        # Header
        "Property Address City State Zip": _address_line(record),
        "MLS": record.mls_number or "",
        "Room ID": str(record.docusign_room_id or ""),
        # Parties
        "Seller Names 1": record.seller_1.name or "",
        "Seller Names 2": record.seller_2.name or "",
        "Buyer Names 1": record.buyer_1.name or "",
        "Buyer Names 2": record.buyer_2.name or "",
        "Forwarding Address 1": _party_address(record.seller_1),
        "Forwarding Address 1_2": _party_address(record.buyer_1),
        "Sellers Phone": record.seller_1.cell_phone or record.seller_1.home_phone or "",
        "Sellers Email": record.seller_1.email or "",
        "Buyers Phone": record.buyer_1.cell_phone or record.buyer_1.home_phone or "",
        "Buyers Email": record.buyer_1.email or "",
        # Agents
        "Listing Agent": record.listing_agent_1.name or "",
        "Listing Agency": record.listing_agent_1.company or "",
        "Buyer Agent": record.buyer_agent_1.name or "",
        "Buyer Agency": record.buyer_agent_1.company or "",
        # Dates & money
        "Contract Date": _fmt_date(record.effective_date),
        "Estimated Closing Date": _fmt_date(record.estimated_closing_date),
        "Closing Date": _fmt_date(record.closing_date),
        "Estimated Sale Price": _fmt_money(record.estimated_sale_price),
        "Final Sale Price": _fmt_money(record.final_sale_price),
        # Providers
        "Closing Company": record.title_provider or "",
        "Lender": record.mortgage_provider or "",
        # Commissions (only what the record actually carries — never guessed)
        "Agency Listing Rate": (
            f"{record.list_side_commission_pct}%"
            if record.list_side_commission_pct is not None
            else ""
        ),
        "Total Exclusive Buyer Agreement": (
            f"{record.buyer_side_commission_pct}%"
            if record.buyer_side_commission_pct is not None
            else ""
        ),
    }

    # Transaction type checkboxes — exhaustive on/off
    for record_type, field_name in TYPE_CHECKBOXES.items():
        values[field_name] = ON if record.transaction_type == record_type else OFF

    # Sold terms checkboxes — exhaustive on/off
    for financing, field_name in SOLD_TERMS_CHECKBOXES.items():
        values[field_name] = ON if (record.financing_type or "") == financing else OFF

    # Agency-specific AcroForm field names live in a gitignored overrides file
    # next to the template (the public repo carries only generic names).
    for generic, actual in _field_overrides().items():
        if generic in values:
            values[actual] = values.pop(generic)
    return values


def _field_overrides() -> dict[str, str]:
    """generic field name -> the agency form's actual AcroForm field name.

    Loaded from `tw_field_overrides.json` beside the TW template — kept out
    of git because real field names can identify the brokerage.
    """
    import json

    from realtorai.config.settings import get_settings

    path = get_settings().tw_template_path.parent / "tw_field_overrides.json"
    if path.exists():
        try:
            return dict(json.loads(path.read_text()))
        except Exception as e:
            logger.warning("tw_field_overrides_invalid", error=str(e))
    return {}


def fill_transaction_worksheet(
    record: TransactionRecord,
    template_path: Path,
    out_path: Path,
) -> Path:
    """Fill the TW template from the record and write the result."""
    from realtorai.documents.pdf_fill import fill_acroform

    values = tw_field_values(record)
    fill_acroform(template_path, values, out_path)
    logger.info(
        "transaction_worksheet_filled",
        out=str(out_path),
        fields_with_values=sum(1 for v in values.values() if v not in ("", OFF)),
    )
    return out_path
