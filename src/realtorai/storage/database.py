"""SQLite database for task queue and persistent storage."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import AsyncIterator

import aiosqlite
import structlog


from realtorai.config.settings import get_settings

logger = structlog.get_logger()

# SQL schema for task queue
SCHEMA = """
-- Task queue table
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    proposal_data TEXT NOT NULL DEFAULT '{}',
    reasoning_summary TEXT,
    confidence TEXT,
    related_email_id TEXT,
    related_contact TEXT,
    related_transaction TEXT,
    approval_action TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);

-- Email tracking (avoid reprocessing)
CREATE TABLE IF NOT EXISTS processed_emails (
    email_id TEXT PRIMARY KEY,
    thread_id TEXT,
    task_id TEXT,
    processed_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- Simple key-value store for daemon state
CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Clients table (local quick-reference, linked to DocuSign Room)
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    transaction_type TEXT,  -- buy, sell, both
    property_address TEXT,
    price REAL,
    status TEXT NOT NULL DEFAULT 'lead',  -- lead, active, under_contract, closed, archived
    room_id INTEGER,  -- DocuSign Room ID (created when they become active)
    file_path TEXT,  -- Path to markdown profile file
    key_dates TEXT DEFAULT '{}',  -- JSON: closing_date, inspection_date, etc.
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status);
CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name);

-- Client notes (agent + LLM can both read/write)
CREATE TABLE IF NOT EXISTS client_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'agent',  -- agent, llm, email
    created_at TEXT NOT NULL,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_client_notes_client ON client_notes(client_id);

-- Pending items (what system is waiting on)
CREATE TABLE IF NOT EXISTS pending_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    item_type TEXT NOT NULL,  -- document, signature, approval, info
    description TEXT NOT NULL,
    waiting_on TEXT NOT NULL,  -- who: agent, client, lender, other_agent, title, etc.
    status TEXT NOT NULL DEFAULT 'waiting',  -- waiting, received, approved, rejected
    due_date TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pending_items_status ON pending_items(status);
