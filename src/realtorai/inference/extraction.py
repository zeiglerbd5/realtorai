"""Data extraction from emails and documents.

Extracts structured data from unstructured content and populates:
- MLS feeder (for seller listings)
- Transaction tracker (for buyer/seller deals)
"""

import re
from typing import Any

import structlog
from pydantic import BaseModel, Field

from realtorai.inference.claude_engine import get_claude_engine
from realtorai.inference.engine import get_engine
from realtorai.inference.model_router import LLMTask
from realtorai.inference.prompts import (
    get_email_extraction_prompt,
    get_mls_extraction_prompt,
    get_transaction_extraction_prompt,
)
from realtorai.inference.tools import EXTRACTION_TOOLS
from realtorai.integrations.spark.mls_feeder import get_mls_feeder, update_mls_feeder
from realtorai.schemas.extraction import (
    ExtractionProposal,
    ExtractionType,
    FieldChange,
    PendingItemMatch,
)
from realtorai.storage.database import get_database
from realtorai.transactions import (
    add_transaction_note,
    get_transaction,
    mark_document_received,
    set_milestone,
    update_transaction,
)

logger = structlog.get_logger()


# Pydantic models for structured extraction
class ExtractedAddress(BaseModel):
    """Extracted property address."""
    street_number: str | None = None
    street_name: str | None = None
    street_suffix: str | None = None
    unit_number: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


class ExtractedProperty(BaseModel):
    """Extracted property details for MLS."""
    type: str | None = Field(None, description="Residential, Condo, Townhouse, Land, Multi-Family")
    year_built: int | None = None
    bedrooms: int | None = None
    bathrooms_full: int | None = None
    bathrooms_half: int | None = None
    living_area_sqft: int | None = None
    lot_size_sqft: int | None = None
    garage_spaces: int | None = None


class ExtractedListing(BaseModel):
    """Extracted MLS listing details."""
    price: int | None = None
    showing_instructions: str | None = None


class ExtractedMarketing(BaseModel):
    """Extracted marketing content."""
    public_remarks: str | None = None
    private_remarks: str | None = None
    virtual_tour_url: str | None = None


class ExtractedFeatures(BaseModel):
    """Extracted property features."""
    heating: list[str] = Field(default_factory=list)
    cooling: list[str] = Field(default_factory=list)
    appliances: list[str] = Field(default_factory=list)
    interior_features: list[str] = Field(default_factory=list)
    exterior_features: list[str] = Field(default_factory=list)


class MLSExtraction(BaseModel):
    """Full MLS feeder extraction result."""
    has_data: bool = Field(description="Whether any MLS data was found")
    address: ExtractedAddress | None = None
    property: ExtractedProperty | None = None
    listing: ExtractedListing | None = None
    marketing: ExtractedMarketing | None = None
    features: ExtractedFeatures | None = None


class ExtractedDates(BaseModel):
    """Extracted transaction dates."""
    effective_date: str | None = Field(None, description="P&S effective date")
    inspection_deadline: str | None = None
    emd_due_date: str | None = None
    loan_application_deadline: str | None = None
    appraisal_deadline: str | None = None
    closing_date: str | None = None
    walkthrough_date: str | None = None
    financing_contingency: str | None = None


class ExtractedFinancial(BaseModel):
    """Extracted financial details."""
    purchase_price: int | None = None
    emd_amount: int | None = None
    emd_delivered: bool | None = None
    loan_amount: int | None = None
    down_payment: int | None = None


class ExtractedContact(BaseModel):
    """Extracted contact info."""
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    role: str | None = None


class ExtractedContacts(BaseModel):
    """All extracted contacts."""
    other_agent: ExtractedContact | None = None
    lender: ExtractedContact | None = None
    title_company: ExtractedContact | None = None
    inspector: ExtractedContact | None = None


