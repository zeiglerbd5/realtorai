"""Spark API listing submission - creates draft listings in FlexMLS.

Workflow:
1. Convert MLS feeder data to Spark API format
2. Create draft listing via POST /listings
3. Request photo upload ticket
4. Upload photos from curated stills folder
5. Agent reviews draft in FlexMLS and publishes

API Reference: https://sparkplatform.com/docs/api_services/listings
"""

import asyncio
import mimetypes
from pathlib import Path
from typing import Any

import httpx
import structlog

from realtorai.config.settings import get_settings
from realtorai.integrations.spark.client import get_spark_client, SPARK_API_BASE
from realtorai.integrations.spark.auth import spark_auth
from realtorai.integrations.spark.mls_feeder import (
    get_mls_feeder,
    set_feeder_status,
    get_feeder_completeness,
)


def _mock_backend() -> bool:
    """True when MLS submission should hit the local simulator."""
    return get_settings().mls_backend == "mock"

logger = structlog.get_logger()


# Map our property types to Spark API codes
# These will need adjustment based on actual MLS field values
PROPERTY_TYPE_MAP = {
    "Residential": "A",
    "Condo": "B",
    "Townhouse": "C",
    "Multi-Family": "D",
    "Land": "E",
    "Commercial": "F",
}

PROPERTY_SUBTYPE_MAP = {
    "Single Family": "SF",
    "Duplex": "DU",
    "Triplex": "TR",
    "Fourplex": "FO",
}


