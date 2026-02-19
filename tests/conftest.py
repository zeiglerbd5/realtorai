"""
Pytest configuration and fixtures for RealtorAI tests.
"""

import asyncio
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


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
    from datetime import datetime, timezone

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
        "created_at": datetime.now(timezone.utc),
    }