class ExtractedMilestones(BaseModel):
    """Extracted milestones that were completed."""
    under_contract: bool = False
    inspection_scheduled: bool = False
    inspection_completed: bool = False
    emd_confirmed: bool = False
    title_company_chosen: bool = False
    clear_to_close: bool = False
    closing_scheduled: bool = False
    closed: bool = False
    # Seller-specific
    mls_status_updated: bool = False
    seller_disclosures_signed: bool = False
    # Buyer-specific
    loan_app_received: bool = False
    appraisal_ordered: bool = False
    appraisal_received: bool = False
    closing_disclosure_received: bool = False


class ExtractedDocuments(BaseModel):
    """Extracted documents that were received."""
    purchase_sale_agreement: bool = False
    lead_paint_addendum: bool = False
    property_disclosures: bool = False
    loan_application_letter: bool = False
    proof_of_funds: bool = False
    appraisal: bool = False
    inspection_report: bool = False
    closing_disclosure: bool = False


class TransactionExtraction(BaseModel):
    """Full transaction extraction result."""
    has_data: bool = Field(description="Whether any transaction data was found")
    property_address: str | None = None
    dates: ExtractedDates | None = None
    financial: ExtractedFinancial | None = None
    contacts: ExtractedContacts | None = None
    milestones: ExtractedMilestones | None = None
    documents: ExtractedDocuments | None = None
    notes: str | None = Field(None, description="Important info to note")


class ExtractionResult(BaseModel):
    """Overall extraction classification."""
    data_type: str = Field(description="mls, transaction, both, or neither")
    confidence: str = Field(description="high, medium, or low")
    summary: str = Field(description="Brief summary of what was found")


async def classify_email_content(content: str) -> ExtractionResult:
    """Classify what type of extractable data is in an email.

    Returns classification of whether email contains:
    - mls: MLS listing data (property details for sellers)
    - transaction: Transaction data (dates, contacts, milestones)
    - both: Contains both types
    - neither: No extractable structured data
    """
    classification_prompt = """\
Analyze this email/document and classify what structured data it contains.

Content:
{content}

Classify as:
- "mls" if it contains property listing details (address, beds/baths, sqft, price, features)
- "transaction" if it contains deal data (closing dates, EMD, lender info, inspection dates)
- "both" if it contains both types
- "neither" if it doesn't contain extractable property/transaction data

Also rate your confidence (high/medium/low) and provide a brief summary."""

    claude = get_claude_engine()
    if claude.available:
        result = await claude.generate_structured(
            classification_prompt.format(content=content[:4000]),
            ExtractionResult,
            task=LLMTask.CLASSIFY,
            system_prompt="You are a real estate data classifier. Be precise.",
        )
    else:
        engine = await get_engine()
        result = await engine.generate_structured(
            prompt=classification_prompt.format(content=content[:4000]),
            output_schema=ExtractionResult,
            system_prompt="You are a real estate data classifier. Be precise.",
        )

    logger.info(
        "email_classified",
        data_type=result.data_type,
        confidence=result.confidence,
    )

    return result


async def extract_mls_data(content: str) -> MLSExtraction:
    """Extract MLS listing data from content.

    Used for seller clients to populate the MLS feeder.
    """
    claude = get_claude_engine()
    if claude.available:
        return await claude.generate_structured(
            f"Extract MLS listing data from this content:\n\n{content[:4000]}",
            MLSExtraction,
            task=LLMTask.EXTRACT,
            system_prompt=get_mls_extraction_prompt(),
        )

    engine = await get_engine()
    return await engine.generate_structured(
        prompt=f"Extract MLS listing data from this content:\n\n{content[:4000]}",
        output_schema=MLSExtraction,
        system_prompt=get_mls_extraction_prompt(),
    )


async def extract_transaction_data(content: str) -> TransactionExtraction:
    """Extract transaction data from content.

    Used for both buyer and seller clients to populate the transaction tracker.
    """
    claude = get_claude_engine()
    if claude.available:
        return await claude.generate_structured(
            f"Extract transaction data from this content:\n\n{content[:4000]}",
            TransactionExtraction,
            task=LLMTask.EXTRACT,
            system_prompt=get_transaction_extraction_prompt(),
        )

    engine = await get_engine()
    return await engine.generate_structured(
        prompt=f"Extract transaction data from this content:\n\n{content[:4000]}",
        output_schema=TransactionExtraction,
        system_prompt=get_transaction_extraction_prompt(),
    )


