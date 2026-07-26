"""Fill the Transaction Worksheet for a stored transaction — on demand.

The TW is filled at the UNDER-CONTRACT phase (it's the agency office staff's
reference sheet, not intake paperwork), so it isn't part of the intake
workflows. Run this when a deal goes under contract; it fills the worksheet
from the transaction's record and files it to the room.

Usage:
    python scripts/fill_tw.py                      # list transactions
    python scripts/fill_tw.py 22-penobscot-street-orono
    python scripts/fill_tw.py <slug> --no-upload   # fill only, don't file to room
"""

import argparse
import asyncio
import sys

from realtorai.config.settings import get_settings
from realtorai.documents.tw_filler import fill_transaction_worksheet
from realtorai.integrations.docusign import rooms
from realtorai.storage.transaction_store import (
    artifacts_dir,
    list_transactions,
    load_transaction,
    save_transaction,
)


async def run(slug: str, upload: bool) -> int:
    envelope = load_transaction(slug)
    if envelope is None:
        print(f"No transaction '{slug}'. Known transactions:", file=sys.stderr)
        for e in list_transactions():
            print(f"  {e.slug}", file=sys.stderr)
        return 1

    template = get_settings().tw_template_path
    if not template.exists():
        print(f"TW template not found at {template} (internal form)", file=sys.stderr)
        return 1

    out_path = artifacts_dir(slug) / "Transaction Worksheet - prefilled.pdf"
    fill_transaction_worksheet(envelope.record, template, out_path)
    print(f"Filled: {out_path}")

    if upload and envelope.record.docusign_room_id:
        doc = await rooms.upload_document_to_room(
            envelope.record.docusign_room_id, out_path.name, out_path.read_bytes()
        )
        print(f"Filed to room {envelope.record.docusign_room_id}: {'ok' if doc else 'FAILED'}")

    from realtorai.storage.transaction_store import Artifact

    envelope.artifacts = [a for a in envelope.artifacts if a.name != "Transaction Worksheet"]
    envelope.artifacts.append(
        Artifact(
            name="Transaction Worksheet",
            path=str(out_path),
            kind="document",
            uploaded_to_room=upload and envelope.record.docusign_room_id is not None,
        )
    )
    save_transaction(envelope)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill the Transaction Worksheet for a deal")
    parser.add_argument("slug", nargs="?", help="Transaction slug (omit to list)")
    parser.add_argument("--no-upload", action="store_true", help="Don't file to the room")
    args = parser.parse_args()

    if not args.slug:
        for envelope in list_transactions():
            side = envelope.record.representation_side or "?"
            print(f"  {envelope.slug}  ({side})")
        return 0
    return asyncio.run(run(args.slug, upload=not args.no_upload))


if __name__ == "__main__":
    sys.exit(main())
