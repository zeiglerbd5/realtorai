"""Bidirectional mapping between canonical TransactionRecord and DocuSign Rooms field_data.

DocuSign Rooms exposes ~80 scalar fields and 8 nested party objects per room.
Our canonical schema uses snake_case names (e.g., `effective_date`); DocuSign
uses its own camelCase names (e.g., `contractDate`). This module is the
translation layer.

Coverage is intentionally partial — fields without a clean DocuSign equivalent
(e.g., `town`, `deed_book`, `map_lot`) stay in the canonical record only and
are tracked outside DocuSign.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from realtorai.schemas.transaction import Party, TransactionRecord

# ---------------------------------------------------------------------------
# Scalar field mapping: canonical_name -> docusign_name
# ---------------------------------------------------------------------------
# Order is for readability only — not significant.

SCALAR_MAP: dict[str, str] = {
    # Identifiers
    "mls_number": "mlsId",
    # Property
    "street_address": "address1",
    "address2": "address2",
    "city": "city",
    "state": "state",
    "zip": "postalCode",
    "county": "county",
    "parcel_id": "taxId",
    "legal_description": "legalDescription",
    "lot_size_acres": "lotSizeAcres",
    "lot_size_sqft": "lotSizeSquareFeet",
    "year_built": "yearBuilt",
    "bedrooms": "bedroomsTotal",
    "bathrooms": "bathroomsTotal",
    "garage_spaces": "garageSpaces",
    "school_district": "schoolDistrict",
    "assessed_value": "assessedValue",
    "annual_tax_amount": "taxAnnualAmount",
    "zoning": "zoningClassification",
    # Dates
    "effective_date": "contractDate",
    "offer_date": "offerDate",
    "binding_date": "bindingDate",
    "seller_executed_contract_date": "sellerExecutedContractDate",
    "estimated_closing_date": "expectedClosingDate",
    "closing_date": "actualCloseDate",
    "inspection_deadline": "inspectionContingencyDate",
    "appraisal_deadline": "appraisalContingencyDate",
    "financing_commitment_deadline": "loanContingencyDate",
    "contingency_removal_date": "contingencyRemovalDate",
    # Financial
    "estimated_sale_price": "contractAmount",
    "final_sale_price": "totalPurchasePrice",
    "contract_amount": "localContractAmount",
    "emd_amount": "earnestMoneyAmount",
    "entity_holding_emd": "entityHoldingEarnestMoney",
    "seller_concession_amount": "sellerConcession",
    "list_side_commission_pct": "listSideCommission",
    "buyer_side_commission_pct": "buyerSideCommission",
    "financing_type": "financingType",
    # Service providers
    "title_provider": "titleProvider",
    "escrow_provider": "escrowProvider",
    "mortgage_provider": "mortgageProvider",
    "homeowners_insurance_provider": "insuranceProvider",
    "home_warranty_provider": "homeWarrantyProvider",
    "survey_provider": "surveyProvider",
    # Meta
    "origin_of_lead": "originOfLead",
    "special_circumstances": "specialCircumstances",
    "comments": "comments",
}

# Canonical fields with no DocuSign Rooms equivalent at top level.
# Tracked only in the canonical record. Listed here so reviewers know
# the omission is deliberate, not a bug.
CANONICAL_ONLY: frozenset[str] = frozenset({
    "docusign_room_id",  # this IS the room key, not a field on the room
    "transaction_type",
    "representation_side",
    "town",
    "map_lot",
    "deed_book",
    "deed_page",
    "square_footage",
})

# ---------------------------------------------------------------------------
# Party mapping: canonical Party attr -> docusign nested object key
# ---------------------------------------------------------------------------

PARTY_FIELD_MAP: dict[str, str] = {
    "name": "name",
    "company": "company",
    "email": "email",
    "cell_phone": "cellPhone",
    "business_phone": "businessPhone",
    "home_phone": "homePhone",
    "address1": "address1",
    "address2": "address2",
    "city": "city",
    "state": "state",
    "postal_code": "postalCode",
    "country": "country",
}

# canonical TransactionRecord attr -> docusign nested object name
PARTY_OBJECT_MAP: dict[str, str] = {
    "seller_1": "seller1",
    "seller_2": "seller2",
    "buyer_1": "buyer1",
    "buyer_2": "buyer2",
    "listing_agent_1": "listingAgent1",
    "listing_agent_2": "listingAgent2",
    "buyer_agent_1": "buyerAgent1",
    "buyer_agent_2": "buyerAgent2",
}


# ---------------------------------------------------------------------------
# Forward: canonical -> DocuSign payload
# ---------------------------------------------------------------------------


# DocuSign Rooms fields that expect a STRING for an otherwise numeric value.
# Discovered empirically: most numeric fields want a JSON number, but a few
# (lot size in particular) validate as string. Extend this set as new
# FIELD_VALIDATION_ERROR responses surface.
STRING_TYPED_NUMERIC_FIELDS: frozenset[str] = frozenset({
    "lotSizeAcres",
    "lotSizeSquareFeet",
})


def _serialize(value: Any, docusign_field: str | None = None) -> Any:
    """Convert Python types to DocuSign-acceptable JSON values.

    DocuSign Rooms has per-field type expectations:
      - bedroomsTotal, garageSpaces, yearBuilt expect integers
      - contractAmount, earnestMoneyAmount, bathroomsTotal expect numbers
      - lotSizeAcres, lotSizeSquareFeet expect strings (see STRING_TYPED_NUMERIC_FIELDS)
    Dates serialize to ISO 8601 (date only).
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    is_string_typed = docusign_field in STRING_TYPED_NUMERIC_FIELDS
    if isinstance(value, Decimal):
        normalized = format(value.normalize(), "f")
        return normalized if is_string_typed else float(value)
    if isinstance(value, (int, float)):
        return str(value) if is_string_typed else value
    return value