async def apply_mls_extraction(
    client_id: int,
    name: str,
    extraction: MLSExtraction,
    source: str = "email",
) -> dict[str, Any]:
    """Apply extracted MLS data to client's feeder.

    Returns dict with applied changes.
    """
    if not extraction.has_data:
        return {"applied": False, "reason": "No MLS data found"}

    updates = {}

    if extraction.address:
        addr_dict = extraction.address.model_dump(exclude_none=True)
        if addr_dict:
            updates["address"] = addr_dict

    if extraction.property:
        prop_dict = extraction.property.model_dump(exclude_none=True)
        if prop_dict:
            updates["property"] = prop_dict

    if extraction.listing:
        listing_dict = extraction.listing.model_dump(exclude_none=True)
        if listing_dict:
            updates["listing"] = listing_dict

    if extraction.marketing:
        marketing_dict = extraction.marketing.model_dump(exclude_none=True)
        if marketing_dict:
            updates["marketing"] = marketing_dict

    if extraction.features:
        features_dict = extraction.features.model_dump(exclude_none=True)
        # Only include non-empty lists
        features_dict = {k: v for k, v in features_dict.items() if v}
        if features_dict:
            updates["features"] = features_dict

    if not updates:
        return {"applied": False, "reason": "No extractable fields"}

    # Apply to feeder
    update_mls_feeder(client_id, name, updates, source=source)

    logger.info(
        "mls_extraction_applied",
        client_id=client_id,
        fields=list(updates.keys()),
    )

    return {
        "applied": True,
        "fields_updated": list(updates.keys()),
        "source": source,
    }


async def apply_transaction_extraction(
    client_id: int,
    name: str,
    extraction: TransactionExtraction,
    source: str = "email",
) -> dict[str, Any]:
    """Apply extracted transaction data to client's tracker.

    Returns dict with applied changes.
    """
    if not extraction.has_data:
        return {"applied": False, "reason": "No transaction data found"}

    updates = {}
    milestones_set = []
    documents_marked = []

    # Build updates dict
    if extraction.property_address:
        updates["property"] = {"address": extraction.property_address}

    if extraction.dates:
        dates_dict = extraction.dates.model_dump(exclude_none=True)
        if dates_dict:
            updates["dates"] = dates_dict

    if extraction.financial:
        financial_dict = extraction.financial.model_dump(exclude_none=True)
        if financial_dict:
            updates["financial"] = financial_dict

    if extraction.contacts:
        contacts_dict = {}
        for field, contact in extraction.contacts.model_dump(exclude_none=True).items():
            if contact and any(contact.values()):
                contacts_dict[field] = contact
        if contacts_dict:
            updates["contacts"] = contacts_dict

    # Apply main updates
    if updates:
        update_transaction(client_id, name, updates, source=source)

    # Set completed milestones
    if extraction.milestones:
        for milestone, completed in extraction.milestones.model_dump().items():
            if completed:
                set_milestone(client_id, name, milestone)
                milestones_set.append(milestone)

    # Mark received documents
    if extraction.documents:
        for doc, received in extraction.documents.model_dump().items():
            if received:
                mark_document_received(client_id, name, doc)
                documents_marked.append(doc)

    # Add note if provided
    if extraction.notes:
        add_transaction_note(client_id, name, extraction.notes, source=source)

    if not updates and not milestones_set and not documents_marked:
        return {"applied": False, "reason": "No extractable fields"}

    logger.info(
        "transaction_extraction_applied",
        client_id=client_id,
        fields=list(updates.keys()),
        milestones=milestones_set,
        documents=documents_marked,
    )

    return {
        "applied": True,
        "fields_updated": list(updates.keys()),
        "milestones_set": milestones_set,
        "documents_marked": documents_marked,
        "source": source,
    }


