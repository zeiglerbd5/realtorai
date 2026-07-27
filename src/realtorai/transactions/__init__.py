"""Transaction coordination - manages deals from contract to close.

Tracks documents, dates, milestones, and contacts for real estate
transactions. Integrates with DocuSign Transaction Rooms (DTR).
"""

from realtorai.transactions.tracker import (
    TRANSACTION_TEMPLATE,
    add_transaction_note,
    create_transaction,
    format_transaction_summary,
    get_transaction,
    get_transaction_progress,
    mark_document_received,
    set_milestone,
    update_transaction,
)

__all__ = [
    "get_transaction",
    "create_transaction",
    "update_transaction",
    "set_milestone",
    "mark_document_received",
    "add_transaction_note",
    "get_transaction_progress",
    "format_transaction_summary",
    "TRANSACTION_TEMPLATE",
]