class ListingSubmissionError(Exception):
    """Error during listing submission to MLS."""

    def __init__(self, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.errors = errors or []


def feeder_to_spark_payload(feeder: dict[str, Any]) -> dict[str, Any]:
    """Convert MLS feeder format to Spark API request body.

    Args:
        feeder: MLS feeder document from our system

    Returns:
        Dict in Spark API format for POST /listings
    """
    addr = feeder.get("address", {})
    prop = feeder.get("property", {})
    listing = feeder.get("listing", {})
    marketing = feeder.get("marketing", {})
    financial = feeder.get("financial", {})

    # Build the Spark API payload
    # Only include non-null values
    payload: dict[str, Any] = {}

    # Property type (required)
    prop_type = prop.get("type")
    if prop_type and prop_type in PROPERTY_TYPE_MAP:
        payload["PropertyType"] = PROPERTY_TYPE_MAP[prop_type]

    prop_subtype = prop.get("subtype")
    if prop_subtype and prop_subtype in PROPERTY_SUBTYPE_MAP:
        payload["PropertySubType"] = PROPERTY_SUBTYPE_MAP[prop_subtype]

    # Address fields
    if addr.get("street_number"):
        payload["StreetNumber"] = str(addr["street_number"])
    if addr.get("street_name"):
        payload["StreetName"] = addr["street_name"]
    if addr.get("street_suffix"):
        payload["StreetSuffix"] = addr["street_suffix"]
    if addr.get("unit_number"):
        payload["UnitNumber"] = str(addr["unit_number"])
    if addr.get("city"):
        payload["City"] = addr["city"]
    if addr.get("state"):
        payload["StateOrProvince"] = addr["state"]
    if addr.get("postal_code"):
        payload["PostalCode"] = str(addr["postal_code"])
    if addr.get("county"):
        payload["CountyOrParish"] = addr["county"]

    # Property details
    if listing.get("price"):
        payload["ListPrice"] = int(listing["price"])
    if prop.get("year_built"):
        payload["YearBuilt"] = int(prop["year_built"])
    if prop.get("bedrooms"):
        payload["BedsTotal"] = int(prop["bedrooms"])
    if prop.get("bathrooms_full"):
        payload["BathsFull"] = int(prop["bathrooms_full"])
    if prop.get("bathrooms_half"):
        payload["BathsHalf"] = int(prop["bathrooms_half"])
    if prop.get("living_area_sqft"):
        payload["BuildingAreaTotal"] = int(prop["living_area_sqft"])
    if prop.get("lot_size_sqft"):
        payload["LotSizeSquareFeet"] = int(prop["lot_size_sqft"])
    if prop.get("stories"):
        payload["StoriesTotal"] = int(prop["stories"])
    if prop.get("garage_spaces"):
        payload["GarageSpaces"] = int(prop["garage_spaces"])
    if prop.get("garage_yn") is not None:
        payload["GarageYN"] = bool(prop["garage_yn"])
    if prop.get("rooms_total"):
        payload["RoomsTotal"] = int(prop["rooms_total"])
    if prop.get("fireplaces_total") is not None:
        payload["FireplacesTotal"] = int(prop["fireplaces_total"])
    if prop.get("lot_size_acres"):
        payload["LotSizeAcres"] = float(prop["lot_size_acres"])

    # Features
    feats = feeder.get("features", {})
    if feats.get("water_source"):
        payload["WaterSource"] = feats["water_source"]
    if feats.get("sewer"):
        payload["Sewer"] = feats["sewer"]

    # Marketing/description
    if marketing.get("public_remarks"):
        payload["PublicRemarks"] = marketing["public_remarks"]
    if marketing.get("private_remarks"):
        payload["PrivateRemarks"] = marketing["private_remarks"]
    if marketing.get("directions"):
        payload["Directions"] = marketing["directions"]
    if marketing.get("virtual_tour_url"):
        payload["VirtualTourURLUnbranded"] = marketing["virtual_tour_url"]

    # Listing info
    if listing.get("showing_instructions"):
        payload["ShowingInstructions"] = listing["showing_instructions"]

    # Financial
    if financial.get("hoa_fee"):
        payload["AssociationFee"] = int(financial["hoa_fee"])
    if financial.get("tax_amount"):
        payload["TaxAnnualAmount"] = int(financial["tax_amount"])
    if financial.get("tax_year"):
        payload["TaxYear"] = int(financial["tax_year"])

    return payload


async def validate_feeder_for_submission(
    client_id: int,
    name: str,
) -> tuple[bool, list[str]]:
    """Validate that a feeder is ready for MLS submission.

    Args:
        client_id: Client database ID
        name: Client name

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    feeder = get_mls_feeder(client_id, name)

    if not feeder:
        return False, ["No MLS feeder found for this client"]

    completeness = get_feeder_completeness(feeder)
    errors = []

    if not completeness["complete"]:
        for field in completeness["missing_fields"]:
            errors.append(f"Missing required field: {field}")

    # Additional validation
    prop_type = feeder.get("property", {}).get("type")
    if prop_type and prop_type not in PROPERTY_TYPE_MAP:
        errors.append(f"Unknown property type: {prop_type}")

    price = feeder.get("listing", {}).get("price")
    if price and (price < 1000 or price > 100_000_000):
        errors.append(f"Price {price} seems invalid (must be $1K-$100M)")

    return len(errors) == 0, errors


async def get_listing_rules(property_type: str) -> dict[str, Any]:
    """Fetch MLS listing rules for a property type.

    This tells us which fields are required, optional, and valid values.

    Args:
        property_type: Spark property type code (A, B, C, etc.)

    Returns:
        Dict with field rules and validations
    """
    client = get_spark_client()

    try:
        data = await client.get(
            f"/listings/rules/propertytypes/{property_type}"
        )
        rules = data.get("D", {}).get("Results", [])

        logger.info("listing_rules_fetched", property_type=property_type, rule_count=len(rules))
        return {
            "property_type": property_type,
            "rules": rules,
        }

    except Exception as e:
        logger.error("listing_rules_error", property_type=property_type, error=str(e))
        return {"property_type": property_type, "rules": []}


async def create_draft_listing(
    client_id: int,
    name: str,
) -> dict[str, Any]:
    """Create a draft listing in FlexMLS from the MLS feeder.

    The listing is created as a DRAFT - agent must review and publish
    in the FlexMLS interface.

    Args:
        client_id: Client database ID
        name: Client name

    Returns:
        Dict with listing_id and listing_key on success

    Raises:
        ListingSubmissionError: If validation or API call fails
    """
    # Validate first
    is_valid, errors = await validate_feeder_for_submission(client_id, name)
    if not is_valid:
        raise ListingSubmissionError("Feeder validation failed", [{"message": e} for e in errors])

    feeder = get_mls_feeder(client_id, name)
    if not feeder:
        raise ListingSubmissionError("No MLS feeder found")

    # Convert to Spark format
    payload = feeder_to_spark_payload(feeder)

    logger.info(
        "creating_draft_listing",
        client_id=client_id,
        field_count=len(payload),
        backend="mock" if _mock_backend() else "live",
    )

    if _mock_backend():
        from realtorai.integrations.spark.mock import get_mock_mls

        result = get_mock_mls().create_listing(payload)
        set_feeder_status(
            client_id=client_id,
            name=name,
            status="submitted",
            mls_listing_id=result["listing_id"],
        )
        return result

    # Make API call
    client = get_spark_client()

    try:
        # Spark API expects {"D": {...}} wrapper
        request_body = {"D": payload}

        token = await spark_auth.get_access_token()
        if not token:
            raise ListingSubmissionError("Not authenticated with Spark API")

        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.post(
                f"{SPARK_API_BASE}/listings",
                json=request_body,
                headers={"Authorization": f"OAuth {token}"},
            )

            data = response.json()

            if response.status_code == 200 and data.get("D", {}).get("Success"):
                result = data["D"]["Results"][0]
                listing_key = result.get("ListingKey")
                listing_id = result.get("ListingId")

                # Update feeder status
                set_feeder_status(
                    client_id=client_id,
                    name=name,
                    status="submitted",
                    mls_listing_id=listing_id,
                )

                logger.info(
                    "draft_listing_created",
                    client_id=client_id,
                    listing_key=listing_key,
                    listing_id=listing_id,
                )

                return {
                    "listing_key": listing_key,
                    "listing_id": listing_id,
                    "status": "draft",
                }

            else:
                # Extract error details
                api_errors = data.get("D", {}).get("Errors", [])
                error_msgs = [e.get("Message", str(e)) for e in api_errors]

                logger.error(
                    "listing_create_failed",
                    status=response.status_code,
                    errors=error_msgs,
                )
                raise ListingSubmissionError(
                    f"API returned {response.status_code}",
                    api_errors,
                )

    except httpx.HTTPError as e:
        logger.exception("listing_create_http_error", error=str(e))
        raise ListingSubmissionError(f"HTTP error: {e}")


async def get_photo_upload_ticket(listing_key: str) -> dict[str, Any]:
    """Request a photo upload ticket for a listing.

    Tickets are temporary tokens that allow uploading photos without
    full API authentication.

    Args:
        listing_key: The ListingKey from create_draft_listing

    Returns:
        Dict with token, uri, and expires_in
    """
    if _mock_backend():
        return {"token": "mock-token", "uri": f"mock://photos/{listing_key}", "expires_in": 3600}

    token = await spark_auth.get_access_token()
    if not token:
        raise ListingSubmissionError("Not authenticated with Spark API")

    async with httpx.AsyncClient(timeout=30.0) as http:
        response = await http.post(
            f"{SPARK_API_BASE}/listings/{listing_key}/photos/tickets",
            json={"D": {"Service": "PhotoUploads"}},
            headers={"Authorization": f"OAuth {token}"},
        )

        data = response.json()

        if response.status_code == 200 and data.get("D", {}).get("Success"):
            result = data["D"]["Results"][0]
            return {
                "token": result.get("Token"),
                "uri": result.get("Uri"),
                "expires_in": result.get("ExpiresIn"),
            }
        else:
            errors = data.get("D", {}).get("Errors", [])
            raise ListingSubmissionError("Failed to get upload ticket", errors)


async def upload_photo(
    upload_uri: str,
    upload_token: str,
    photo_path: Path,
    caption: str | None = None,
    is_primary: bool = False,
) -> str | None:
    """Upload a single photo to a listing.

    Args:
        upload_uri: URI from the upload ticket
        upload_token: Token from the upload ticket
        photo_path: Path to the image file
        caption: Optional caption (max 1000 chars)
        is_primary: Whether this is the primary listing photo

    Returns:
        Photo ID on success, None on failure
    """
    if not photo_path.exists():
        logger.warning("photo_not_found", path=str(photo_path))
        return None

    if upload_uri.startswith("mock://"):
        from realtorai.integrations.spark.mock import get_mock_mls

        listing_key = upload_uri.removeprefix("mock://photos/")
        photo_id = get_mock_mls().add_photo(listing_key, photo_path.name, is_primary=is_primary)
        logger.info("photo_uploaded", photo_id=photo_id, name=photo_path.name, backend="mock")
        return photo_id

    # Determine content type
    content_type, _ = mimetypes.guess_type(str(photo_path))
    if not content_type:
        content_type = "image/jpeg"

    try:
        with open(photo_path, "rb") as f:
            files = {
                "File": (photo_path.name, f, content_type),
            }
            data = {
                "Token": upload_token,
                "Name": photo_path.stem,
            }

            if caption:
                data["Caption"] = caption[:1000]
            if is_primary:
                data["Primary"] = "true"

            async with httpx.AsyncClient(timeout=60.0) as http:
                response = await http.post(
                    upload_uri,
                    data=data,
                    files=files,
                )

                result = response.json()

                if response.status_code == 200 and result.get("D", {}).get("Success"):
                    photo_id = result["D"]["Results"][0].get("Id")
                    logger.info("photo_uploaded", photo_id=photo_id, name=photo_path.name)
                    return photo_id
                else:
                    logger.error("photo_upload_failed", path=str(photo_path), response=result)
                    return None

    except Exception as e:
        logger.exception("photo_upload_error", path=str(photo_path), error=str(e))
        return None


async def upload_listing_photos(
    listing_key: str,
    photos_dir: Path,
    max_photos: int = 50,
) -> dict[str, Any]:
    """Upload all photos from a directory to a listing.

    Photos are uploaded in filename order, with the first becoming primary.

    Args:
        listing_key: The ListingKey for the listing
        photos_dir: Directory containing photos
        max_photos: Maximum photos to upload (MLS limits vary)

    Returns:
        Dict with upload stats
    """
    if not photos_dir.exists():
        return {"uploaded": 0, "failed": 0, "error": "Photos directory not found"}

    # Get all image files, sorted by name
    photo_files = sorted([
        f for f in photos_dir.iterdir()
        if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')
    ])[:max_photos]

    if not photo_files:
        return {"uploaded": 0, "failed": 0, "error": "No photos found"}

    # Get upload ticket
    try:
        ticket = await get_photo_upload_ticket(listing_key)
    except ListingSubmissionError as e:
        return {"uploaded": 0, "failed": 0, "error": str(e)}

    uploaded = 0
    failed = 0

    for i, photo_path in enumerate(photo_files):
        is_primary = (i == 0)  # First photo is primary

        photo_id = await upload_photo(
            upload_uri=ticket["uri"],
            upload_token=ticket["token"],
            photo_path=photo_path,
            is_primary=is_primary,
        )

        if photo_id:
            uploaded += 1
        else:
            failed += 1

        # Small delay to avoid rate limiting
        if i < len(photo_files) - 1:
            await asyncio.sleep(0.5)

    logger.info(
        "photos_upload_complete",
        listing_key=listing_key,
        uploaded=uploaded,
        failed=failed,
    )

    return {
        "uploaded": uploaded,
        "failed": failed,
        "total": len(photo_files),
    }


async def submit_listing_with_photos(
    client_id: int,
    name: str,
) -> dict[str, Any]:
    """Full workflow: create draft listing and upload photos.

    This is the main entry point for submitting a listing to FlexMLS.

    Args:
        client_id: Client database ID
        name: Client name

    Returns:
        Dict with listing info and photo upload results
    """
    # Get feeder to find photos directory
    feeder = get_mls_feeder(client_id, name)
    if not feeder:
        raise ListingSubmissionError("No MLS feeder found")

    # Create the draft listing
    listing_result = await create_draft_listing(client_id, name)

    # Upload photos if available
    photos_folder = feeder.get("media", {}).get("photos_folder")
    photo_result = {"uploaded": 0, "failed": 0}

    if photos_folder:
        photos_dir = Path(photos_folder)
        photo_result = await upload_listing_photos(
            listing_key=listing_result["listing_key"],
            photos_dir=photos_dir,
        )

    return {
        "listing_key": listing_result["listing_key"],
        "listing_id": listing_result["listing_id"],
        "status": "draft",
        "photos": photo_result,
        "message": (
            f"Draft listing created with {photo_result['uploaded']} photos. "
            "Review and publish in FlexMLS."
        ),
    }


async def get_listing_status(listing_key: str) -> dict[str, Any] | None:
    """Check the current status of a submitted listing.

    Args:
        listing_key: The ListingKey from submission

    Returns:
        Listing data including status, or None if not found
    """
    if _mock_backend():
        from realtorai.integrations.spark.mock import get_mock_mls

        listing = get_mock_mls().get_listing(listing_key)
        if listing is None:
            return None
        return {
            "listing_key": listing["ListingKey"],
            "listing_id": listing["ListingId"],
            "status": listing["StandardStatus"],
            "mls_status": listing["MlsStatus"],
            "price": listing["Payload"].get("ListPrice"),
            "modification_timestamp": listing["ModificationTimestamp"],
        }

    client = get_spark_client()

    try:
        data = await client.get(f"/listings/{listing_key}")
        results = data.get("D", {}).get("Results", [])

        if results:
            listing = results[0]
            return {
                "listing_key": listing.get("ListingKey"),
                "listing_id": listing.get("ListingId"),
                "status": listing.get("StandardStatus"),
                "mls_status": listing.get("MlsStatus"),
                "price": listing.get("ListPrice"),
                "modification_timestamp": listing.get("ModificationTimestamp"),
            }
        return None

    except Exception as e:
        logger.error("listing_status_error", listing_key=listing_key, error=str(e))
        return None
