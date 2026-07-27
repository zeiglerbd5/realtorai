"""Matterport asset downloader.

Downloads tour metadata and still images to client deal folders.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

from realtorai.config.settings import get_settings
from realtorai.integrations.matterport.models import (
    get_model,
    get_model_embed_url,
    get_model_snapshots,
)
from realtorai.storage.client_files import slugify

logger = structlog.get_logger()


def get_client_matterport_dir(client_id: int, name: str) -> Path:
    """Get the matterport directory path for a client.

    Args:
        client_id: Client database ID
        name: Client name

    Returns:
        Path to data/clients/{id}-{slug}/matterport/
    """
    settings = get_settings()
    slug = slugify(name)
    return settings.clients_dir / f"{client_id}-{slug}" / "matterport"


def get_stills_dir(client_id: int, name: str) -> Path:
    """Get the stills subdirectory path.

    Returns:
        Path to data/clients/{id}-{slug}/matterport/stills/
    """
    return get_client_matterport_dir(client_id, name) / "stills"


def get_tour_info_path(client_id: int, name: str) -> Path:
    """Get the tour_info.json file path.

    Returns:
        Path to data/clients/{id}-{slug}/matterport/tour_info.json
    """
    return get_client_matterport_dir(client_id, name) / "tour_info.json"


def get_tour_info(client_id: int, name: str) -> dict[str, Any] | None:
    """Read stored tour metadata for a client.

    Args:
        client_id: Client database ID
        name: Client name

    Returns:
        Tour info dict or None if not found
    """
    path = get_tour_info_path(client_id, name)

    if not path.exists():
        return None

    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logger.error("read_tour_info_error", path=str(path), error=str(e))
        return None


async def download_image(
    url: str,
    dest_path: Path,
    client: httpx.AsyncClient,
) -> bool:
    """Download a single image from URL to destination path.

    Args:
        url: Image URL
        dest_path: Local file path to save to
        client: HTTP client instance

    Returns:
        True if successful
    """
    try:
        response = await client.get(url)
        response.raise_for_status()

        dest_path.write_bytes(response.content)
        logger.debug("image_downloaded", url=url[:50], path=str(dest_path))
        return True

    except Exception as e:
        logger.error("image_download_error", url=url[:50], error=str(e))
        return False


async def download_tour_assets(
    client_id: int,
    client_name: str,
    model_id: str,
    max_images: int = 9999,
) -> dict[str, Any]:
    """Download Matterport tour assets to a client's folder.

    Creates the folder structure:
        data/clients/{id}-{slug}/matterport/
        ├── tour_info.json
        └── stills/
            ├── image_001.jpg
            └── ...

    Args:
        client_id: Client database ID
        client_name: Client name
        model_id: Matterport model ID (e.g., "SxQL3iGyoDo")
        max_images: Maximum images to download (default 40)

    Returns:
        Result dict with status, paths, and counts
    """
    logger.info(
        "downloading_matterport_tour",
        client_id=client_id,
        model_id=model_id,
        max_images=max_images,
    )

    # Create directories
    matterport_dir = get_client_matterport_dir(client_id, client_name)
    stills_dir = get_stills_dir(client_id, client_name)
    matterport_dir.mkdir(parents=True, exist_ok=True)
    stills_dir.mkdir(parents=True, exist_ok=True)

    # Get model details
    model = await get_model(model_id)
    if not model:
        return {
            "status": "error",
            "error": f"Model {model_id} not found",
            "matterport_dir": str(matterport_dir),
        }

    # Get snapshots
    snapshots = await get_model_snapshots(model_id, limit=max_images)

    # Generate embed URL
    embed_url = get_model_embed_url(model_id)

    # Save tour info
    tour_info = {
        "model_id": model_id,
        "name": model.get("name"),
        "description": model.get("description"),
        "embed_url": embed_url,
        "created": model.get("created"),
        "modified": model.get("modified"),
        "state": model.get("state"),
        "visibility": model.get("visibility"),
        "publication": model.get("publication"),
        "downloaded_at": datetime.now().isoformat(),
        "snapshot_count": len(snapshots),
        "client_id": client_id,
        "client_name": client_name,
    }

    tour_info_path = get_tour_info_path(client_id, client_name)
    with open(tour_info_path, "w") as f:
        json.dump(tour_info, f, indent=2)

    logger.info("tour_info_saved", path=str(tour_info_path))

    # Download images concurrently
    images_downloaded = 0

    if snapshots:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            tasks = []

            for i, snapshot in enumerate(snapshots, start=1):
                url = snapshot.get("url")
                if not url:
                    continue

                # Determine file extension from URL or default to jpg
                ext = ".jpg"
                if ".png" in url.lower():
                    ext = ".png"

                dest_path = stills_dir / f"image_{i:03d}{ext}"
                tasks.append(download_image(url, dest_path, http_client))

            # Run downloads concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            images_downloaded = sum(1 for r in results if r is True)

    logger.info(
        "matterport_download_complete",
        client_id=client_id,
        model_id=model_id,
        images_downloaded=images_downloaded,
    )

    return {
        "status": "success",
        "matterport_dir": str(matterport_dir),
        "stills_dir": str(stills_dir),
        "tour_info_path": str(tour_info_path),
        "images_downloaded": images_downloaded,
        "embed_url": embed_url,
        "model_name": model.get("name"),
    }
