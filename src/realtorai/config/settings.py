"""
RealtorAI Settings

Application configuration using Pydantic Settings.
Loads from environment variables and .env file.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Microsoft Graph API
    # -------------------------------------------------------------------------
    graph_client_id: str = Field(
        default="",
        description="Azure AD app client ID",
    )
    graph_tenant_id: str = Field(
        default="common",
        description="Azure AD tenant ID (use 'common' for multi-tenant)",
    )
    graph_redirect_uri: str = Field(
        default="http://localhost:8421/callback",
        description="OAuth redirect URI",
    )
    graph_scopes: list[str] = Field(
        default=[
            "Mail.Read",
            "Mail.Send",
            "Calendars.ReadWrite",
            "offline_access",
        ],
        description="Microsoft Graph API scopes",
    )

    # -------------------------------------------------------------------------
    # Spark API (FlexMLS/MREIS)
    # -------------------------------------------------------------------------
    spark_client_id: str = Field(
        default="",
        description="Spark API client ID from sparkplatform.com",
    )
    spark_client_secret: str = Field(
        default="",
        description="Spark API client secret",
    )
    spark_demo_token: str = Field(
        default="",
        description="Spark API demo access token for testing with example data",
    )

    # -------------------------------------------------------------------------
    # DocuSign Rooms API
    # -------------------------------------------------------------------------
    docusign_user_id: str = Field(
        default="",
        description="DocuSign User ID (GUID)",
    )
    docusign_account_id: str = Field(
        default="",
        description="DocuSign API Account ID (GUID)",
    )
    docusign_base_uri: str = Field(
        default="https://demo.rooms.docusign.com",
        description="DocuSign Account Base URI",
    )
    docusign_integration_key: str = Field(
        default="",
        description="DocuSign Integration Key (Client ID)",
    )
    docusign_secret_key: str = Field(
        default="",
        description="DocuSign Secret Key (for auth code grant)",
    )

    # -------------------------------------------------------------------------
    # Matterport API
    # -------------------------------------------------------------------------
    matterport_api_token: str = Field(
        default="",
        description="Matterport API token",
    )
    matterport_api_secret: str = Field(
        default="",
        description="Matterport API secret",
    )

    # -------------------------------------------------------------------------
    # Model Configuration
    # -------------------------------------------------------------------------
    model_name: str = Field(
        default="Qwen/Qwen3-8B-MLX-4bit",
        description="HuggingFace model ID for MLX inference",
    )
    model_max_tokens: int = Field(
        default=2048,
        ge=256,
        le=8192,
        description="Maximum tokens to generate",
    )
    model_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature",
    )

    # -------------------------------------------------------------------------
    # Application Paths
    # -------------------------------------------------------------------------
    data_dir: Path = Field(
        default=Path("data"),
        description="Data storage directory",
    )

    @property
    def db_path(self) -> Path:
        """SQLite database path."""
        return self.data_dir / "realtorai.db"

    @property
    def feedback_log_dir(self) -> Path:
        """Directory for feedback logs (RL training data)."""
        return self.data_dir / "logs" / "feedback"

    @property
    def cache_dir(self) -> Path:
        """Cache directory for temporary files."""
        return self.data_dir / "cache"

    @property
    def clients_dir(self) -> Path:
        """Directory for client markdown files."""
        return self.data_dir / "clients"

    # -------------------------------------------------------------------------
    # Web UI
    # -------------------------------------------------------------------------
    web_host: str = Field(
        default="127.0.0.1",
        description="Web server host",
    )
    web_port: int = Field(
        default=8421,
        ge=1024,
        le=65535,
        description="Web server port",
    )

    # -------------------------------------------------------------------------
    # Daemon
    # -------------------------------------------------------------------------
    daemon_poll_interval: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Email polling interval in seconds",
    )

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )

    # -------------------------------------------------------------------------
    # Development
    # -------------------------------------------------------------------------
    debug: bool = Field(
        default=False,
        description="Enable debug mode",
    )

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        directories = [
            self.data_dir,
            self.db_path.parent,
            self.feedback_log_dir,
            self.cache_dir,
            self.clients_dir,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    settings = Settings()
    settings.ensure_directories()
    return settings
