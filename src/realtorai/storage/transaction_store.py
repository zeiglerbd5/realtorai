"""Persistence for transactions: canonical record + workflow state + artifacts.

Each transaction gets a directory under `data/transactions/<slug>/`:

    transaction.json    — TransactionEnvelope (record, workflow state, metadata)
    artifacts/          — generated files (master info doc, deed review,
                          tax map / flood artifacts, verification report)

The slug is derived from the property address so a transaction is findable by
eye on disk. `docusign_room_id` remains the join key to the Room once created.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

from realtorai.config.settings import get_settings
from realtorai.schemas.transaction import TransactionRecord

logger = structlog.get_logger()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Artifact(BaseModel):
    """A generated file attached to a transaction."""

    name: str
    path: str
    kind: str = "document"  # document | report | map | listing
    created_at: datetime = Field(default_factory=_now)
    uploaded_to_room: bool = False


class TransactionEnvelope(BaseModel):
    """Everything we persist for one transaction."""

    slug: str
    record: TransactionRecord
    client_id: int | None = None
    client_name: str | None = None
    workflow: dict[str, Any] | None = None  # serialized WorkflowState (owned by workflows.engine)
    workflow_history: list[dict[str, Any]] = Field(default_factory=list)  # prior phases
    artifacts: list[Artifact] = Field(default_factory=list)
    mls_listing_key: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


def slug_for(record: TransactionRecord, fallback: str = "transaction") -> str:
    """Derive a filesystem slug from the property address."""
    parts = [p for p in (record.street_address, record.city) if p]
    base = " ".join(parts) or fallback
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return slug or fallback


def transaction_dir(slug: str) -> Path:
    return get_settings().transactions_dir / slug


def artifacts_dir(slug: str) -> Path:
    path = transaction_dir(slug) / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_transaction(envelope: TransactionEnvelope) -> Path:
    envelope.updated_at = _now()
    path = transaction_dir(envelope.slug)
    path.mkdir(parents=True, exist_ok=True)
    file_path = path / "transaction.json"
    with open(file_path, "w") as f:
        f.write(envelope.model_dump_json(indent=2))
    logger.debug("transaction_saved", slug=envelope.slug)
    return file_path


def load_transaction(slug: str) -> TransactionEnvelope | None:
    file_path = transaction_dir(slug) / "transaction.json"
    if not file_path.exists():
        return None
    try:
        with open(file_path) as f:
            return TransactionEnvelope.model_validate(json.load(f))
    except Exception as e:
        logger.error("transaction_load_error", slug=slug, error=str(e))
        return None


def list_transactions() -> list[TransactionEnvelope]:
    """All transactions, newest first."""
    root = get_settings().transactions_dir
    if not root.exists():
        return []
    envelopes = []
    for child in root.iterdir():
        if child.is_dir():
            envelope = load_transaction(child.name)
            if envelope:
                envelopes.append(envelope)
    envelopes.sort(key=lambda e: e.updated_at, reverse=True)
    return envelopes


def find_by_room_id(room_id: int) -> TransactionEnvelope | None:
    for envelope in list_transactions():
        if envelope.record.docusign_room_id == room_id:
            return envelope
    return None
