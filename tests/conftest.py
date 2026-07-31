"""
Pytest configuration and fixtures for RealtorAI tests.
"""

import asyncio
import tempfile
from collections.abc import Generator
from datetime import UTC
from pathlib import Path

import pytest
import pytest_asyncio

#: Every env var that could let a test reach a real service or a real account.
#: Blanked for the whole suite by `_no_ambient_secrets` below.
_AMBIENT_SECRETS = (
    "ANTHROPIC_API_KEY",
    "DOCUSIGN_CLIENT_ID",
    "DOCUSIGN_CLIENT_SECRET",
    "DOCUSIGN_ACCOUNT_ID",
    "SPARK_API_KEY",
    "SPARK_CLIENT_ID",
    "SPARK_CLIENT_SECRET",
    "SPARK_DEMO_TOKEN",
    "GRAPH_CLIENT_ID",
    "GRAPH_CLIENT_SECRET",
    "MATTERPORT_API_TOKEN",
    "MATTERPORT_API_SECRET",
)


@pytest.fixture(autouse=True)
def _no_ambient_secrets(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Keep the developer's real .env out of every test.

    `Settings` is declared with `SettingsConfigDict(env_file=".env")`, so any
    test that reaches `get_settings()` without `offline_env` reads the real
    keys sitting in the repo root — which is how an "offline" suite starts
    making live calls on one machine and not another.

    Deliberately narrower than `offline_env`: this only blanks credentials and
    forces the mock backends. It does not relocate DATA_DIR or tear down the
    database singleton, because doing that for all 116 tests is a far bigger
    behavioural change than the isolation it buys.
    """
    for name in _AMBIENT_SECRETS:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("DOCUSIGN_BACKEND", "mock")
    monkeypatch.setenv("MLS_BACKEND", "mock")
    monkeypatch.setenv("PUBLIC_RECORDS_LIVE", "false")

    from realtorai.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_db_path(temp_dir: Path) -> Path:
    """Get path for test database."""
    return temp_dir / "test.db"


@pytest_asyncio.fixture
async def database(test_db_path: Path):
    """Create and initialize test database."""
    from realtorai.storage.database import Database

    db = Database(test_db_path)
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def offline_env(temp_dir: Path, monkeypatch) -> Generator[Path, None, None]:
    """Isolated data dir + mock backends + no API key (fully offline).

    Clears the settings cache and integration singletons so each test gets a
    fresh mock DocuSign Rooms / MLS state under a temp DATA_DIR.
    """
    from realtorai.config.settings import get_settings
    from realtorai.integrations.docusign.client import reset_docusign_client
    from realtorai.integrations.spark.mock import reset_mock_mls

    def _close_db_singleton() -> None:
        from realtorai.storage import database as database_module

        if database_module._database is not None:
            asyncio.run(database_module.close_database())

    monkeypatch.setenv("DATA_DIR", str(temp_dir))
    monkeypatch.setenv("DOCUSIGN_BACKEND", "mock")
    monkeypatch.setenv("MLS_BACKEND", "mock")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("PUBLIC_RECORDS_LIVE", "false")
    get_settings.cache_clear()
    reset_docusign_client()
    reset_mock_mls()
    _close_db_singleton()  # a prior test's DB points at its own temp dir

    yield temp_dir

    _close_db_singleton()  # aiosqlite's non-daemon thread would block exit
    get_settings.cache_clear()
    reset_docusign_client()
    reset_mock_mls()


@pytest.fixture
def mock_settings(temp_dir: Path):
    """Create mock settings for testing."""
    from realtorai.config.settings import Settings

    return Settings(
        db_path=temp_dir / "test.db",
        feedback_log_dir=temp_dir / "feedback",
        cache_dir=temp_dir / "cache",
        graph_client_id="test-client-id",
        graph_tenant_id="test-tenant-id",
        model_name="test-model",
        web_port=8422,
        daemon_poll_interval=60,
    )


@pytest.fixture
def sample_email_data() -> dict:
    """Sample email data for testing."""
    return {
        "id": "email-123",
        "subject": "Interested in 123 Main St",
        "sender": {
            "emailAddress": {
                "name": "Sarah Johnson",
                "address": "sarah@example.com",
            }
        },
        "receivedDateTime": "2024-01-15T10:30:00Z",
        "body": {
            "content": "Hi, I saw your listing and I'm interested in scheduling a showing.",
            "contentType": "text",
        },
        "isRead": False,
        "conversationId": "conv-456",
    }


@pytest.fixture
def sample_task_data() -> dict:
    """Sample task data for testing."""
    from datetime import datetime

    return {
        "id": "task-123",
        "task_type": "email_response",
        "status": "pending",
        "title": "Reply to Sarah Johnson",
        "summary": "Sarah is interested in scheduling a showing for 123 Main St",
        "confidence": "high",
        "source_id": "email-123",
        "source_type": "email",
        "proposal_data": {
            "draft_response": {
                "subject": "Re: Interested in 123 Main St",
                "body": "Hi Sarah, I'd be happy to schedule a showing...",
                "to": "sarah@example.com",
            }
        },
        "created_at": datetime.now(UTC),
    }