async def extract_from_email(
    client_id: int,
    name: str,
    email_content: str,
    email_subject: str | None = None,
    sender: str | None = None,
    representation: str | None = None,  # buyer or seller
) -> dict[str, Any]:
    """Process an email and extract all relevant data.

    This is the main entry point for email extraction.
    It classifies the email, extracts data, and applies it to the appropriate trackers.

    Args:
        client_id: Client database ID
        name: Client name
        email_content: Full email body
        email_subject: Optional email subject for context
        sender: Optional sender info for context
        representation: buyer or seller (affects what milestones are applicable)

    Returns:
        Dict with extraction results and what was applied
    """
    # Build full content for analysis
    full_content = ""
    if email_subject:
        full_content += f"Subject: {email_subject}\n"
    if sender:
        full_content += f"From: {sender}\n"
    full_content += f"\n{email_content}"

    # Classify what type of data is present
    classification = await classify_email_content(full_content)

    result = {
        "classification": classification.model_dump(),
        "mls_extraction": None,
        "transaction_extraction": None,
    }

    # Extract and apply based on classification
    if classification.data_type in ("mls", "both"):
        # Only extract MLS data for sellers
        if representation != "buyer":
            mls_data = await extract_mls_data(full_content)
            mls_result = await apply_mls_extraction(client_id, name, mls_data, source="email")
            result["mls_extraction"] = mls_result

    if classification.data_type in ("transaction", "both"):
        tx_data = await extract_transaction_data(full_content)
        tx_result = await apply_transaction_extraction(client_id, name, tx_data, source="email")
        result["transaction_extraction"] = tx_result

    logger.info(
        "email_extraction_complete",
        client_id=client_id,
        data_type=classification.data_type,
        mls_applied=result.get("mls_extraction", {}).get("applied", False),
        tx_applied=result.get("transaction_extraction", {}).get("applied", False),
    )

    return result


async def extract_from_document(
    client_id: int,
    name: str,
    document_text: str,
    document_type: str = "unknown",
    representation: str | None = None,
) -> dict[str, Any]:
    """Process a document (PDF text, etc.) and extract data.

    Similar to email extraction but optimized for document content.

    Args:
        client_id: Client database ID
        name: Client name
        document_text: Extracted text from document
        document_type: Type of document (p_and_s, inspection_report, appraisal, etc.)
        representation: buyer or seller

    Returns:
        Dict with extraction results
    """
    # Add document type context
    full_content = f"Document Type: {document_type}\n\n{document_text}"

    # For known document types, we can be more targeted
    if document_type in ("p_and_s", "purchase_sale_agreement"):
        # P&S contains transaction data
        tx_data = await extract_transaction_data(full_content)
        tx_result = await apply_transaction_extraction(
            client_id, name, tx_data, source=f"document:{document_type}"
        )
        # Also mark P&S as received
        mark_document_received(client_id, name, "purchase_sale_agreement")
        return {
            "classification": {"data_type": "transaction"},
            "transaction_extraction": tx_result,
        }

    elif document_type == "inspection_report":
        # Inspection report - mark received and extract any dates
        mark_document_received(client_id, name, "inspection_report")
        set_milestone(client_id, name, "inspection_completed")
        return {
            "classification": {"data_type": "transaction"},
            "document_marked": "inspection_report",
            "milestone_set": "inspection_completed",
        }

    elif document_type == "appraisal":
        mark_document_received(client_id, name, "appraisal")
        set_milestone(client_id, name, "appraisal_received")
        return {
            "classification": {"data_type": "transaction"},
            "document_marked": "appraisal",
            "milestone_set": "appraisal_received",
        }

    elif document_type == "mls_spec_sheet":
        # Seller property info
        mls_data = await extract_mls_data(full_content)
        mls_result = await apply_mls_extraction(
            client_id, name, mls_data, source=f"document:{document_type}"
        )
        mark_document_received(client_id, name, "mls_spec_sheet")
        return {
            "classification": {"data_type": "mls"},
            "mls_extraction": mls_result,
        }

    # For unknown document types, use full classification
    return await extract_from_email(
        client_id=client_id,
        name=name,
        email_content=document_text,
        representation=representation,
    )


