"""Matterport model (tour) operations.

Provides functions to query tour details, snapshots, and generate embed URLs.
"""

from typing import Any

import structlog

from realtorai.integrations.matterport.client import get_matterport_client

logger = structlog.get_logger()


async def get_model(model_id: str) -> dict[str, Any] | None:
    """Get details for a specific Matterport model (tour).

    Args:
        model_id: The Matterport model ID (e.g., "SxQL3iGyoDo")

    Returns:
        Model details dict or None if not found
    """
    client = get_matterport_client()

    query = """
    query GetModel($modelId: ID!) {
        model(id: $modelId) {
            id
            name
            description
            created
            modified
            visibility
            state
            publication {
                description
                summary
                address
                published
            }
        }
    }
    """

    try:
        data = await client.query(query, {"modelId": model_id})
        model = data.get("model")

        if model:
            logger.info("matterport_model_fetched", model_id=model_id, name=model.get("name"))

        return model

    except Exception as e:
        logger.error("matterport_get_model_error", model_id=model_id, error=str(e))
        return None


async def get_model_snapshots(
    model_id: str,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Get snapshot (still image) URLs for a model via panoramic skybox images.

    Args:
        model_id: The Matterport model ID
        limit: Maximum number of snapshots to return (default 40)

    Returns:
        List of snapshot dicts with 'id', 'url', etc.
    """
    client = get_matterport_client()

    # Query for panoramic images from sweep locations
    query = """
    query GetModelSnapshots($modelId: ID!) {
        model(id: $modelId) {
            id
            name
            locations {
                id
                position { x y z }
                panos {
                    id
                    skybox(resolution: "2k") {
                        id
                        status
                        format
                        children
                    }
                }
            }
        }
    }
    """

    try:
        data = await client.query(query, {"modelId": model_id})
        model = data.get("model")

        if not model:
            logger.warning("matterport_model_not_found", model_id=model_id)
            return []

        # Extract image URLs from locations/panos/skybox
        snapshots = []
        locations = model.get("locations", [])

        for location in locations:
            if len(snapshots) >= limit:
                break

            panos = location.get("panos", [])
            for pano in panos:
                if len(snapshots) >= limit:
                    break

                skybox = pano.get("skybox")
                if skybox and skybox.get("children"):
                    # children contains the image URLs
                    for url in skybox.get("children", []):
                        if len(snapshots) >= limit:
                            break
                        snapshots.append({
                            "id": f"{location.get('id')}_{pano.get('id')}_{len(snapshots)}",
                            "url": url,
                            "location_id": location.get("id"),
                            "pano_id": pano.get("id"),
                        })

        logger.info(
            "matterport_snapshots_fetched",
            model_id=model_id,
            count=len(snapshots),
        )

        return snapshots

    except Exception as e:
        logger.error("matterport_get_snapshots_error", model_id=model_id, error=str(e))
        return []


def get_model_embed_url(
    model_id: str,
    autoplay: bool = True,
    help: bool = False,
    hl: int = 0,
    play: bool = True,
    qs: bool = True,
    brand: bool = False,
    mls: bool = True,
) -> str:
    """Generate an embeddable iframe URL for a Matterport model.

    Args:
        model_id: The Matterport model ID
        autoplay: Start tour automatically
        help: Show help hints
        hl: Highlight color (0 = none)
        play: Enable playback
        qs: Quickstart
        brand: Show Matterport branding
        mls: MLS-friendly mode

    Returns:
        Embed URL for iframe src
    """
    base_url = "https://my.matterport.com/show/"

    params = [
        f"m={model_id}",
    ]

    if autoplay:
        params.append("autoplay=1")
    if not help:
        params.append("help=0")
    if hl:
        params.append(f"hl={hl}")
    if play:
        params.append("play=1")
    if qs:
        params.append("qs=1")
    if not brand:
        params.append("brand=0")
    if mls:
        params.append("mls=1")

    url = f"{base_url}?{'&'.join(params)}"

    logger.debug("matterport_embed_url_generated", model_id=model_id, url=url)
    return url


async def list_models(
    limit: int = 50,
    search_query: str = "*",
) -> list[dict[str, Any]]:
    """List available Matterport models for the account.

    Args:
        limit: Maximum models to return
        search_query: Search query (default "*" for all)

    Returns:
        List of model summary dicts
    """
    client = get_matterport_client()

    query = """
    query ListModels($query: String!) {
        models(query: $query) {
            totalResults
            results {
                id
                name
                description
                created
                modified
                visibility
                state
            }
        }
    }
    """

    try:
        data = await client.query(query, {"query": search_query})
        results = data.get("models", {}).get("results", [])

        # Apply limit
        models = results[:limit]

        logger.info("matterport_models_listed", count=len(models))
        return models

    except Exception as e:
        logger.error("matterport_list_models_error", error=str(e))
        return []


def format_model_summary(model: dict[str, Any]) -> str:
    """Format a model dict as a readable summary string."""
    model_id = model.get("id", "unknown")
    name = model.get("name", "Untitled")
    state = model.get("state", "unknown")
    created = model.get("created", "")[:10] if model.get("created") else ""

    return f"- {name} (ID: {model_id}) — {state}, Created: {created}"