CREATE INDEX IF NOT EXISTS idx_pending_items_client ON pending_items(client_id);
"""


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Connect to database and ensure schema exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row

        # Enable foreign keys
        await self._connection.execute("PRAGMA foreign_keys = ON")

        # Create schema
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()

        logger.info("database_connected", path=str(self.db_path))

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("database_closed")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Context manager for database transactions."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        try:
            yield self._connection
            await self._connection.commit()
        except Exception:
            await self._connection.rollback()
            raise

    # -------------------------------------------------------------------------
    # Task Queue Operations
    # -------------------------------------------------------------------------

    async def create_task(
        self,
        task_id: str,
        task_type: str,
        title: str,
        summary: str,
        details: dict | None = None,
        proposal_data: dict | None = None,
        reasoning_summary: str | None = None,
        confidence: str | None = None,
        related_email_id: str | None = None,
        related_contact: str | None = None,
        related_transaction: str | None = None,
    ) -> None:
        """Create a new task in the queue."""
        async with self.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO tasks (
                    id, task_type, title, summary, details, proposal_data,
                    reasoning_summary, confidence, related_email_id,
                    related_contact, related_transaction, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    task_type,
                    title,
                    summary,
                    json.dumps(details or {}),
                    json.dumps(proposal_data or {}),
                    reasoning_summary,
                    confidence,
                    related_email_id,
                    related_contact,
                    related_transaction,
                    datetime.now(UTC).replace(tzinfo=None).isoformat(),
                ),
            )
        logger.info("task_created", task_id=task_id, task_type=task_type)

    async def get_pending_tasks(self, limit: int = 50) -> list[dict]:
        """Get pending tasks, ordered by creation time."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'pending'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def get_task(self, task_id: str) -> dict | None:
        """Get a specific task by ID."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_task(row) if row else None

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        approval_action: dict | None = None,
    ) -> None:
        """Update task status after approval/rejection."""
        async with self.transaction() as conn:
            await conn.execute(
                """
                UPDATE tasks
                SET status = ?, approval_action = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(approval_action) if approval_action else None,
                    datetime.now(UTC).replace(tzinfo=None).isoformat(),
                    task_id,
                ),
            )
        logger.info("task_updated", task_id=task_id, status=status)

    async def update_task_data(
        self,
        task_id: str,
        proposal_data: dict,
        details: dict | None = None,
    ) -> None:
        """Persist updated proposal_data (and optionally details) for a task.

        Used by the conversational approval loop to grow a task's thread and
        attach operator-supplied amendments before execution.
        """
        async with self.transaction() as conn:
            if details is None:
                await conn.execute(
                    "UPDATE tasks SET proposal_data = ?, updated_at = ? WHERE id = ?",
                    (
                        json.dumps(proposal_data),
                        datetime.now(UTC).replace(tzinfo=None).isoformat(),
                        task_id,
                    ),
                )
            else:
                await conn.execute(
                    "UPDATE tasks SET proposal_data = ?, details = ?, updated_at = ? WHERE id = ?",
                    (
                        json.dumps(proposal_data),
                        json.dumps(details),
                        datetime.now(UTC).replace(tzinfo=None).isoformat(),
                        task_id,
                    ),
                )
        logger.info("task_data_updated", task_id=task_id)

    def _row_to_task(self, row: aiosqlite.Row) -> dict:
        """Convert database row to task dict."""
        return {
            "id": row["id"],
            "task_type": row["task_type"],
            "status": row["status"],
            "title": row["title"],
            "summary": row["summary"],
            "details": json.loads(row["details"]),
            "proposal_data": json.loads(row["proposal_data"]),
            "reasoning_summary": row["reasoning_summary"],
            "confidence": row["confidence"],
            "related_email_id": row["related_email_id"],
            "related_contact": row["related_contact"],
            "related_transaction": row["related_transaction"],
            "approval_action": json.loads(row["approval_action"])
            if row["approval_action"]
            else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # -------------------------------------------------------------------------
    # Email Tracking
    # -------------------------------------------------------------------------

    async def is_email_processed(self, email_id: str) -> bool:
        """Check if an email has already been processed."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            "SELECT 1 FROM processed_emails WHERE email_id = ?", (email_id,)
        )
        return await cursor.fetchone() is not None

    async def mark_email_processed(
        self, email_id: str, thread_id: str | None, task_id: str
    ) -> None:
        """Mark an email as processed."""
        async with self.transaction() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO processed_emails (email_id, thread_id, task_id, processed_at)
                VALUES (?, ?, ?, ?)
                """,
                (email_id, thread_id, task_id, datetime.now(UTC).replace(tzinfo=None).isoformat()),
            )

    # -------------------------------------------------------------------------
    # Key-Value Store
    # -------------------------------------------------------------------------

    async def get_kv(self, key: str) -> str | None:
        """Get a value from the key-value store."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            "SELECT value FROM kv_store WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_kv(self, key: str, value: str) -> None:
        """Set a value in the key-value store."""
        async with self.transaction() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO kv_store (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, datetime.now(UTC).replace(tzinfo=None).isoformat()),
            )

    # -------------------------------------------------------------------------
    # Client Operations
    # -------------------------------------------------------------------------

    async def create_client(
        self,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        transaction_type: str | None = None,
        property_address: str | None = None,
        price: float | None = None,
        status: str = "lead",
        room_id: int | None = None,
    ) -> int:
        """Create a new client. Returns the client ID.

        Also creates a markdown profile file for the client.
        """
        from realtorai.storage.client_files import create_client_file

        async with self.transaction() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO clients (
                    name, email, phone, transaction_type, property_address,
                    price, status, room_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    email,
                    phone,
                    transaction_type,
                    property_address,
                    price,
                    status,
                    room_id,
                    datetime.now(UTC).replace(tzinfo=None).isoformat(),
                ),
            )
            client_id = cursor.lastrowid

        # Create markdown profile file
        file_path = create_client_file(
            client_id=client_id,
            name=name,
            email=email,
            phone=phone,
            transaction_type=transaction_type,
            property_address=property_address,
            price=price,
            status=status,
        )

        # Update record with file path
        async with self.transaction() as conn:
            await conn.execute(
                "UPDATE clients SET file_path = ? WHERE id = ?",
                (str(file_path), client_id),
            )

        logger.info("client_created", client_id=client_id, name=name, file_path=str(file_path))
        return client_id

    async def get_client(self, client_id: int) -> dict | None:
        """Get a client by ID."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_client(row) if row else None

    async def get_clients(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get clients, optionally filtered by status."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        if status:
            cursor = await self._connection.execute(
                """
                SELECT * FROM clients
                WHERE status = ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (status, limit),
            )
        else:
            cursor = await self._connection.execute(
                """
                SELECT * FROM clients
                WHERE status != 'archived'
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_client(row) for row in rows]

    async def update_client(self, client_id: int, **updates) -> None:
        """Update client fields."""
        if not updates:
            return

        # Build SET clause dynamically
        set_parts = []
        values = []
        for key, value in updates.items():
            if key == "key_dates" and isinstance(value, dict):
                value = json.dumps(value)
            set_parts.append(f"{key} = ?")
            values.append(value)

        set_parts.append("updated_at = ?")
        values.append(datetime.now(UTC).replace(tzinfo=None).isoformat())
        values.append(client_id)

        async with self.transaction() as conn:
            await conn.execute(
                f"UPDATE clients SET {', '.join(set_parts)} WHERE id = ?",
                values,
            )
        logger.info("client_updated", client_id=client_id, fields=list(updates.keys()))

    async def search_clients(self, query: str, limit: int = 20) -> list[dict]:
        """Search clients by name, email, or property address."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        search_term = f"%{query}%"
        cursor = await self._connection.execute(
            """
            SELECT * FROM clients
            WHERE name LIKE ? OR email LIKE ? OR property_address LIKE ?
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (search_term, search_term, search_term, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_client(row) for row in rows]

    async def find_client_by_email(self, email: str) -> dict | None:
        """Find a client by exact email match.

        Used to link incoming emails to existing clients.
        Returns the first matching client or None.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            """
            SELECT * FROM clients
            WHERE LOWER(email) = LOWER(?)
            LIMIT 1
            """,
            (email,),
        )
        row = await cursor.fetchone()
        return self._row_to_client(row) if row else None

    async def get_client(self, client_id: int) -> dict | None:
        """Get a client by ID."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            "SELECT * FROM clients WHERE id = ?",
            (client_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_client(row) if row else None

    def _row_to_client(self, row: aiosqlite.Row) -> dict:
        """Convert database row to client dict."""
        return {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "phone": row["phone"],
            "transaction_type": row["transaction_type"],
            "property_address": row["property_address"],
            "price": row["price"],
            "status": row["status"],
            "room_id": row["room_id"],
            "file_path": row["file_path"],
            "key_dates": json.loads(row["key_dates"]) if row["key_dates"] else {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # -------------------------------------------------------------------------
    # Client Notes
    # -------------------------------------------------------------------------

    async def add_client_note(
        self,
        client_id: int,
        content: str,
        source: str = "agent",
    ) -> int:
        """Add a note to a client. Returns note ID.

        Also appends the note to the client's markdown file.
        """
        from realtorai.storage.client_files import append_note

        async with self.transaction() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO client_notes (client_id, content, source, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (client_id, content, source, datetime.now(UTC).replace(tzinfo=None).isoformat()),
            )
            note_id = cursor.lastrowid

        # Also append to markdown file
        client = await self.get_client(client_id)
        if client:
            append_note(client_id, client["name"], content, source)

        logger.info("client_note_added", client_id=client_id, source=source)
        return note_id

    async def get_client_notes(self, client_id: int, limit: int = 50) -> list[dict]:
        """Get notes for a client, most recent first."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            """
            SELECT * FROM client_notes
            WHERE client_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (client_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "client_id": row["client_id"],
                "content": row["content"],
                "source": row["source"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # -------------------------------------------------------------------------
    # Pending Items (Waiting On)
    # -------------------------------------------------------------------------

    async def create_pending_item(
        self,
        client_id: int,
        item_type: str,
        description: str,
        waiting_on: str,
        due_date: str | None = None,
    ) -> int:
        """Create a pending item. Returns item ID."""
        async with self.transaction() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO pending_items (
                    client_id, item_type, description, waiting_on, due_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    item_type,
                    description,
                    waiting_on,
                    due_date,
                    datetime.now(UTC).replace(tzinfo=None).isoformat(),
                ),
            )
            item_id = cursor.lastrowid
        logger.info("pending_item_created", client_id=client_id, item_type=item_type)
        return item_id

    async def get_pending_items(
        self,
        client_id: int | None = None,
        status: str = "waiting",
    ) -> list[dict]:
        """Get pending items, optionally filtered by client."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        if client_id:
            cursor = await self._connection.execute(
                """
                SELECT p.*, c.name as client_name, c.property_address
                FROM pending_items p
                JOIN clients c ON p.client_id = c.id
                WHERE p.client_id = ? AND p.status = ?
                ORDER BY p.due_date ASC, p.created_at ASC
                """,
                (client_id, status),
            )
        else:
            cursor = await self._connection.execute(
                """
                SELECT p.*, c.name as client_name, c.property_address
                FROM pending_items p
                JOIN clients c ON p.client_id = c.id
                WHERE p.status = ?
                ORDER BY p.due_date ASC, p.created_at ASC
                """,
                (status,),
            )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "client_id": row["client_id"],
                "client_name": row["client_name"],
                "property_address": row["property_address"],
                "item_type": row["item_type"],
                "description": row["description"],
                "waiting_on": row["waiting_on"],
                "status": row["status"],
                "due_date": row["due_date"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def resolve_pending_item(
        self,
        item_id: int,
        status: str = "received",
    ) -> None:
        """Mark a pending item as resolved."""
        async with self.transaction() as conn:
            await conn.execute(
                """
                UPDATE pending_items
                SET status = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status, datetime.now(UTC).replace(tzinfo=None).isoformat(), item_id),
            )
        logger.info("pending_item_resolved", item_id=item_id, status=status)

    # -------------------------------------------------------------------------
    # Leads (Prospective Clients)
    # -------------------------------------------------------------------------

    async def create_lead(
        self,
        name: str,
        email: str,
        phone: str | None = None,
        transaction_type: str = "buy",
        source: str | None = None,
    ) -> int:
        """Create a new lead. Returns lead ID.

        Leads are stored in the clients table with status='lead'.
        When they sign the buyer agency agreement, they become active clients.
        """
        async with self.transaction() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO clients (
                    name, email, phone, transaction_type, status, created_at
                ) VALUES (?, ?, ?, ?, 'lead', ?)
                """,
                (
                    name,
                    email,
                    phone,
                    transaction_type,
                    datetime.now(UTC).replace(tzinfo=None).isoformat(),
                ),
            )
            lead_id = cursor.lastrowid

        logger.info(
            "lead_created",
            lead_id=lead_id,
            name=name,
            email=email,
            transaction_type=transaction_type,
        )
        return lead_id

    async def find_lead_by_email(self, email: str) -> dict | None:
        """Find a lead by email address."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            """
            SELECT * FROM clients
            WHERE email = ? AND status = 'lead'
            LIMIT 1
            """,
            (email,),
        )
        row = await cursor.fetchone()

        if not row:
            return None

        return {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "phone": row["phone"],
            "transaction_type": row["transaction_type"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    async def convert_lead_to_client(
        self,
        lead_id: int,
        property_address: str | None = None,
    ) -> None:
        """Convert a lead to an active client.

        Called when they sign the buyer agency agreement.
        """
        async with self.transaction() as conn:
            await conn.execute(
                """
                UPDATE clients
                SET status = 'active',
                    property_address = COALESCE(?, property_address),
                    updated_at = ?
                WHERE id = ? AND status = 'lead'
                """,
                (property_address, datetime.now(UTC).replace(tzinfo=None).isoformat(), lead_id),
            )
        logger.info("lead_converted_to_client", lead_id=lead_id)

    async def add_standard_lead_pending_items(self, lead_id: int, transaction_type: str = "buy") -> None:
        """Add standard pending items for a new lead.

        For buyers: Buyer Agency Agreement
        For sellers: Listing Agreement
        """
        if transaction_type == "buy":
            await self.create_pending_item(
                client_id=lead_id,
                item_type="document",
                description="Buyer Agency Agreement",
                waiting_on="client",
            )
        elif transaction_type == "sell":
            await self.create_pending_item(
                client_id=lead_id,
                item_type="document",
                description="Listing Agreement",
                waiting_on="client",
            )
        # Could add more standard items here

    async def add_standard_client_pending_items(self, client_id: int, transaction_type: str = "buy") -> None:
        """Add standard pending items for a new active client (post-agreement).

        These are the items needed to proceed with the transaction.
        """
        if transaction_type == "buy":
            items = [
                ("document", "Pre-approval letter", "lender"),
                ("document", "Proof of funds", "client"),
                ("info", "Financing details", "client"),
            ]
            for item_type, description, waiting_on in items:
                await self.create_pending_item(
                    client_id=client_id,
                    item_type=item_type,
                    description=description,
                    waiting_on=waiting_on,
                )


# Global database instance
_database: Database | None = None


async def get_database() -> Database:
    """Get the database instance, connecting if necessary."""
    global _database
    if _database is None:
        settings = get_settings()
        _database = Database(settings.db_path)
        await _database.connect()
    return _database


async def close_database() -> None:
    """Close and drop the singleton connection.

    Call before process exit in CLIs/tests — aiosqlite's worker thread is
    non-daemon, so an unclosed connection keeps the interpreter alive.
    """
    global _database
    if _database is not None:
        try:
            await _database.close()
        finally:
            _database = None