def _get_nested_value(data: dict[str, Any] | None, path: str) -> Any:
    """Get a value from a nested dict using dot notation."""
    if data is None:
        return None
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def _extract_source_snippet(content: str, extraction: dict[str, Any], max_length: int = 300) -> str:
    """Extract a relevant snippet from content that supports the extraction.

    Looks for sentences containing key extracted values.
    """
    if not content:
        return ""

    # Flatten extraction to get all values
    def flatten_values(d: dict, values: list) -> list:
        for v in d.values():
            if isinstance(v, dict):
                flatten_values(v, values)
            elif isinstance(v, list):
                values.extend([str(x) for x in v if x])
            elif v is not None:
                values.append(str(v))
        return values

    search_values = flatten_values(extraction, [])

    # Filter to meaningful values (skip bools, very short strings)
    search_values = [v for v in search_values if len(v) > 3 and v.lower() not in ("true", "false")]

    if not search_values:
        return content[:max_length]

    # Find sentences containing extracted values
    sentences = re.split(r'[.!?\n]+', content)
    best_sentence = ""
    best_score = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 20:
            continue
        score = sum(1 for v in search_values if v.lower() in sentence.lower())
        if score > best_score:
            best_score = score
            best_sentence = sentence

    if best_sentence:
        return best_sentence[:max_length]
    return content[:max_length]


# Mapping of extracted fields to pending item descriptions (for fuzzy matching)
FIELD_TO_PENDING_ITEM_PATTERNS: dict[str, list[str]] = {
    # Dates
    "dates.closing_date": ["closing date", "closing confirmation", "close date"],
    "dates.inspection_deadline": ["inspection date", "inspection scheduled", "inspection deadline"],
    "dates.appraisal_deadline": ["appraisal date", "appraisal deadline"],
    "dates.effective_date": ["effective date", "contract date"],
    "dates.emd_due_date": ["emd", "earnest money", "deposit due"],
    "dates.loan_application_deadline": ["loan application", "mortgage application"],
    "dates.financing_contingency": ["financing contingency", "loan contingency"],
    "dates.walkthrough_date": ["walkthrough", "final walk"],
    # Contacts
    "contacts.lender": ["lender info", "lender contact", "loan officer", "mortgage"],
    "contacts.title_company": ["title company", "closing attorney", "title agent", "settlement"],
    "contacts.other_agent": [
        "agent contact", "other agent", "buyer agent", "seller agent", "listing agent"
    ],
    "contacts.inspector": ["inspector", "inspection contact"],
    # Financial
    "financial.purchase_price": ["purchase price", "offer amount", "sale price"],
    "financial.emd_amount": ["emd amount", "earnest money", "deposit amount"],
    "financial.loan_amount": ["loan amount", "mortgage amount"],
    "financial.down_payment": ["down payment"],
}

MILESTONE_TO_PENDING_ITEM_PATTERNS: dict[str, list[str]] = {
    "clear_to_close": ["clear to close", "ctc", "cleared to close"],
    "inspection_completed": ["inspection", "inspection report"],
    "appraisal_received": ["appraisal", "appraisal report"],
    "under_contract": ["contract", "under contract", "signed contract"],
    "emd_confirmed": ["emd", "earnest money", "deposit confirmed"],
    "closing_scheduled": ["closing scheduled", "closing date confirmed"],
    "loan_app_received": ["loan application", "mortgage application"],
    "closing_disclosure_received": ["closing disclosure", "cd"],
}


def _fuzzy_match_description(description: str, patterns: list[str]) -> bool:
    """Check if a pending item description fuzzy-matches any patterns."""
    desc_lower = description.lower()
    for pattern in patterns:
        if pattern.lower() in desc_lower:
            return True
    return False


