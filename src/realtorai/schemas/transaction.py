"""Canonical TransactionRecord — single source of truth for a deal's data.

Mirrors the master schema in docs/transaction_data_schema.md. Per-field
naming follows the canonical names defined there. The DocuSign field mapper
(integrations/docusign/field_mapper.py) translates these to DocuSign Rooms
field paths.

This is a partial first pass — covers the fields that map cleanly to
DocuSign Rooms today plus the most critical TC-tracked fields. Extend
incrementally as more sources come online.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class Party(BaseModel):
    """A person on the transaction (seller, buyer, agent)."""

    name: str | None = None
    company: str | None = None
    email: str | None = None
    cell_phone: str | None = None
    business_phone: str | None = None
    home_phone: str | None = None
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class TransactionRecord(BaseModel):
    """Canonical transaction record.

    The `docusign_room_id` is the join key — every record corresponds to
    one Room. Field names match docs/transaction_data_schema.md.
    """

    # ---- Identifiers ----
    docusign_room_id: int | None = None
    mls_number: str | None = None
    transaction_type: Literal[
        "Residential", "Multi-Family", "Commercial", "Personal Property", "Land", "Other"
    ] | None = None
    representation_side: Literal["Listing", "Buyer", "Dual", "Lease"] | None = None

    # ---- Listing contract (ER/EA terms — Part A "Contract Information") ----
    listing_agreement_type: Literal["ER", "EA"] | None = Field(
        default=None, description="Exclusive Right to Sell / Exclusive Agency"
    )
    listing_status: Literal["Active", "Coming Soon — No Show", "Pending", "Closed"] | None = None
    listing_expiration_date: date | None = None
    comp_listing: bool | None = None
    kick_out: bool | None = None
    showing_service: str | None = Field(default=None, description="BrokerBay / None")

    # ---- Property ----
    property_sub_type: Literal[
        "Single Family Residence", "Condominium", "Mobile Home"
    ] | None = None
    street_address: str | None = None
    address2: str | None = None
    unit_number: str | None = None
    city: str | None = None
    town: str | None = Field(default=None, description="Maine quirk; sometimes differs from city")
    state: str | None = Field(default="US-ME", description="DocuSign uses US-XX format")
    zip: str | None = None
    zip4: str | None = None
    county: str | None = None
    parcel_id: str | None = Field(default=None, description="Preserve source format verbatim")
    map_lot: str | None = Field(default=None, description="Preserve source format verbatim")
    deed_book: str | None = None
    deed_page: str | None = None
    legal_description: str | None = None
    lot_size_acres: Decimal | None = None
    lot_size_sqft: Decimal | None = None
    acreage_source: Literal[
        "Appraiser", "Deed", "Public Records", "Seller", "Survey", "Other"
    ] | None = None
    year_built: int | None = None
    square_footage: Decimal | None = Field(
        default=None, description="Finished sqft above grade"
    )
    sqft_below_grade: Decimal | None = None
    sqft_source: Literal[
        "Appraiser", "Builder", "Measured", "Measured (ANSI)", "Public Records",
        "Seller", "Other",
    ] | None = None
    bedrooms: int | None = None
    bathrooms: Decimal | None = Field(default=None, description="Total; half baths = 0.5")
    rooms_total: int | None = Field(default=None, description="Excludes bathrooms")
    unit_count: int | None = Field(
        default=None,
        description="Dwelling units; MLS-required on Multi-Family. Not derivable "
        "from transaction_type — 'Multi-Family' does not say how many.",
    )
    fireplaces_total: int | None = None
    # MLS bath matrix — per-level counts (all 10 are MLS-required)
    full_baths_basement: int | None = None
    half_baths_basement: int | None = None
    full_baths_level_1: int | None = None
    half_baths_level_1: int | None = None
    full_baths_level_2: int | None = None
    half_baths_level_2: int | None = None
    full_baths_level_3: int | None = None
    half_baths_level_3: int | None = None
    full_baths_upper: int | None = None
    half_baths_upper: int | None = None
    garage: bool | None = Field(default=None, description="MLS Garage Y/N (spaces separate)")
    garage_spaces: int | None = None
    road_frontage: bool | None = None
    road_frontage_feet: Decimal | None = None
    road_frontage_source: Literal[
        "Appraiser", "Deed", "Public Records", "Seller", "Survey", "Other"
    ] | None = None
    school_district: str | None = None
    assessed_value: Decimal | None = None
    annual_tax_amount: Decimal | None = None
    tax_year: int | None = None
    zoning: str | None = None
    zoning_overlay: Literal["Yes", "No", "Unknown"] | None = None
    leased_land: bool | None = None
    association: bool | None = Field(default=None, description="HOA/association exists")
    neighborhood_association: str | None = None
    tree_growth: bool | None = Field(default=None, description="Maine Tree Growth program")
    hers_certified: Literal["Yes", "No", "Unknown"] | None = None
    surveyed: Literal["Yes", "No", "Unknown"] | None = None
    seasonal: Literal["Yes", "No", "Unknown"] | None = None
    occupant_type: Literal["Owner", "Tenant"] | None = None
    furniture: Literal["Furnished", "Unfurnished", "Partially", "Negotiable"] | None = None
    color: str | None = None
    bank_owned_reo: bool | None = None
    two_houses_on_lot: bool | None = None
    # Systems (Part A supporting detail / disclosure section I-III)
    water_source: Literal["Public", "Private", "Seasonal", "Unknown"] | None = None
    sewer: Literal["Public", "Private", "Quasi-Public", "Unknown"] | None = None
    heat_type: str | None = None
    electrical: str | None = Field(
        default=None, description="Fuses / Circuit Breaker / mixed / Other / Unknown"
    )
    waterfront: bool | None = None
    water_views: bool | None = None
    # Flood (disclosure section VI — auto-filled from the FEMA NFHL pull)
    flood_zone: str | None = None
    in_sfha: bool | None = Field(default=None, description="Special Flood Hazard Area")
    firm_panel: str | None = None
    # Deed-derived facts
    deed_type_offered: Literal[
        "Bill of Sale", "Other", "Personal Rep", "Quit Claim",
        "Quit Claim w/Covenant", "Trustee", "Warranty",
    ] | None = None
    deed_all_or_partial: Literal["All", "Partial"] | None = None
    deed_restrictions: Literal["Unknown", "Yes"] | None = None
    year_acquired: int | None = Field(default=None, description="Year seller took title")

    # ---- Parties (DocuSign supports 2 of each side) ----
    seller_1: Party = Field(default_factory=Party)
    seller_2: Party = Field(default_factory=Party)
    buyer_1: Party = Field(default_factory=Party)
    buyer_2: Party = Field(default_factory=Party)
    listing_agent_1: Party = Field(default_factory=Party)
    listing_agent_2: Party = Field(default_factory=Party)
    buyer_agent_1: Party = Field(default_factory=Party)
    buyer_agent_2: Party = Field(default_factory=Party)

    # ---- Dates (effective date drives all P&S deadlines) ----
    effective_date: date | None = Field(
        default=None,
        description='Date of last party signature; appears as "Contract Date" on the TW',
    )
    offer_date: date | None = None
    binding_date: date | None = None
    seller_executed_contract_date: date | None = None
    estimated_closing_date: date | None = None
    closing_date: date | None = None
    inspection_deadline: date | None = None
    appraisal_deadline: date | None = None
    financing_commitment_deadline: date | None = None
    contingency_removal_date: date | None = None

    # ---- Financial ----
    estimated_sale_price: Decimal | None = None
    final_sale_price: Decimal | None = None
    contract_amount: Decimal | None = None
    emd_amount: Decimal | None = None
    emd_due_date: date | None = None
    entity_holding_emd: str | None = None
    seller_concession_amount: Decimal | None = None
    list_side_commission_pct: Decimal | None = None
    buyer_side_commission_pct: Decimal | None = None
    financing_type: str | None = None

    # ---- Service providers ----
    title_provider: str | None = None
    escrow_provider: str | None = None
    mortgage_provider: str | None = None
    homeowners_insurance_provider: str | None = None
    home_warranty_provider: str | None = None
    survey_provider: str | None = None

    # ---- Condition & conveyance ----
    # Disclosure intel the paperwork states plainly but no form field claimed,
    # so it used to land in `comments` as prose — extracted, then unreachable by
    # every filler. Nothing here feeds the room/MLS build today; these exist so
    # the facts are addressable when the P&S, disclosures, or a buyer question
    # needs them. Keep them free-text where the source is free-text; inventing
    # an enum the paperwork does not use would just move the problem.
    personal_property_included: str | None = Field(
        default=None,
        description="Appliances/chattel conveying with the property, as listed",
    )
    system_updates: str | None = Field(
        default=None,
        description="Replacements and service history with dates/servicer, if stated",
    )
    known_defects: str | None = Field(
        default=None, description="Defects the seller disclosed, quoted or paraphrased"
    )
    basement_moisture: str | None = Field(
        default=None, description="Water intrusion observations — location and conditions"
    )
    sump_pump: bool | None = None
    lead_paint_status: Literal[
        "None Known", "Known", "Presumed (pre-1978)", "Unknown"
    ] | None = Field(
        default=None,
        description="Seller's stated position; 'Presumed' when age triggers it and "
        "no test exists. Distinct from whether the disclosure was signed.",
    )
    lead_paint_condition: str | None = Field(
        default=None, description="Observed paint condition, e.g. peeling window trim"
    )

    # ---- Meta ----
    origin_of_lead: str | None = None
    special_circumstances: str | None = None
    comments: str | None = None
