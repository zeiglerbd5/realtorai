"""Master Information Sheet filler — the agency team's fillable PDF.

The team's "Master Information Sheet (fillable)" is an 89-field AcroForm
(fields f1–f89, ordered to the FlexMLS entry screen — same taxonomy as the
154-field index). This fills it deterministically from the TransactionRecord:
the sheet is the office-staff-facing rendering of the record, generated at
listing intake and regenerated any time the record improves (e.g. after the
public-records pulls auto-fill flood zone, assessment year, deed facts).

All fields are text; Y/N answers render as "Yes"/"No"; unknown stays blank —
never guessed. Template at `settings.mis_template_path` (gitignored).
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import structlog

from realtorai.integrations.spark.record_bridge import split_street_address
from realtorai.schemas.transaction import TransactionRecord

logger = structlog.get_logger()


def _yn(value: bool | None) -> str:
    if value is None:
        return ""
    return "Yes" if value else "No"


def _s(value) -> str:
    return "" if value is None else str(value)


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"${value:,.0f}" if value == value.to_integral_value() else f"${value:,.2f}"


def _d(value: date | None) -> str:
    return value.strftime("%m/%d/%Y") if value else ""


def _baths(full: int | None, half: int | None) -> str:
    if full is None and half is None:
        return ""
    return f"{full or 0}F / {half or 0}H"


def _map_block_lot(map_lot: str | None) -> dict[str, str]:
    """Split '020/003/082' into Map / Block / Lot; two segments = Map / Lot."""
    if not map_lot:
        return {}
    import re

    segments = [s for s in re.split(r"[^0-9A-Za-z]+", map_lot) if s]
    if len(segments) >= 3:
        return {"f23_Map": segments[0], "f24_Block": segments[1], "f25_Lot": segments[2]}
    if len(segments) == 2:
        return {"f23_Map": segments[0], "f25_Lot": segments[1]}
    return {"f23_Map": map_lot}


def mis_field_values(record: TransactionRecord) -> dict[str, str]:
    """MIS field name (f1..f89) -> value. Blank = unknown, never guessed."""
    street = split_street_address(record.street_address or "")
    state = (record.state or "").removeprefix("US-")
    address_line = ", ".join(
        p
        for p in (
            record.street_address,
            record.city,
            f"{state} {record.zip}".strip() if (state or record.zip) else None,
        )
        if p
    )
    vesting = ""
    if record.deed_book:
        vesting = f"Bk {record.deed_book} / Pg {record.deed_page or '?'}"
        if record.year_acquired:
            vesting += f", acquired {record.year_acquired}"

    values = {
        "f1_PropertyAddressCityState": address_line,
        "f2_ListPrice": _money(record.estimated_sale_price),
        "f3_Status": _s(record.listing_status),
        "f4_MLS": _s(record.mls_number),
        "f5_PropertyType": _s(record.transaction_type),
        "f6_ListingMember": _s(record.listing_agent_1.name),
        "f7_ColistingMember": _s(record.listing_agent_2.name),
        "f8_PropertySubType": _s(record.property_sub_type),
        "f9_Street": _s(street["street_number"]),
        "f11_StreetName": _s(street["street_name"]),
        "f12_StreetType": _s(street["street_suffix"]),
        "f13_Unit": _s(record.unit_number),
        "f14_County": _s(record.county),
        "f15_Town": _s(record.town or record.city),
        "f16_State": state,
        "f17_ZipCode": _s(record.zip),
        "f18_Zip4": _s(record.zip4),
        "f19_TaxIDTOWNMAPBLOCKLOT": _s(record.parcel_id),
        "f20_LeasedLand": _yn(record.leased_land),
        "f21_DeedBook": _s(record.deed_book),
        "f22_DeedPage": _s(record.deed_page),
        **_map_block_lot(record.map_lot or record.parcel_id),
        "f26_Zoning": _s(record.zoning),
        "f27_ZoningOverlay": _s(record.zoning_overlay),
        "f28_Association": _yn(record.association),
        "f29_NeighborhoodAssociation": _s(record.neighborhood_association),
        "f30_SchoolDistrict": _s(record.school_district),
        "f31_FullTaxAmountexcludeexem": _money(record.annual_tax_amount),
        "f32_TaxYear": _s(record.tax_year),
        "f33_TreeGrowth": _yn(record.tree_growth),
        "f34_ListDate": _d(record.effective_date),
        "f35_ExpirationDate": _d(record.listing_expiration_date),
        "f36_ListingAgreementEREA": _s(record.listing_agreement_type),
        "f37_ShowingService": _s(record.showing_service),
        "f38_CompListing": _yn(record.comp_listing),
        "f39_KickOut": _yn(record.kick_out),
        "f40_Surveyed": _s(record.surveyed),
        "f41_Seasonal": _s(record.seasonal),
        "f42_OccupantType": _s(record.occupant_type),
        "f43_DeedConveyanceTypeOffere": _s(record.deed_type_offered),
        "f44_Roomsexclbaths": _s(record.rooms_total),
        "f45_Bedrooms": _s(record.bedrooms),
        "f46_Fireplaces": _s(record.fireplaces_total),
        "f47_BasementFullHalf": _baths(record.full_baths_basement, record.half_baths_basement),
        "f48_Level1FullHalf": _baths(record.full_baths_level_1, record.half_baths_level_1),
        "f49_Level2FullHalf": _baths(record.full_baths_level_2, record.half_baths_level_2),
        "f50_Level3UpperFullHalf": " · ".join(
            part
            for part in (
                f"L3 {_baths(record.full_baths_level_3, record.half_baths_level_3)}"
                if _baths(record.full_baths_level_3, record.half_baths_level_3)
                else "",
                f"Upper {_baths(record.full_baths_upper, record.half_baths_upper)}"
                if _baths(record.full_baths_upper, record.half_baths_upper)
                else "",
            )
            if part
        ),
        "f51_YearBuilt0999ifunknown": _s(record.year_built),
        "f52_SqFtFinishedAboveGrade": _s(record.square_footage),
        "f53_SqFtFinishedBelowGrade": _s(record.sqft_below_grade),
        "f54_SqFtSource": _s(record.sqft_source),
        "f55_Garage": _yn(record.garage),
        "f56_GarageSpaces": _s(record.garage_spaces),
        "f57_LotSizeacres": _s(record.lot_size_acres),
        "f58_SourceofAcreage": _s(record.acreage_source),
        "f59_RoadFrontage": _yn(record.road_frontage),
        "f60_RoadFrontageft": _s(record.road_frontage_feet),
        "f61_Furniture": _s(record.furniture),
        "f62_Color": _s(record.color),
        "f63_Heattypefuel": _s(record.heat_type),
        "f65_Water": _s(record.water_source),
        "f66_Sewer": _s(record.sewer),
        "f67_Electric": _s(record.electrical),
        "f75_OwnerofRecord": _s(record.seller_1.name),
        "f76_Owner2": _s(record.seller_2.name),
        "f77_AssessedValuetotal": _money(record.assessed_value),
        "f79_AssessmentYear": _s(record.tax_year),
        "f80_VestingDeedtypeBookPaged": vesting,
        "f82_Legaldescriptionease": _s(record.legal_description),
        "f84_InSpecialFloodHazardArea": _yn(record.in_sfha),
        "f85_FloodZone": _s(record.flood_zone),
        "f86_FIRMPanel": _s(record.firm_panel),
        "f89_Sourcedocsuseddatesa": (
            "Auto-filled from RealtorAI transaction record, "
            f"{datetime.now(UTC).date().isoformat()}"
        ),
    }
    # Drop blanks so we never overwrite a hand-entered template value with ""
    return {k: v for k, v in values.items() if v != ""}


def fill_master_information_sheet(
    record: TransactionRecord,
    template_path: Path,
    out_path: Path,
) -> Path:
    """Fill the agency team MIS from the record."""
    from realtorai.documents.pdf_fill import fill_acroform

    values = mis_field_values(record)
    fill_acroform(template_path, values, out_path)
    logger.info("mis_filled", out=str(out_path), fields_with_values=len(values))
    return out_path
