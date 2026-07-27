"""
Tests for storage layer (database operations).
"""


import pytest


@pytest.mark.asyncio
class TestDatabase:
    """Tests for Database class."""

    async def test_initialize_creates_tables(self, database):
        """Test that initialization creates required tables."""
        # Check tables exist by querying them
        cursor = await database._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
        tables = [row[0] for row in rows]

        assert "tasks" in tables
        assert "processed_emails" in tables
        assert "kv_store" in tables

    async def test_create_task(self, database, sample_task_data):
        """Test creating a task."""
        await database.create_task(
            task_id=sample_task_data["id"],
            task_type=sample_task_data["task_type"],
            title=sample_task_data["title"],
            summary=sample_task_data["summary"],
            confidence=sample_task_data["confidence"],
            related_email_id=sample_task_data["source_id"],
            proposal_data=sample_task_data["proposal_data"],
        )

        # Verify task was created
        retrieved = await database.get_task(sample_task_data["id"])
        assert retrieved is not None
        assert retrieved["id"] == sample_task_data["id"]
        assert retrieved["title"] == sample_task_data["title"]
        assert retrieved["status"] == "pending"

    async def test_get_pending_tasks(self, database):
        """Test retrieving pending tasks."""
        # Create multiple tasks with different statuses
        await database.create_task(
            task_id="pending-1",
            task_type="email_response",
            title="Pending task",
            summary="Test",
        )

        await database.create_task(
            task_id="approved-1",
            task_type="email_response",
            title="Will be approved",
            summary="Test",
        )

        # Update one to approved
        await database.update_task_status("approved-1", "approved")

        # Get only pending tasks
        pending = await database.get_pending_tasks()
        pending_ids = [t["id"] for t in pending]

        assert "pending-1" in pending_ids
        assert "approved-1" not in pending_ids

    async def test_update_task_status(self, database):
        """Test updating task status."""
        await database.create_task(
            task_id="update-test",
            task_type="email_response",
            title="Test task",
            summary="Test",
        )

        # Update status
        await database.update_task_status("update-test", "approved")

        # Verify update
        updated = await database.get_task("update-test")
        assert updated["status"] == "approved"

    async def test_mark_email_processed(self, database):
        """Test marking an email as processed."""
        email_id = "email-test-123"

        # Should not be processed initially
        is_processed = await database.is_email_processed(email_id)
        assert is_processed is False

        # Create a task first
        await database.create_task(
            task_id="task-for-email",
            task_type="email_response",
            title="Test",
            summary="Test",
        )

        # Mark as processed
        await database.mark_email_processed(
            email_id=email_id,
            thread_id="thread-123",
            task_id="task-for-email",
        )

        # Should now be processed
        is_processed = await database.is_email_processed(email_id)
        assert is_processed is True

    async def test_kv_store_operations(self, database):
        """Test key-value store operations."""
        # Set value
        await database.set_kv("test_key", "test_value")

        # Get value
        value = await database.get_kv("test_key")
        assert value == "test_value"

        # Get non-existent key
        missing = await database.get_kv("nonexistent")
        assert missing is None

        # Update value
        await database.set_kv("test_key", "updated_value")
        value = await database.get_kv("test_key")
        assert value == "updated_value"

    async def test_get_task_nonexistent(self, database):
        """Test getting a task that doesn't exist."""
        task = await database.get_task("nonexistent-task")
        assert task is None

    async def test_task_with_timestamps(self, database):
        """Test that tasks have proper timestamps."""
        await database.create_task(
            task_id="timestamp-test",
            task_type="follow_up",
            title="Timestamp test",
            summary="Test",
        )

        retrieved = await database.get_task("timestamp-test")
        assert retrieved["created_at"] is not None