def _party_to_payload(party: Party) -> dict[str, Any] | None:
    """Convert a Party to a DocuSign nested object. Returns None if empty."""
    out: dict[str, Any] = {}
    for canonical_attr, docusign_key in PARTY_FIELD_MAP.items():
        v = getattr(party, canonical_attr, None)
        if v is not None:
            out[docusign_key] = _serialize(v, docusign_key)
    return out or None


def to_room_field_data(record: TransactionRecord, *, include_nulls: bool = False) -> dict[str, Any]:
    """Convert a TransactionRecord to DocuSign Rooms field_data payload.

    Args:
        record: The canonical transaction record.
        include_nulls: If True, send `null` for unset fields (useful to clear
            a field on the DocuSign side). Default False sends only set fields.

    Returns:
        A flat dict ready to pass to `update_room_field_data(room_id, ...)`.
        The wrapping `{"data": ...}` is added by `update_room_field_data` itself.
    """
    out: dict[str, Any] = {}

    # Scalars
    for canonical_field, docusign_field in SCALAR_MAP.items():
        v = getattr(record, canonical_field, None)
        if v is None and not include_nulls:
            continue
        out[docusign_field] = _serialize(v, docusign_field)

    # Parties
    for canonical_attr, docusign_obj in PARTY_OBJECT_MAP.items():
        party: Party = getattr(record, canonical_attr)
        payload = _party_to_payload(party)
        if payload:
            out[docusign_obj] = payload

    return out


# ---------------------------------------------------------------------------
# Reverse: DocuSign payload -> canonical
# ---------------------------------------------------------------------------


def _deserialize_for_field(canonical_field: str, value: Any) -> Any:
    """Coerce a DocuSign value back into the canonical type.

    Pydantic handles most coercion at construction time, but for dates we
    must strip time/timezone suffixes DocuSign sometimes returns.
    """
    if value is None:
        return None
    if canonical_field.endswith("_date") or canonical_field.endswith("_deadline"):
        if isinstance(value, str):
            # DocuSign returns ISO 8601 sometimes with time component
            return value.split("T", 1)[0]
    return value


def from_room_field_data(data: dict[str, Any]) -> TransactionRecord:
    """Convert a DocuSign Rooms field_data dict to a canonical TransactionRecord.

    Unmapped DocuSign fields are dropped silently — only the fields we know
    about flow back. This is intentional: extending coverage means adding to
    SCALAR_MAP.
    """
    docusign_to_canonical = {v: k for k, v in SCALAR_MAP.items()}
    party_obj_reverse = {v: k for k, v in PARTY_OBJECT_MAP.items()}
    party_field_reverse = {v: k for k, v in PARTY_FIELD_MAP.items()}

    kwargs: dict[str, Any] = {}

    for docusign_key, value in data.items():
        # Scalar?
        if docusign_key in docusign_to_canonical:
            canonical_name = docusign_to_canonical[docusign_key]
            kwargs[canonical_name] = _deserialize_for_field(canonical_name, value)
            continue
        # Party?
        if docusign_key in party_obj_reverse and isinstance(value, dict):
            canonical_party = party_obj_reverse[docusign_key]
            party_kwargs: dict[str, Any] = {}
            for sub_k, sub_v in value.items():
                if sub_k in party_field_reverse:
                    party_kwargs[party_field_reverse[sub_k]] = sub_v
            if party_kwargs:
                kwargs[canonical_party] = Party(**party_kwargs)

    return TransactionRecord(**kwargs)
