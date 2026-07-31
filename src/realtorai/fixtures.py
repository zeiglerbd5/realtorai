"""Reference fixture: the 22 Penobscot St transaction record.

Derived from a real document set (deed, tax card, signed listing agreement,
MREC brokerage relationship form, lead paint + property disclosures) for a
listing in Orono. Used by the demo scripts, the UI demo button, and the
workflow tests.

Party identities are fictional — seller, agents, and agency all follow the
repo's anonymisation convention. The *property* facts are not: the address,
Map/Block/Lot, deed book and page, and assessed value are genuine public
record, which is what lets the live registry, VGSI tax card, Maine parcel,
and FEMA flood integrations resolve against real government APIs in the demo.
Swapping them for invented values would break the one part of this project
that talks to production systems.
"""

from datetime import date
from decimal import Decimal

from realtorai.schemas.transaction import Party, TransactionRecord


def build_22_penobscot() -> TransactionRecord:
    return TransactionRecord(
        # ---- Identifiers ----
        transaction_type="Multi-Family",  # Tax card: Use Code 1050 "3 UNIT"
        representation_side="Listing",
        # ---- Listing contract (ER terms) ----
        listing_agreement_type="ER",
        listing_status="Coming Soon — No Show",
        listing_expiration_date=date(2026, 8, 31),
        kick_out=False,
        # comp_listing / showing_service deliberately TBD — seller/MLS answers
        # ---- Property ----
        street_address="22 Penobscot Street",
        city="Orono",
        town="Orono",
        state="US-ME",
        zip="04473",
        county="Penobscot",
        parcel_id="020/003/082",         # Tax card "Mblu"
        map_lot="020/003/082",           # same — town uses Map/Block/Lot collapsed
        deed_book="16601",               # Listing agreement specifies 16601 / 156-157
        deed_page="156-157",
        legal_description=(
            "Lot in Orono, Penobscot County, ME, generally westerly side of "
            "Penobscot Street; same premises conveyed Daniel Moor by Ard "
            "Godfrey et al. by deed 4/29/1836 (Vol 101, Pg 84); further by "
            "deed Maranda S. Taylor to Willard A. Spencer 4/8/1908 (Bk 783, "
            "Pg 163), excepting portion conveyed to European & North American "
            "Railway Company."
        ),
        lot_size_acres=Decimal("0.22"),
        acreage_source="Public Records",
        # Tax card; property disclosure says 1836 (likely the original land conveyance)
        year_built=1920,
        square_footage=Decimal("3676"),
        sqft_below_grade=Decimal("0"),
        sqft_source="Public Records",
        bedrooms=6,                       # ⚠️ tax card 6 vs prior MLS unit-sum 5 — reconcile
        bathrooms=Decimal("3"),
        rooms_total=12,
        fireplaces_total=1,
        # Bath matrix per prior MLS: U1+U3 on level 1, U2 on level 2
        full_baths_basement=0,
        half_baths_basement=0,
        full_baths_level_1=2,
        half_baths_level_1=0,
        full_baths_level_2=1,
        half_baths_level_2=0,
        full_baths_level_3=0,
        half_baths_level_3=0,
        full_baths_upper=0,
        half_baths_upper=0,
        garage=True,                      # ⚠️ prior MLS said No vs ~200sqft detached on tax card
        garage_spaces=1,                  # 200sqft outbuilding "GARAGE-AVG"
        road_frontage=True,
        road_frontage_feet=Decimal("66"),
        road_frontage_source="Public Records",
        assessed_value=Decimal("264200"),
        tax_year=2025,                    # assessment year; Full Tax Amount $ still TBD (mill rate)
        zoning="Residential",
        zoning_overlay="No",
        leased_land=False,
        association=False,
        tree_growth=False,
        # hers_certified deliberately TBD — seller answer
        surveyed="Yes",
        seasonal="No",
        occupant_type="Tenant",
        furniture="Unfurnished",
        color="Yellow",
        bank_owned_reo=False,
        two_houses_on_lot=False,
        water_source="Public",
        sewer="Public",                   # new sewer line per seller updates
        heat_type="Baseboard hot water (oil); new propane HWBB boiler (2024) + FHA K1",
        electrical="Circuit breakers + fuses (mixed)",
        waterfront=False,
        water_views=True,                 # Penobscot River views per prior MLS
        deed_all_or_partial="All",
        deed_restrictions="Unknown",      # railway exception per deed — flag to title
        year_acquired=2022,
        # ---- Seller (fictional; see the module docstring) ----
        seller_1=Party(
            name="Morgan T. Rowe",
            email="morgan.rowe@example.com",
            cell_phone="207-555-0142",
            # Listing agreement (current); tax card has a stale Old Town address
            address1="48 Forest Avenue",
            city="Orono",
            state="ME",
            postal_code="04473",
        ),
        # ---- Listing agent(s) ----
        listing_agent_1=Party(
            name="Agent One",
            company="The Agency REALTORS",
            email="agent.one@agency.example",  # inferred; not in docs
            business_phone="207-555-0101",
            address1="100 Main Street",
            city="Bangor",
            state="ME",
            postal_code="04401",
        ),
        listing_agent_2=Party(
            name="Agent Two",
            company="The Agency REALTORS",
        ),
        # ---- Dates from listing agreement ----
        effective_date=date(2026, 6, 1),          # Listing term start
        # ---- Pricing / commission ----
        estimated_sale_price=Decimal("325000"),   # List price
        list_side_commission_pct=Decimal("1.0"),  # 1% per listing agreement
        # ---- Meta ----
        comments=(
            "Personal property included: 3 refrigerators, 3 washers, 3 dryers, "
            "2 gas ranges, 1 electric range. Conveyance by Quitclaim deed. "
            "Multi-unit (3-unit) converted from single family. Heat: 2yr "
            "propane HWBB boiler + FHA K1 (Forest Heating, last service "
            "2024-11-01); old oil furnaces in basement defunct. Sewer + "
            "downstairs plumbing fully replaced. Basement: sump pump present, "
            "water in SE corner during heavy rain. Electrical: 1 main breaker "
            "+ 2 smaller fuse boxes (mixed). Lead paint: unknown but probable "
            "given age; cracking/peeling around window trims + storage rooms."
        ),
    )