async def find_matching_pending_items(
    client_id: int,
    changes: list[FieldChange],
    milestones: list[str],
    documents: list[str],
) -> list[PendingItemMatch]:
    """Find pending_items that would be resolved by these changes.

    Matches extracted fields/milestones/documents against pending items
    using fuzzy description matching.

    Args:
        client_id: Client database ID
        changes: List of field changes from extraction
        milestones: List of milestones to be set
        documents: List of documents to be marked

    Returns:
        List of PendingItemMatch objects for items that should be resolved
    """
    db = await get_database()
    pending_items = await db.get_pending_items(client_id=client_id, status="waiting")

    if not pending_items:
        return []

    matched = []
    matched_ids = set()  # Avoid duplicates

    # Check field changes against patterns
    for change in changes:
        field_path = change.field_path

        # Handle nested contact fields (e.g., contacts.lender.name -> contacts.lender)
        if field_path.startswith("contacts.") and field_path.count(".") > 1:
            # Extract the contact type (contacts.lender.name -> contacts.lender)
            parts = field_path.split(".")
            field_path = ".".join(parts[:2])

        patterns = FIELD_TO_PENDING_ITEM_PATTERNS.get(field_path, [])
        if not patterns:
            continue

        for item in pending_items:
            if item["id"] in matched_ids:
                continue
            if _fuzzy_match_description(item["description"], patterns):
                matched.append(PendingItemMatch(
                    id=item["id"],
                    description=item["description"],
                    waiting_on=item["waiting_on"],
                    item_type=item["item_type"],
                ))
                matched_ids.add(item["id"])

    # Check milestones against patterns
    for milestone in milestones:
        patterns = MILESTONE_TO_PENDING_ITEM_PATTERNS.get(milestone, [])
        if not patterns:
            continue

        for item in pending_items:
            if item["id"] in matched_ids:
                continue
            if _fuzzy_match_description(item["description"], patterns):
                matched.append(PendingItemMatch(
                    id=item["id"],
                    description=item["description"],
                    waiting_on=item["waiting_on"],
                    item_type=item["item_type"],
                ))
                matched_ids.add(item["id"])

    # Check documents - match directly by document name
    for doc in documents:
        doc_patterns = [
            doc.replace("_", " "),  # purchase_sale_agreement -> purchase sale agreement
            doc.replace("_", ""),   # purchase_sale_agreement -> purchasesaleagreement
        ]
        # Add common aliases
        doc_aliases = {
            "purchase_sale_agreement": ["p&s", "p and s", "purchase agreement", "sales contract"],
            "inspection_report": ["inspection", "home inspection"],
            "appraisal": ["appraisal report", "property appraisal"],
            "closing_disclosure": ["cd", "closing docs"],
            "proof_of_funds": ["pof", "bank statement", "funds verification"],
            "loan_application_letter": ["loan app", "mortgage app", "pre-approval"],
        }
        doc_patterns.extend(doc_aliases.get(doc, []))

        for item in pending_items:
            if item["id"] in matched_ids:
                continue
            if _fuzzy_match_description(item["description"], doc_patterns):
                matched.append(PendingItemMatch(
                    id=item["id"],
                    description=item["description"],
                    waiting_on=item["waiting_on"],
                    item_type=item["item_type"],
                ))
                matched_ids.add(item["id"])

    logger.info(
        "pending_items_matched",
        client_id=client_id,
        matched_count=len(matched),
        matched_ids=list(matched_ids),
    )

    return matched


