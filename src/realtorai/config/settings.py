"""
RealtorAI Settings

Application configuration using Pydantic Settings.
Loads from environment variables and .env file.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    docusign_backend: Literal["mock", "live"] = Field(
        default="mock",
        description=(
            "Rooms API backend. 'mock' runs a local simulator (no broker API "
            "approval needed); 'live' talks to docusign_base_uri."
        ),
    )

    # -------------------------------------------------------------------------
    # MLS backend (Maine Listings / FlexMLS via Spark API)
    # -------------------------------------------------------------------------
    mls_backend: Literal["mock", "live"] = Field(
        default="mock",
        description=(
            "MLS submission backend. 'mock' stores draft listings locally; "
            "'live' submits to the Spark API (requires MLS approval)."
        ),
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
    # Document templates
    # -------------------------------------------------------------------------
    tw_template_path: Path = Field(
        default=Path("data/templates/Transaction-Worksheet.pdf"),
        description=(
            "Blank The Agency Transaction Worksheet (fillable PDF). Internal "
            "brokerage form — keep out of git; the fill step skips if missing."
        ),
    )
    mis_template_path: Path = Field(
        default=Path("data/templates/Master-Information-Sheet.pdf"),
        description=(
            "agency team Master Information Sheet (fillable, 89 fields). "
            "Internal form — keep out of git; the fill step skips if missing."
        ),
    )

    # -------------------------------------------------------------------------
    # Public records
    # -------------------------------------------------------------------------
    public_records_live: bool = Field(
        default=True,
        description=(
            "Fetch live public records (FEMA flood determination via NFHL). "
            "Falls back to manual pull sheets on any failure; set false for "
            "fully offline runs."
        ),
    )

    # -------------------------------------------------------------------------
    # Claude API (cloud inference for workflow automation)
    # -------------------------------------------------------------------------
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key. Empty = workflow LLM steps degrade to offline mode.",
    )
    claude_model_standard: str = Field(
        default="claude-sonnet-5",
        description="Model for high-volume structured work: extraction, form fill, classification",
    )
    claude_model_review: str = Field(
        default="claude-opus-4-8",
        description="Model for high-stakes review: verification passes, deed review",
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
        le=32768,
        description="Maximum tokens to generate (upper bound = Qwen3 native context)",
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

    @property
    def transactions_dir(self) -> Path:
        """Directory for transaction records, workflow state, and artifacts."""
        return self.data_dir / "transactions"

    @property
    def mock_docusign_dir(self) -> Path:
        """State directory for the mock DocuSign Rooms backend."""
        return self.data_dir / "mock_docusign"

    @property
    def mock_mls_dir(self) -> Path:
        """State directory for the mock MLS backend."""
        return self.data_dir / "mock_mls"

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
            self.transactions_dir,
            self.mock_docusign_dir,
            self.mock_mls_dir,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    settings = Settings()
    settings.ensure_directories()
    return settings
