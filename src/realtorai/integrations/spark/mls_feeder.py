"""MLS Feeder - accumulates listing data for MLS submission.

The MLS feeder is a JSON document that collects property details from
various sources (emails, documents, conversations) and prepares them
for submission to the MLS.

Workflow:
1. LLM extracts property info from emails/docs → updates feeder
2. Agent curates photos → saves to matterport/stills/
3. Agent reviews feeder in our dashboard (quick check)
4. System creates DRAFT listing in FlexMLS (not published)
5. Agent reviews in FlexMLS interface (sees exactly what will go live)
6. Agent clicks publish IN FLEXMLS (they own final submit)

This ensures no "lost in translation" - agent sees the actual MLS
interface before anything goes live.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from realtorai.storage.client_files import get_client_dir

logger = structlog.get_logger()


# MLS feeder template with common RESO fields
MLS_FEEDER_TEMPLATE = {
    "status": "draft",  # draft, ready, submitted
    "created_at": None,
    "updated_at": None,
    "submitted_at": None,
    "mls_listing_id": None,  # Set after submission

    # Property Address
    "address": {
        "street_number": None,
        "street_name": None,
        "street_suffix": None,  # St, Ave, Rd, etc.
        "unit_number": None,
        "city": None,
        "state": None,
        "postal_code": None,
        "county": None,
    },

    # Property Details
    "property": {
        "type": None,  # Residential, Condo, Townhouse, Land, Multi-Family
        "subtype": None,  # Single Family, Duplex, etc.
        "year_built": None,
        "bedrooms": None,
        "bathrooms_full": None,
        "bathrooms_half": None,
        "living_area_sqft": None,
        "lot_size_sqft": None,
        "lot_size_acres": None,
        "stories": None,
        "garage_spaces": None,
        "parking_spaces": None,
    },

    # Listing Info
    "listing": {
        "price": None,
        "agent_id": None,
        "office_id": None,
        "list_date": None,
        "expiration_date": None,
        "showing_instructions": None,
        "lockbox_type": None,
        "lockbox_code": None,
    },

    # Description & Marketing
    "marketing": {
        "public_remarks": None,  # Main listing description
        "private_remarks": None,  # Agent-only notes
        "directions": None,
        "virtual_tour_url": None,  # Matterport embed URL goes here
    },

    # Features & Amenities
    "features": {
        "heating": [],
        "cooling": [],
        "flooring": [],
        "appliances": [],
        "interior_features": [],
        "exterior_features": [],
        "lot_features": [],
        "community_features": [],
        "water_source": None,
        "sewer": None,
        "utilities": [],
    },

    # Room Details (optional)
    "rooms": [],

    # Financial
    "financial": {
        "hoa_fee": None,
        "hoa_frequency": None,  # Monthly, Annually, etc.
        "tax_amount": None,
        "tax_year": None,
    },

    # Media
    "media": {
        "photos_folder": None,  # Path to curated stills
        "photo_count": 0,
        "matterport_model_id": None,
        "matterport_embed_url": None,
        "video_url": None,
        "floor_plan_url": None,
    },

    # Metadata - tracks where info came from
    "sources": [],  # List of {source, date, fields_updated}
}


def get_mls_feeder_path(client_id: int, name: str) -> Path:
    """Get the path to the MLS feeder JSON file."""
    client_dir = get_client_dir(client_id, name)
    return client_dir / "mls_feeder.json"


def get_mls_feeder(client_id: int, name: str) -> dict[str, Any] | None:
    """Read the MLS feeder for a client.

    Returns None if no feeder exists yet.
    """
    path = get_mls_feeder_path(client_id, name)

    if not path.exists():
        return None

    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logger.error("mls_feeder_read_error", path=str(path), error=str(e))
        return None


def create_mls_feeder(client_id: int, name: str) -> dict[str, Any]:
    """Create a new MLS feeder for a client.

    Returns the new feeder document.
    """
    path = get_mls_feeder_path(client_id, name)
    path.parent.mkdir(parents=True, exist_ok=True)

    feeder = MLS_FEEDER_TEMPLATE.copy()
    feeder = json.loads(json.dumps(feeder))  # Deep copy
    feeder["created_at"] = datetime.now().isoformat()
    feeder["updated_at"] = datetime.now().isoformat()

    with open(path, 'w') as f:
        json.dump(feeder, f, indent=2)

    logger.info("mls_feeder_created", client_id=client_id, path=str(path))
    return feeder


def update_mls_feeder(
    client_id: int,
    name: str,
    updates: dict[str, Any],
    source: str = "llm",
) -> dict[str, Any]:
    """Update the MLS feeder with new data.

    Args:
        client_id: Client database ID
        name: Client name
        updates: Dict of fields to update (can be nested)
        source: Where the data came from (email, document, conversation, agent)

    Returns:
        The updated feeder document
    """
    feeder = get_mls_feeder(client_id, name)

    if feeder is None:
        feeder = create_mls_feeder(client_id, name)

    # Track which fields are being updated
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

    deep_update(feeder, updates)

    # Update metadata
    feeder["updated_at"] = datetime.now().isoformat()

    if fields_updated:
        feeder["sources"].append({
            "source": source,
            "date": datetime.now().isoformat(),
            "fields_updated": fields_updated,
        })

    # Save
    path = get_mls_feeder_path(client_id, name)
    with open(path, 'w') as f:
        json.dump(feeder, f, indent=2)

    logger.info(
        "mls_feeder_updated",
        client_id=client_id,
        source=source,
        fields_count=len(fields_updated),
    )

    return feeder


def set_feeder_status(
    client_id: int,
    name: str,
    status: str,
    mls_listing_id: str | None = None,
) -> dict[str, Any]:
    """Update the feeder status.

    Args:
        client_id: Client database ID
        name: Client name
        status: New status (draft, ready, submitted)
        mls_listing_id: MLS listing ID if submitted
    """
    feeder = get_mls_feeder(client_id, name)

    if feeder is None:
        raise ValueError(f"No MLS feeder found for client {client_id}")

    feeder["status"] = status

    if status == "submitted":
        feeder["submitted_at"] = datetime.now().isoformat()
        if mls_listing_id:
            feeder["mls_listing_id"] = mls_listing_id

    feeder["updated_at"] = datetime.now().isoformat()

    path = get_mls_feeder_path(client_id, name)
    with open(path, 'w') as f:
        json.dump(feeder, f, indent=2)

    logger.info("mls_feeder_status_changed", client_id=client_id, status=status)
    return feeder


def link_matterport_to_feeder(
    client_id: int,
    name: str,
    model_id: str,
    embed_url: str,
) -> dict[str, Any]:
    """Link a Matterport tour to the MLS feeder."""
    return update_mls_feeder(
        client_id=client_id,
        name=name,
        updates={
            "media": {
                "matterport_model_id": model_id,
                "matterport_embed_url": embed_url,
            },
            "marketing": {
                "virtual_tour_url": embed_url,
            },
        },
        source="matterport",
    )


def update_photos_in_feeder(client_id: int, name: str) -> dict[str, Any]:
    """Scan the stills folder and update photo count in feeder."""
    from realtorai.integrations.matterport.downloader import get_client_matterport_dir

    stills_dir = get_client_matterport_dir(client_id, name) / "stills"

    photo_count = 0
    if stills_dir.exists():
        photo_count = len([
            f for f in stills_dir.iterdir()
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')
        ])

    return update_mls_feeder(
        client_id=client_id,
        name=name,
        updates={
            "media": {
                "photos_folder": str(stills_dir) if stills_dir.exists() else None,
                "photo_count": photo_count,
            },
        },
        source="system",
    )


def get_feeder_completeness(feeder: dict[str, Any]) -> dict[str, Any]:
    """Check how complete the feeder is for MLS submission.

    Returns a report of missing required fields.
    """
    required_fields = {
        "address.street_number": feeder.get("address", {}).get("street_number"),
        "address.street_name": feeder.get("address", {}).get("street_name"),
        "address.city": feeder.get("address", {}).get("city"),
        "address.state": feeder.get("address", {}).get("state"),
        "address.postal_code": feeder.get("address", {}).get("postal_code"),
        "property.type": feeder.get("property", {}).get("type"),
        "property.bedrooms": feeder.get("property", {}).get("bedrooms"),
        "property.bathrooms_full": feeder.get("property", {}).get("bathrooms_full"),
        "property.living_area_sqft": feeder.get("property", {}).get("living_area_sqft"),
        "listing.price": feeder.get("listing", {}).get("price"),
        "marketing.public_remarks": feeder.get("marketing", {}).get("public_remarks"),
    }

    missing = [field for field, value in required_fields.items() if value is None]
    filled = [field for field, value in required_fields.items() if value is not None]

    return {
        "complete": len(missing) == 0,
        "completeness_pct": round(len(filled) / len(required_fields) * 100),
        "filled_count": len(filled),
        "total_required": len(required_fields),
        "missing_fields": missing,
    }


def format_feeder_summary(feeder: dict[str, Any]) -> str:
    """Format feeder as human-readable summary for LLM context."""
    addr = feeder.get("address", {})
    prop = feeder.get("property", {})
    listing = feeder.get("listing", {})
    media = feeder.get("media", {})

    address_str = " ".join(filter(None, [
        addr.get("street_number"),
        addr.get("street_name"),
        addr.get("street_suffix"),
    ]))
    if addr.get("city"):
        address_str += f", {addr.get('city')}"
    if addr.get("state"):
        address_str += f", {addr.get('state')}"
    if addr.get("postal_code"):
        address_str += f" {addr.get('postal_code')}"

    completeness = get_feeder_completeness(feeder)

    lines = [
        f"MLS Feeder Status: {feeder.get('status', 'draft').upper()}",
        f"Completeness: {completeness['completeness_pct']}%",
        "",
        f"Address: {address_str or 'Not set'}",
        f"Type: {prop.get('type') or 'Not set'}",
        f"Price: ${listing.get('price'):,}" if listing.get('price') else "Price: Not set",
        f"Beds/Baths: {prop.get('bedrooms') or '?'} bed / {prop.get('bathrooms_full') or '?'} bath",
        f"Sqft: {prop.get('living_area_sqft'):,}"
        if prop.get('living_area_sqft')
        else "Sqft: Not set",
        "",
        f"Photos: {media.get('photo_count', 0)}",
        f"Virtual Tour: {'Yes' if media.get('matterport_embed_url') else 'No'}",
    ]

    if completeness['missing_fields']:
        lines.append("")
        lines.append(f"Missing: {', '.join(completeness['missing_fields'])}")

    return "\n".join(lines)
