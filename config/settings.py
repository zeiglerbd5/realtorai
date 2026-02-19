"""Application settings using Pydantic Settings."""

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
    graph_client_id: str = Field(default="", description="Azure AD app client ID")
    graph_tenant_id: str = Field(default="common", description="Azure AD tenant ID")
    # Client secret stored in Keychain, not in env

    # -------------------------------------------------------------------------
    # Model Configuration
    # -------------------------------------------------------------------------
    model_path: Path = Field(
        default=Path("models/llama-3.2-8b-q4"),
        description="Path to quantized model weights",
    )
    model_max_tokens: int = Field(default=2048, ge=256, le=8192)
    model_temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # -------------------------------------------------------------------------
    # Application Paths
    # -------------------------------------------------------------------------
    data_dir: Path = Field(default=Path("data"), description="Data storage directory")

    @property
    def db_path(self) -> Path:
        """SQLite database path."""
        return self.data_dir / "db" / "realtorai.db"

    @property
    def feedback_dir(self) -> Path:
        """Directory for feedback logs (RL training data)."""
        return self.data_dir / "logs" / "feedback"

    @property
    def cache_dir(self) -> Path:
        """Cache directory for temporary files."""
        return self.data_dir / "cache"

    # -------------------------------------------------------------------------
    # Web UI
    # -------------------------------------------------------------------------
    web_host: str = Field(default="127.0.0.1")
    web_port: int = Field(default=8420, ge=1024, le=65535)

    # -------------------------------------------------------------------------
    # Daemon
    # -------------------------------------------------------------------------
    daemon_poll_interval_seconds: int = Field(default=120, ge=30, le=600)
    daemon_socket_path: Path = Field(default=Path("/tmp/realtorai.sock"))

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")

    # -------------------------------------------------------------------------
    # Development
    # -------------------------------------------------------------------------
    debug: bool = Field(default=False)

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        for directory in [
            self.data_dir,
            self.db_path.parent,
            self.feedback_dir,
            self.cache_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    settings = Settings()
    settings.ensure_directories()
    return settings
