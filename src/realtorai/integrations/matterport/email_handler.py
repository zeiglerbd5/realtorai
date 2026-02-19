"""Handle Matterport download emails.

Processes emails from Matterport containing zip download links,
downloads the assets, and routes them to the appropriate client folder.
"""

import re
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import structlog

from realtorai.config.settings import get_settings
from realtorai.storage.client_files import slugify
from realtorai.integrations.matterport.downloader import get_client_matterport_dir

logger = structlog.get_logger()

# Patterns to find Matterport download links in emails
MATTERPORT_LINK_PATTERNS = [
    r'https?://[^\s<>"]*matterport\.com[^\s<>"]*\.zip[^\s<>"]*',
    r'https?://[^\s<>"]*matterport[^\s<>"]*download[^\s<>"]*',
    r'https?://my\.matterport\.com/api/[^\s<>"]+',
]


def extract_download_url(email_body: str) -> str | None:
    """Extract Matterport download URL from email body.

    Args:
        email_body: The email body text (plain text or HTML)

    Returns:
        The download URL if found, None otherwise
    """
    for pattern in MATTERPORT_LINK_PATTERNS:
        match = re.search(pattern, email_body, re.IGNORECASE)
        if match:
            url = match.group(0)
            # Clean up any trailing punctuation or HTML artifacts
            url = re.sub(r'[<>\"\'].*$', '', url)
            logger.info("matterport_download_url_found", url=url[:80])
            return url

    logger.warning("no_matterport_download_url_found")
    return None


def extract_model_info(email_body: str) -> dict[str, Any]:
    """Extract model/property info from email to help identify the client.

    Args:
        email_body: The email body text

    Returns:
        Dict with any extracted info (address, model_name, etc.)
    """
    info = {}

    # Try to find property address patterns
    address_patterns = [
        r'(?:property|address|location)[\s:]+([^\n<]+)',
        r'(\d+\s+[A-Za-z]+\s+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Blvd|Boulevard)[^\n<]*)',
    ]

    for pattern in address_patterns:
        match = re.search(pattern, email_body, re.IGNORECASE)
        if match:
            info['address'] = match.group(1).strip()
            break

    # Try to find model/space name
    name_patterns = [
        r'(?:model|space|tour)[\s:]+["\']?([^"\'<\n]+)["\']?',
        r'(?:your|the)\s+([^<\n]+?)\s+(?:is ready|has been)',
    ]

    for pattern in name_patterns:
        match = re.search(pattern, email_body, re.IGNORECASE)
        if match:
            info['model_name'] = match.group(1).strip()
            break

    return info


async def download_and_extract_zip(
    url: str,
    client_id: int,
    client_name: str,
) -> dict[str, Any]:
    """Download a Matterport zip file and extract to client folder.

    Args:
        url: The download URL for the zip file
        client_id: Client database ID
        client_name: Client name for folder path

    Returns:
        Result dict with status and details
    """
    logger.info(
        "downloading_matterport_zip",
        client_id=client_id,
        url=url[:80],
    )

    matterport_dir = get_client_matterport_dir(client_id, client_name)
    matterport_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get('content-type', '')

            # Check if it's actually a zip file
            if 'zip' not in content_type and not response.content[:4] == b'PK\x03\x04':
                # Not a zip, might be a redirect page or error
                logger.warning("matterport_download_not_zip", content_type=content_type)
                return {
                    "status": "error",
                    "error": f"Download was not a zip file (got {content_type})",
                }

            # Extract zip contents
            zip_buffer = BytesIO(response.content)

            with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
                file_list = zip_ref.namelist()

                # Extract all files
                for file_name in file_list:
                    # Skip directories and hidden files
                    if file_name.endswith('/') or file_name.startswith('__'):
                        continue

                    # Determine destination based on file type
                    ext = Path(file_name).suffix.lower()

                    if ext in ('.jpg', '.jpeg', '.png', '.webp'):
                        dest_dir = matterport_dir / "stills"
                    elif ext in ('.obj', '.fbx', '.gltf', '.glb'):
                        dest_dir = matterport_dir / "models"
                    elif ext in ('.pdf',):
                        dest_dir = matterport_dir / "floorplans"
                    elif ext in ('.json', '.xml'):
                        dest_dir = matterport_dir / "metadata"
                    else:
                        dest_dir = matterport_dir / "other"

                    dest_dir.mkdir(parents=True, exist_ok=True)

                    # Extract file
                    dest_path = dest_dir / Path(file_name).name
                    with zip_ref.open(file_name) as src, open(dest_path, 'wb') as dst:
                        dst.write(src.read())

                logger.info(
                    "matterport_zip_extracted",
                    client_id=client_id,
                    files_count=len(file_list),
                )

                # Count files by type
                images = sum(1 for f in file_list if Path(f).suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'))
                models = sum(1 for f in file_list if Path(f).suffix.lower() in ('.obj', '.fbx', '.gltf', '.glb'))

                # Save download info
                import json
                info_path = matterport_dir / "download_info.json"
                with open(info_path, 'w') as f:
                    json.dump({
                        "download_url": url,
                        "downloaded_at": datetime.now().isoformat(),
                        "files_count": len(file_list),
                        "images_count": images,
                        "models_count": models,
                        "client_id": client_id,
                        "client_name": client_name,
                    }, f, indent=2)

                return {
                    "status": "success",
                    "matterport_dir": str(matterport_dir),
                    "files_extracted": len(file_list),
                    "images_count": images,
                    "models_count": models,
                }

    except httpx.HTTPStatusError as e:
        logger.error("matterport_download_http_error", status=e.response.status_code)
        return {
            "status": "error",
            "error": f"HTTP error: {e.response.status_code}",
        }
    except zipfile.BadZipFile:
        logger.error("matterport_download_bad_zip")
        return {
            "status": "error",
            "error": "Downloaded file is not a valid zip",
        }
    except Exception as e:
        logger.error("matterport_download_error", error=str(e))
        return {
            "status": "error",
            "error": str(e),
        }


async def process_matterport_email(
    email_body: str,
    client_id: int,
    client_name: str,
) -> dict[str, Any]:
    """Process a Matterport email and download assets to client folder.

    Args:
        email_body: The full email body text
        client_id: Client database ID to route files to
        client_name: Client name for folder path

    Returns:
        Result dict with status and details
    """
    # Extract download URL
    url = extract_download_url(email_body)

    if not url:
        return {
            "status": "error",
            "error": "No Matterport download link found in email",
        }

    # Extract any model info for logging
    model_info = extract_model_info(email_body)
    logger.info("matterport_email_parsed", model_info=model_info)

    # Download and extract
    result = await download_and_extract_zip(url, client_id, client_name)

    if model_info:
        result["model_info"] = model_info

    return result
