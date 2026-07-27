"""Transaction Tracker - manages deal from contract to close.

Tracks documents, dates, contacts, and milestones for both buyer
and seller representation. Integrates with DocuSign Transaction Rooms (DTR).

This is separate from the MLS feeder which handles listing creation.
The transaction tracker manages the deal once it's under contract.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from realtorai.storage.client_files import get_client_dir

logger = structlog.get_logger()


# Transaction tracker template
TRANSACTION_TEMPLATE = {
    "status": "active",  # active, closed, cancelled
    "representation": None,  # buyer, seller
    "created_at": None,
    "updated_at": None,
    "closed_at": None,

    # Property basics (may overlap with MLS feeder for sellers)
    "property": {
        "address": None,
        "city": None,
        "state": None,
        "postal_code": None,
        "year_built": None,  # Important for Lead Paint determination (pre-1978)
    },

    # Key dates extracted from P&S and addenda
    "dates": {
        "effective_date": None,  # P&S effective date
        "inspection_deadline": None,
        "emd_due_date": None,
        "loan_application_deadline": None,
        "appraisal_deadline": None,
        "closing_date": None,
        "walkthrough_date": None,
        # Contingency deadlines (can add more as needed)
        "financing_contingency": None,
        "sale_of_property_contingency": None,
    },

    # Financial
    "financial": {
        "purchase_price": None,
        "emd_amount": None,
        "emd_delivered": False,
        "emd_delivery_date": None,
        "loan_amount": None,
        "down_payment": None,
    },

    # Documents - tracking receipt and status
    "documents": {
        "purchase_sale_agreement": {"received": False, "date": None, "reviewed": False},
        # required if pre-1978
        "lead_paint_addendum": {"received": False, "date": None, "required": None},
        "deed": {"received": False, "date": None},
        "property_disclosures": {"received": False, "date": None, "signed_by_both": False},
        "addenda": [],  # list of {name, received, date}
        "loan_application_letter": {"received": False, "date": None},
        "proof_of_funds": {"received": False, "date": None},
        "appraisal": {"received": False, "date": None, "value": None},
        "inspection_report": {"received": False, "date": None},
        # Inspection Contingency Addendum
        "ica_repairs": {"received": False, "date": None, "verified": False},
        "closing_disclosure": {"received": False, "date": None, "reviewed": False},
        "settlement_statement": {"received": False, "date": None, "reviewed": False},
        "mls_spec_sheet": {"received": False, "date": None},
    },

    # Contacts involved in the transaction
    "contacts": {
        "client": {"name": None, "email": None, "phone": None},
        # buyer's or listing agent
        "other_agent": {"name": None, "email": None, "phone": None, "role": None},
        "lender": {"name": None, "email": None, "phone": None, "company": None},
        "title_company": {"name": None, "email": None, "phone": None, "attorney": None},
        "inspector": {"name": None, "email": None, "phone": None},
    },

    # Milestones / Status flags
    # Common milestones (both buyer and seller)
    "milestones": {
        "under_contract": {"completed": False, "date": None},
        "tc_email_sent": {"completed": False, "date": None},  # Initial TC email to lender/client
        "docs_uploaded_dtr": {"completed": False, "date": None},  # DocuSign Transaction Rooms
        "inspection_scheduled": {"completed": False, "date": None},
        "inspection_completed": {"completed": False, "date": None},
        "emd_confirmed": {"completed": False, "date": None},
        "title_company_chosen": {"completed": False, "date": None},
        "clear_to_close": {"completed": False, "date": None},
        "walkthrough_scheduled": {"completed": False, "date": None},
        "walkthrough_completed": {"completed": False, "date": None},
        "closing_scheduled": {"completed": False, "date": None},
        "closed": {"completed": False, "date": None},
    },

    # Seller-specific milestones
    "seller_milestones": {
        "mls_status_updated": {"completed": False, "date": None},  # Pending or Active UC
        "seller_disclosures_signed": {"completed": False, "date": None},
        "title_services_ordered": {"completed": False, "date": None},  # Deed prep, etc.
        "inspection_prep_email_sent": {"completed": False, "date": None},
        "utility_transfer_coordinated": {"completed": False, "date": None},
        "closing_statement_reviewed": {"completed": False, "date": None},
        "closing_gift_reminder": {"completed": False, "date": None},
    },

    # Buyer-specific milestones
    "buyer_milestones": {
        "loan_app_received": {"completed": False, "date": None},
        "proof_of_funds_received": {"completed": False, "date": None},
        "homeowners_insurance_quoted": {"completed": False, "date": None},
        "appraisal_ordered": {"completed": False, "date": None},
        "appraisal_received": {"completed": False, "date": None},
        "closing_disclosure_received": {"completed": False, "date": None},
        "closing_disclosure_reviewed": {"completed": False, "date": None},
        "home_warranty_decision": {"completed": False, "date": None},
        "utilities_setup_reminder": {"completed": False, "date": None},
        "comps_prepped_for_appraisal": {"completed": False, "date": None},
    },

    # Seller-specific fields
    "seller": {
        "mls_status_preference": None,  # "pending" or "active_under_contract"
        "title_services_needed": [],  # deed_prep, remote_closing, poa, tax_waiver
        "utility_transfer_done": False,
        "fuel_proration_needed": False,
        "propane_tank_leased": False,
    },

    # Buyer-specific fields
    "buyer": {
        "owners_title_insurance": None,  # recommended, declined, purchased
        "homeowners_insurance_quote": {"obtained": False, "company": None},
        "home_warranty": None,  # waived, purchased
    },

    # Notes and source tracking
    "notes": [],  # list of {date, source, content}
    "sources": [],  # list of {source, date, fields_updated} - tracks where data came from
}


def get_transaction_path(client_id: int, name: str) -> Path:
    """Get path to transaction tracker JSON file."""
    client_dir = get_client_dir(client_id, name)
    return client_dir / "transaction.json"


def get_transaction(client_id: int, name: str) -> dict[str, Any] | None:
    """Load transaction tracker for a client.

    Returns None if no transaction exists.
    """
    path = get_transaction_path(client_id, name)

    if not path.exists():
        return None

    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logger.error("transaction_read_error", path=str(path), error=str(e))
        return None


def create_transaction(
    client_id: int,
    name: str,
    representation: str | None = None,
) -> dict[str, Any]:
    """Create a new transaction tracker for a client.

    Args:
        client_id: Client database ID
        name: Client name
        representation: "buyer" or "seller" (auto-detected from client if not provided)

    Returns:
        The new transaction document
    """
    path = get_transaction_path(client_id, name)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Auto-detect representation from client's transaction_type if not provided
    if representation is None:
        try:
            # Import here to avoid circular imports
            import asyncio

            from realtorai.storage.database import get_database

            async def get_client_type():
                db = await get_database()
                client = await db.get_client(client_id)
                if client and client.get("transaction_type"):
                    tx_type = client["transaction_type"].lower()
                    if "buy" in tx_type:
                        return "buyer"
                    elif "sell" in tx_type:
                        return "seller"
                return "seller"  # Default

            # Try to run async function
            try:
                asyncio.get_running_loop()
                # If we're in an async context, we can't use run()
                representation = "seller"  # Default in async context
            except RuntimeError:
                representation = asyncio.run(get_client_type())
        except Exception as e:
            logger.warning("could_not_detect_client_type", error=str(e))
            representation = "seller"

    transaction = json.loads(json.dumps(TRANSACTION_TEMPLATE))  # Deep copy
    transaction["created_at"] = datetime.now().isoformat()
    transaction["updated_at"] = datetime.now().isoformat()
    transaction["representation"] = representation

    with open(path, "w") as f:
        json.dump(transaction, f, indent=2)

    logger.info("transaction_created", client_id=client_id, representation=representation)
    return transaction


def update_transaction(
    client_id: int,
    name: str,
    updates: dict[str, Any],
    source: str = "agent",
) -> dict[str, Any]:
    """Update transaction tracker with new data.

    Args:
        client_id: Client database ID
        name: Client name
        updates: Dict of fields to update (can be nested)
        source: Where data came from (email, document, agent, llm)

    Returns:
        Updated transaction document
    """
    transaction = get_transaction(client_id, name)

    if transaction is None:
        transaction = create_transaction(client_id, name)

    fields_updated = []

    def deep_update(target: dict, updates: dict, prefix: str = ""):
        """Recursively update nested dicts."""
        for key, value in updates.items():
            field_path = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                deep_update(target[key], value, field_path)
            else:
                if target.get(key) != value:
                    target[key] = value
                    fields_updated.append(field_path)

    deep_update(transaction, updates)

    # Update metadata
    transaction["updated_at"] = datetime.now().isoformat()

    if fields_updated:
        transaction["sources"].append({
            "source": source,
            "date": datetime.now().isoformat(),
            "fields_updated": fields_updated,
        })

    # Save
    path = get_transaction_path(client_id, name)
    with open(path, "w") as f:
        json.dump(transaction, f, indent=2)

    logger.info(
        "transaction_updated",
        client_id=client_id,
        source=source,
        fields_count=len(fields_updated),
    )

    return transaction


def set_milestone(
    client_id: int,
    name: str,
    milestone: str,
    completed: bool = True,
    date: str | None = None,
) -> dict[str, Any]:
    """Mark a milestone as completed.

    Args:
        client_id: Client database ID
        name: Client name
        milestone: Milestone key (e.g., "inspection_completed")
        completed: Whether milestone is completed
        date: Date of completion (defaults to now)
    """
    if date is None:
        date = datetime.now().isoformat()

    # Determine which milestone category this belongs to
    transaction = get_transaction(client_id, name)
    if not transaction:
        transaction = create_transaction(client_id, name)

    # Check if it's a role-specific milestone
    seller_milestones = ["mls_status_updated", "seller_disclosures_signed",
                         "title_services_ordered", "inspection_prep_email_sent",
                         "utility_transfer_coordinated", "closing_statement_reviewed",
                         "closing_gift_reminder"]
    buyer_milestones = ["loan_app_received", "proof_of_funds_received",
                        "homeowners_insurance_quoted", "appraisal_ordered",
                        "appraisal_received", "closing_disclosure_received",
                        "closing_disclosure_reviewed", "home_warranty_decision",
                        "utilities_setup_reminder", "comps_prepped_for_appraisal"]

    if milestone in seller_milestones:
        milestone_key = "seller_milestones"
    elif milestone in buyer_milestones:
        milestone_key = "buyer_milestones"
    else:
        milestone_key = "milestones"

    return update_transaction(
        client_id=client_id,
        name=name,
        updates={
            milestone_key: {
                milestone: {"completed": completed, "date": date}
            }
        },
        source="agent",
    )


def mark_document_received(
    client_id: int,
    name: str,
    document: str,
    date: str | None = None,
    **extra_fields,
) -> dict[str, Any]:
    """Mark a document as received.

    Args:
        client_id: Client database ID
        name: Client name
        document: Document key (e.g., "purchase_sale_agreement")
        date: Date received (defaults to now)
        **extra_fields: Additional fields to set (e.g., reviewed=True)
    """
    if date is None:
        date = datetime.now().isoformat()

    doc_update = {"received": True, "date": date}
    doc_update.update(extra_fields)

    return update_transaction(
        client_id=client_id,
        name=name,
        updates={"documents": {document: doc_update}},
        source="agent",
    )


def add_transaction_note(
    client_id: int,
    name: str,
    content: str,
    source: str = "agent",
) -> dict[str, Any]:
    """Add a note to the transaction."""
    transaction = get_transaction(client_id, name)
    if transaction is None:
        transaction = create_transaction(client_id, name)

    transaction["notes"].append({
        "date": datetime.now().isoformat(),
        "source": source,
        "content": content,
    })
    transaction["updated_at"] = datetime.now().isoformat()

    path = get_transaction_path(client_id, name)
    with open(path, "w") as f:
        json.dump(transaction, f, indent=2)

    return transaction


def get_transaction_progress(transaction: dict[str, Any]) -> dict[str, Any]:
    """Calculate transaction progress and what's pending.

    Returns dict with:
        - overall_pct: Overall completion percentage
        - milestones_completed: Count of completed milestones
        - milestones_total: Total milestones
        - documents_received: Count of received documents
        - next_actions: List of suggested next actions
        - overdue_dates: List of dates that have passed
    """
    milestones = transaction.get("milestones", {})
    documents = transaction.get("documents", {})
    dates = transaction.get("dates", {})
    representation = transaction.get("representation", "seller")

    # Get role-specific milestones
    if representation == "buyer":
        role_milestones = transaction.get("buyer_milestones", {})
    else:
        role_milestones = transaction.get("seller_milestones", {})

    # Combine common + role-specific milestones
    all_milestones = {**milestones, **role_milestones}

    # Count milestones
    completed = sum(
        1 for m in all_milestones.values() if isinstance(m, dict) and m.get("completed")
    )
    total = len(all_milestones)

    # Count documents (excluding addenda list)
    doc_received = 0
    doc_total = 0
    for key, doc in documents.items():
        if key == "addenda":
            continue
        if isinstance(doc, dict):
            doc_total += 1
            if doc.get("received"):
                doc_received += 1

    # Calculate overall progress (weighted: milestones 60%, docs 40%)
    milestone_pct = (completed / total * 100) if total > 0 else 0
    doc_pct = (doc_received / doc_total * 100) if doc_total > 0 else 0
    overall_pct = int(milestone_pct * 0.6 + doc_pct * 0.4)

    # Determine next actions based on what's not done
    next_actions = []

    # Common actions
    if not milestones.get("tc_email_sent", {}).get("completed"):
        next_actions.append("Send TC email to client and lender")

    if not milestones.get("docs_uploaded_dtr", {}).get("completed"):
        next_actions.append("Upload documents to DTR")

    if not documents.get("purchase_sale_agreement", {}).get("reviewed"):
        next_actions.append("Review P&S for errors")

    if not transaction.get("financial", {}).get("emd_delivered"):
        next_actions.append("Confirm EMD delivery")

    if not milestones.get("inspection_scheduled", {}).get("completed"):
        next_actions.append("Schedule inspection")

    if not milestones.get("title_company_chosen", {}).get("completed"):
        next_actions.append("Confirm title company choice")

    # Seller-specific actions
    if representation == "seller":
        if not role_milestones.get("mls_status_updated", {}).get("completed"):
            next_actions.append("Update MLS status (Pending/Active UC)")
        if not role_milestones.get("seller_disclosures_signed", {}).get("completed"):
            next_actions.append("Get seller disclosures signed")
        if not role_milestones.get("inspection_prep_email_sent", {}).get("completed"):
            next_actions.append("Send inspection prep email to seller")

    # Buyer-specific actions
    if representation == "buyer":
        if not role_milestones.get("loan_app_received", {}).get("completed"):
            next_actions.append("Get proof of loan application")
        if not role_milestones.get("homeowners_insurance_quoted", {}).get("completed"):
            next_actions.append("Get homeowners insurance quote")
        if not role_milestones.get("appraisal_ordered", {}).get("completed"):
            next_actions.append("Order appraisal")

    # Check for overdue dates
    overdue = []
    today = datetime.now().date()
    for date_name, date_str in dates.items():
        if date_str:
            try:
                date_val = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
                if date_val < today:
                    overdue.append({"name": date_name, "date": date_str})
            except (ValueError, TypeError):
                pass

    return {
        "overall_pct": overall_pct,
        "milestones_completed": completed,
        "milestones_total": total,
        "documents_received": doc_received,
        "documents_total": doc_total,
        "next_actions": next_actions[:5],  # Top 5 actions
        "overdue_dates": overdue,
        "representation": representation,
    }


def format_transaction_summary(transaction: dict[str, Any]) -> str:
    """Format transaction as human-readable summary for LLM context."""
    prop = transaction.get("property", {})
    dates = transaction.get("dates", {})
    financial = transaction.get("financial", {})
    progress = get_transaction_progress(transaction)

    address = prop.get("address") or "Address not set"

    lines = [
        f"Transaction Status: {transaction.get('status', 'active').upper()}",
        f"Representation: {transaction.get('representation', 'unknown').upper()}",
        f"Progress: {progress['overall_pct']}%",
        "",
        f"Property: {address}",
        f"Purchase Price: ${financial.get('purchase_price'):,}"
        if financial.get('purchase_price')
        else "Purchase Price: Not set",
        f"Closing Date: {dates.get('closing_date') or 'Not set'}",
        "",
        f"Milestones: {progress['milestones_completed']}/{progress['milestones_total']}",
        f"Documents: {progress['documents_received']}/{progress['documents_total']}",
    ]

    if progress["next_actions"]:
        lines.append("")
        lines.append("Next Actions:")
        for action in progress["next_actions"]:
            lines.append(f"  - {action}")

    if progress["overdue_dates"]:
        lines.append("")
        lines.append("OVERDUE:")
        for item in progress["overdue_dates"]:
            lines.append(f"  - {item['name']}: {item['date']}")

    return "\n".join(lines)
