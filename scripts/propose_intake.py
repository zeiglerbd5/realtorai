"""Propose an intake workflow from an email — into the approval queue.

This is the bridge between any inbox reader and the workflow system. The
intended production loop (nothing automated end-to-end, by design):

  1. A daily Claude task (Cowork) reads the forwarded-agency Gmail account,
     spots candidate emails (signed-envelope notifications, new-client
     paperwork handoffs), downloads their attachments, and calls this CLI.
  2. This CLI classifies the email (Sonnet; keyword fallback offline) and —
     if it's a new listing/buyer client — files a WORKFLOW_KICKOFF task in
     the approval queue with the attachments saved to data/intake/.
  3. A HUMAN reviews the task in the web UI queue and clicks Approve.
  4. Approval triggers extraction (Sonnet), verification (Opus), and the
     matching workflow — room, forms, MLS draft, public records.

Usage:
    python scripts/propose_intake.py --subject "Completed: ERTS (Combo)" \
        --body-file body.txt --attach signed_erts.pdf disclosure.pdf
    python scripts/propose_intake.py --subject "..." --body "inline text"
"""

import argparse
import asyncio
import sys
from pathlib import Path

from realtorai.workflows.email_trigger import propose_new_client_workflow


async def run(args: argparse.Namespace) -> int:
    body = args.body or (Path(args.body_file).read_text() if args.body_file else "")
    attachments: list[tuple[str, bytes]] = []
    for path_str in args.attach or []:
        path = Path(path_str)
        if not path.exists():
            print(f"attachment not found: {path}", file=sys.stderr)
            return 1
        attachments.append((path.name, path.read_bytes()))

    from realtorai.storage.database import close_database

    try:
        task_id = await propose_new_client_workflow(
            args.subject, body, attachments, source=args.source
        )
    finally:
        await close_database()
    if task_id is None:
        print("Classified as 'other' — no workflow proposed.")
        return 0
    print(f"Proposed: task {task_id}")
    print("Review and approve it in the web UI queue — nothing runs until then.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Propose an intake workflow from an email")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", default=None, help="Email body text inline")
    parser.add_argument("--body-file", default=None, help="Path to a file with the body text")
    parser.add_argument("--attach", nargs="*", help="Attachment file paths")
    parser.add_argument("--source", default="email", help="Provenance label (e.g. gmail)")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