def compute_mls_diff(
    client_id: int,
    name: str,
    extraction: MLSExtraction,
    content: str = "",
) -> list[FieldChange]:
    """Compute diff between current MLS feeder and proposed extraction.

    Args:
        client_id: Client database ID
        name: Client name
        extraction: MLS extraction result
        content: Original content for snippet extraction

    Returns:
        List of FieldChange objects representing the diff
    """
    current_feeder = get_mls_feeder(client_id, name)
    changes = []

    # Build flat dict of proposed updates
    proposed = {}
    if extraction.address:
        for field, value in extraction.address.model_dump(exclude_none=True).items():
            proposed[f"address.{field}"] = value
    if extraction.property:
        for field, value in extraction.property.model_dump(exclude_none=True).items():
            proposed[f"property.{field}"] = value
    if extraction.listing:
        for field, value in extraction.listing.model_dump(exclude_none=True).items():
            proposed[f"listing.{field}"] = value
    if extraction.marketing:
        for field, value in extraction.marketing.model_dump(exclude_none=True).items():
            proposed[f"marketing.{field}"] = value
    if extraction.features:
        for field, value in extraction.features.model_dump(exclude_none=True).items():
            if value:  # Skip empty lists
                proposed[f"features.{field}"] = value

    # Compare with current values
    for field_path, proposed_value in proposed.items():
        current_value = _get_nested_value(current_feeder, field_path)
        if current_value != proposed_value:
            # Extract snippet supporting this value
            snippet = ""
            if isinstance(proposed_value, str):
                snippet = _extract_source_snippet(
                    content, {field_path: proposed_value}, max_length=150
                )
            elif isinstance(proposed_value, (int, float)):
                snippet = _extract_source_snippet(
                    content, {field_path: str(proposed_value)}, max_length=150
                )

            changes.append(FieldChange(
                field_path=field_path,
                current_value=current_value,
                proposed_value=proposed_value,
                source_snippet=snippet,
            ))

    return changes


def compute_transaction_diff(
    client_id: int,
    name: str,
    extraction: TransactionExtraction,
    content: str = "",
) -> tuple[list[FieldChange], list[str], list[str]]:
    """Compute diff between current transaction and proposed extraction.

    Args:
        client_id: Client database ID
        name: Client name
        extraction: Transaction extraction result
        content: Original content for snippet extraction

    Returns:
        Tuple of (changes, milestones_to_set, documents_to_mark)
    """
    current_tx = get_transaction(client_id, name)
    changes = []
    milestones_to_set = []
    documents_to_mark = []

    # Build flat dict of proposed updates
    proposed = {}
    if extraction.property_address:
        proposed["property.address"] = extraction.property_address
    if extraction.dates:
        for field, value in extraction.dates.model_dump(exclude_none=True).items():
            proposed[f"dates.{field}"] = value
    if extraction.financial:
        for field, value in extraction.financial.model_dump(exclude_none=True).items():
            proposed[f"financial.{field}"] = value
    if extraction.contacts:
        contacts_dict = extraction.contacts.model_dump(exclude_none=True)
        for contact_type, contact_data in contacts_dict.items():
            if contact_data and any(contact_data.values()):
                for field, value in contact_data.items():
                    if value:
                        proposed[f"contacts.{contact_type}.{field}"] = value

    # Compare with current values
    for field_path, proposed_value in proposed.items():
        current_value = _get_nested_value(current_tx, field_path)
        if current_value != proposed_value:
            snippet = ""
            if isinstance(proposed_value, str):
                snippet = _extract_source_snippet(
                    content, {field_path: proposed_value}, max_length=150
                )

            changes.append(FieldChange(
                field_path=field_path,
                current_value=current_value,
                proposed_value=proposed_value,
                source_snippet=snippet,
            ))

    # Collect milestones to set
    if extraction.milestones:
        for milestone, completed in extraction.milestones.model_dump().items():
            if completed:
                # Check if not already set
                if current_tx:
                    current_completed = _get_nested_value(
                        current_tx, f"milestones.{milestone}.completed"
                    ) or _get_nested_value(
                        current_tx, f"buyer_milestones.{milestone}.completed"
                    ) or _get_nested_value(
                        current_tx, f"seller_milestones.{milestone}.completed"
                    )
                    if not current_completed:
                        milestones_to_set.append(milestone)
                else:
                    milestones_to_set.append(milestone)

    # Collect documents to mark
    if extraction.documents:
        for doc, received in extraction.documents.model_dump().items():
            if received:
                # Check if not already marked
                if current_tx:
                    current_received = _get_nested_value(current_tx, f"documents.{doc}.received")
                    if not current_received:
                        documents_to_mark.append(doc)
                else:
                    documents_to_mark.append(doc)

    return changes, milestones_to_set, documents_to_mark


