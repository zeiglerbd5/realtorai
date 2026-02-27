"""Document template rendering."""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Template directory (in source for distribution)
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Client documents directory (in data for runtime)
DOCS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "clients"


def render_template(template_name: str, context: dict[str, Any]) -> str:
    """Render a template with the given context.

    Uses {{variable}} syntax for placeholders.
    """
    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_name}")

    content = template_path.read_text()

    # Replace all {{variable}} placeholders
    def replace_var(match: re.Match) -> str:
        var_name = match.group(1)
        value = context.get(var_name, "")
        return str(value) if value else f"[{var_name}]"

    return re.sub(r"\{\{(\w+)\}\}", replace_var, content)


def render_buyer_agency_agreement(
    buyer_name: str,
    buyer_email: str | None = None,
    buyer_phone: str | None = None,
    buyer_address: str | None = None,
    property_type: str = "Single Family Home",
    locations: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    min_beds: int = 3,
    min_baths: float = 2,
    other_requirements: str | None = None,
    commission_percent: float = 2.5,
    term_months: int = 6,
    agent_license: str = "ME-XXXXXX",
    agency_address: str = "Portland, ME",
    agency_phone: str = "(207) 555-0100",
    agency_email: str = "brett@zeiglerrealty.com",
) -> str:
    """Render a buyer agency agreement for a client.

    Args:
        buyer_name: Client's full name
        buyer_email: Client's email address
        buyer_phone: Client's phone number
        buyer_address: Client's current address
        property_type: Type of property sought
        locations: Target locations/areas
        min_price: Minimum price range
        max_price: Maximum price range
        min_beds: Minimum bedrooms
        min_baths: Minimum bathrooms
        other_requirements: Additional requirements
        commission_percent: Agent commission percentage
        term_months: Agreement term in months
        agent_license: Agent's license number
        agency_address: Agency address
        agency_phone: Agency phone
        agency_email: Agency email

    Returns:
        Rendered agreement as markdown string
    """
    today = datetime.now()
    end_date = today + timedelta(days=term_months * 30)

    context = {
        "date": today.strftime("%B %d, %Y"),
        "buyer_name": buyer_name,
        "buyer_name_2": "",  # For second buyer if applicable
        "buyer_email": buyer_email or "[Email]",
        "buyer_phone": buyer_phone or "[Phone]",
        "buyer_address": buyer_address or "[Address]",
        "agent_license": agent_license,
        "agency_address": agency_address,
        "agency_phone": agency_phone,
        "agency_email": agency_email,
        "start_date": today.strftime("%B %d, %Y"),
        "end_date": end_date.strftime("%B %d, %Y"),
        "property_type": property_type,
        "locations": locations or "[Target Areas]",
        "min_price": f"{min_price:,}" if min_price else "[Min]",
        "max_price": f"{max_price:,}" if max_price else "[Max]",
        "min_beds": str(min_beds),
        "min_baths": str(min_baths),
        "other_requirements": other_requirements or "None specified",
        "commission_percent": str(commission_percent),
        "flat_fee": "",
        "excluded_properties": "None",
        "termination_notice_days": "14",
        "protection_period_days": "90",
        "document_id": f"BAA-{today.strftime('%Y%m%d')}-{hash(buyer_name) % 10000:04d}",
        "generated_date": today.strftime("%Y-%m-%d %H:%M"),
    }

    return render_template("buyer_agency_agreement.md", context)


def save_rendered_document(
    content: str,
    client_id: int,
    client_name: str,
    document_type: str,
) -> Path:
    """Save a rendered document to the client's folder.

    Args:
        content: Rendered document content
        client_id: Client database ID
        client_name: Client name (for folder)
        document_type: Type of document (e.g., "buyer_agency_agreement")

    Returns:
        Path to saved document
    """
    # Create client documents folder
    safe_name = re.sub(r"[^\w\s-]", "", client_name).strip().replace(" ", "_")
    client_dir = DOCS_DIR / f"{client_id}_{safe_name}" / "documents"
    client_dir.mkdir(parents=True, exist_ok=True)

    # Save document
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{document_type}_{timestamp}.md"
    doc_path = client_dir / filename
    doc_path.write_text(content)

    return doc_path
