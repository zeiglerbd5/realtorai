"""
RealtorAI Background Daemon

Polls for new emails and processes them through the AI pipeline.
Runs independently from the web UI.
"""

import asyncio
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

# Fix imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from realtorai.config.settings import Settings, get_settings
from realtorai.orchestration.feedback import FeedbackLogger
from realtorai.orchestration.queue import TaskQueue
from realtorai.storage.database import Database
from realtorai.storage.keychain import get_graph_tokens


class RealtorAIDaemon:
    """Background daemon for email polling and processing."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.running = False
        self._shutdown_event = asyncio.Event()

        # Components initialized on start
        self.db: Database | None = None
        self.queue: TaskQueue | None = None
        self.feedback_logger: FeedbackLogger | None = None

    async def initialize(self) -> None:
        """Initialize all components."""
        print("Initializing daemon components...")

        # Database
        self.db = Database(self.settings.db_path)
        await self.db.connect()
        print(f"  Database: {self.settings.db_path}")

        # Task queue
        self.queue = TaskQueue()
        print("  Task queue: Ready")

        # Feedback logger
        self.feedback_logger = FeedbackLogger()
        print("  Feedback logger: Ready")

        print("Initialization complete")

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        print("\nShutting down daemon...")
        self.running = False
        self._shutdown_event.set()

        if self.db:
            await self.db.close()
            print("  Database closed")

        # Remove PID file
        if hasattr(self, '_pid_file') and self._pid_file.exists():
            self._pid_file.unlink()
            print("  PID file removed")

        print("Shutdown complete")

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(self.shutdown())
            )

    async def poll_emails(self) -> None:
        """Poll for new emails and process them."""
        from realtorai.integrations.graph.email import get_emails

        # Check if Graph API is configured
        if not self.settings.graph_client_id:
            print("  Graph API not configured. Skipping email poll.")
            return

        # Check if we have valid tokens
        tokens = get_graph_tokens()
        if not tokens:
            print("  No Graph tokens found. Please authenticate via the web UI.")
            return

        try:
            # Get unread emails
            emails = await get_emails(
                unread_only=True,
                limit=20,
            )

            if not emails:
                print("  No new emails")
                return

            print(f"  Found {len(emails)} new email(s)")

            for email in emails:
                email_id = email.get("id")

                # Skip if already processed
                if await self.db.is_email_processed(email_id):
                    continue

                print(f"  Processing: {email.get('subject', 'No subject')[:50]}")

                try:
                    # Import email agent here to avoid circular imports
                    from realtorai.agents.email_agent import EmailAgent
                    from realtorai.integrations.graph.email import format_email_for_display

                    email_agent = EmailAgent()

                    # Process through email agent
                    proposal = await email_agent.process_email(email)

                    # Add to task queue
                    formatted = format_email_for_display(email)
                    task_id = await self.queue.add_email_task(
                        email_id=email_id,
                        sender_email=formatted["from_email"],
                        sender_name=formatted["from_name"],
                        subject=formatted["subject"],
                        classification=proposal.classification.model_dump(),
                        draft_response=(
                            proposal.draft_response.model_dump()
                            if proposal.draft_response
                            else None
                        ),
                        reasoning_summary=proposal.reasoning.conclusion,
                        confidence=proposal.classification.confidence.value,
                    )

                    print(f"    Created task: {task_id}")

                except Exception as e:
                    print(f"    Error processing email: {e}")
                    import traceback
                    traceback.print_exc()
                    # Don't mark as processed so we retry next time

        except Exception as e:
            print(f"  Error polling emails: {e}")

    async def process_background_tasks(self) -> None:
        """Process any pending background tasks."""
        # Placeholder for future background processing
        # - Calendar reminders
        # - Follow-up checks
        # - Deadline monitoring
        pass

    async def run(self) -> None:
        """Main daemon loop."""
        await self.initialize()
        self._setup_signal_handlers()

        # Write PID file
        self._pid_file = self.settings.data_dir / "daemon.pid"
        self._pid_file.write_text(str(os.getpid()))

        self.running = True
        print(f"\nDaemon started. Polling every {self.settings.daemon_poll_interval}s")
        print("Press Ctrl+C to stop\n")

        while self.running:
            cycle_start = datetime.now(UTC)
            print(f"[{cycle_start.strftime('%H:%M:%S')}] Polling cycle started")

            try:
                await self.poll_emails()
                await self.process_background_tasks()
            except Exception as e:
                print(f"  Error in poll cycle: {e}")

            print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] Cycle complete")

            # Wait for next cycle or shutdown
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.settings.daemon_poll_interval,
                )
            except TimeoutError:
                pass  # Normal timeout, continue loop

        await self.shutdown()


def run_daemon(foreground: bool = False, poll_interval: int | None = None) -> NoReturn:
    """Run the daemon process."""
    settings = get_settings()

    if poll_interval:
        settings.daemon_poll_interval = poll_interval

    daemon = RealtorAIDaemon(settings)

    if not foreground:
        # TODO: Proper daemonization (double-fork, etc.)
        print("Note: Daemonization not yet implemented. Running in foreground mode.")

    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        pass

    sys.exit(0)


def main() -> None:
    """Entry point for realtorai-daemon command."""
    import argparse

    parser = argparse.ArgumentParser(
        description="RealtorAI background daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --foreground              Run in foreground mode
  %(prog)s --poll-interval 30        Poll every 30 seconds
        """,
    )
    parser.add_argument(
        "--foreground", "-f",
        action="store_true",
        help="Run in foreground (recommended for now)",
    )
    parser.add_argument(
        "--poll-interval", "-p",
        type=int,
        default=None,
        help="Email polling interval in seconds",
    )

    args = parser.parse_args()

    run_daemon(foreground=args.foreground, poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()