async def create_extraction_proposals(
    client_id: int,
    name: str,
    email_content: str,
    email_subject: str | None = None,
    sender: str | None = None,
    representation: str | None = None,
) -> list[ExtractionProposal]:
    """Create extraction proposals for queuing (does NOT apply data).

    This replaces the auto-apply behavior with a proposal workflow.

    Args:
        client_id: Client database ID
        name: Client name
        email_content: Full email body
        email_subject: Optional email subject
        sender: Optional sender info
        representation: buyer or seller

    Returns:
        List of ExtractionProposal objects to be queued for approval
    """
    proposals = []

    # Build full content for analysis
    full_content = ""
    if email_subject:
        full_content += f"Subject: {email_subject}\n"
    if sender:
        full_content += f"From: {sender}\n"
    full_content += f"\n{email_content}"

    # Classify what type of data is present
    classification = await classify_email_content(full_content)

    if classification.data_type == "neither":
        return []

    # Extract source snippet for the overall proposal
    source_snippet = _extract_source_snippet(
        email_content,
        {"subject": email_subject or "", "sender": sender or ""},
        max_length=300
    )

    # Extract and compute diff for MLS data
    if classification.data_type in ("mls", "both"):
        if representation != "buyer":  # Only for sellers
            mls_extraction = await extract_mls_data(full_content)
            if mls_extraction.has_data:
                changes = compute_mls_diff(client_id, name, mls_extraction, email_content)
                if changes:
                    # Find matching pending items for MLS changes
                    pending_matches = await find_matching_pending_items(
                        client_id=client_id,
                        changes=changes,
                        milestones=[],
                        documents=[],
                    )
                    proposals.append(ExtractionProposal(
                        extraction_type=ExtractionType.MLS,
                        client_id=client_id,
                        client_name=name,
                        source_email_subject=email_subject,
                        source_email_from=sender,
                        source_snippet=source_snippet,
                        changes=changes,
                        raw_extraction=mls_extraction.model_dump(),
                        confidence=classification.confidence,
                        pending_items_to_resolve=pending_matches,
                    ))

    # Extract and compute diff for transaction data
    if classification.data_type in ("transaction", "both"):
        tx_extraction = await extract_transaction_data(full_content)
        if tx_extraction.has_data:
            changes, milestones, documents = compute_transaction_diff(
                client_id, name, tx_extraction, email_content
            )
            if changes or milestones or documents:
                # Find matching pending items for transaction changes
                pending_matches = await find_matching_pending_items(
                    client_id=client_id,
                    changes=changes,
                    milestones=milestones,
                    documents=documents,
                )
                proposals.append(ExtractionProposal(
                    extraction_type=ExtractionType.TRANSACTION,
                    client_id=client_id,
                    client_name=name,
                    source_email_subject=email_subject,
                    source_email_from=sender,
                    source_snippet=source_snippet,
                    changes=changes,
                    raw_extraction=tx_extraction.model_dump(),
                    confidence=classification.confidence,
                    milestones_to_set=milestones,
                    documents_to_mark=documents,
                    pending_items_to_resolve=pending_matches,
                ))

    logger.info(
        "extraction_proposals_created",
        client_id=client_id,
        proposal_count=len(proposals),
        types=[p.extraction_type.value for p in proposals],
    )

    return proposals


async def process_with_tools(
    client_id: int,
    name: str,
    content: str,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Process content using LLM tool calling.

    Alternative approach that lets the LLM decide which tools to call.
    More flexible but may be less reliable than structured extraction.
    """
    engine = await get_engine()

    prompt = f"""Analyze this content and extract any relevant data for client ID {client_id}.

Content:
{content[:4000]}

If you find MLS listing data (property details), use update_mls_feeder.
If you find transaction data (dates, contacts, milestones), use update_transaction, \
set_milestone, or mark_document_received as appropriate.
"""

    result = await engine.call_tool(
        prompt=prompt,
        tools=EXTRACTION_TOOLS,
        system_prompt=system_prompt or get_email_extraction_prompt(),
    )

    return result
