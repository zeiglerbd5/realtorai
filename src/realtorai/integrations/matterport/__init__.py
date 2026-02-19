"""Matterport 3D Tour integration.

Provides API access to Matterport tours for downloading
embed URLs and still images to client deal folders.

API Reference: https://matterport.github.io/showcase-sdk/docs/reference/current/
"""

from realtorai.integrations.matterport.auth import matterport_auth, MatterportAuth
from realtorai.integrations.matterport.client import get_matterport_client, MatterportClient
from realtorai.integrations.matterport.models import (
    get_model,
    get_model_snapshots,
    get_model_embed_url,
    list_models,
)
from realtorai.integrations.matterport.downloader import (
    download_tour_assets,
    get_client_matterport_dir,
    get_tour_info,
)
from realtorai.integrations.matterport.email_handler import (
    process_matterport_email,
    download_and_extract_zip,
    extract_download_url,
)

__all__ = [
    # Auth
    "matterport_auth",
    "MatterportAuth",
    # Client
    "get_matterport_client",
    "MatterportClient",
    # Models
    "get_model",
    "get_model_snapshots",
    "get_model_embed_url",
    "list_models",
    # Downloader
    "download_tour_assets",
    "get_client_matterport_dir",
    "get_tour_info",
    # Email handler
    "process_matterport_email",
    "download_and_extract_zip",
    "extract_download_url",
]
