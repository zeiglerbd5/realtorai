"""Main entry point for RealtorAI CLI."""


import structlog

# Add config to path

from realtorai.config.settings import get_settings


def setup_logging() -> None:
    """Configure structured logging."""
    settings = get_settings()

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main() -> None:
    """RealtorAI main entry point."""
    import argparse

    from rich.console import Console

    console = Console()

    parser = argparse.ArgumentParser(
        description="RealtorAI — Local-first AI copilot for real estate professionals"
    )
    parser.add_argument(
        "--version", action="version", version=f"RealtorAI {__import__('realtorai').__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Web UI command
    web_parser = subparsers.add_parser("web", help="Start the web UI")
    web_parser.add_argument("--host", default=None, help="Host to bind to")
    web_parser.add_argument("--port", type=int, default=None, help="Port to bind to")

    # Daemon command
    daemon_parser = subparsers.add_parser("daemon", help="Start the background daemon")
    daemon_parser.add_argument("--foreground", action="store_true", help="Run in foreground")

    # Status command
    subparsers.add_parser("status", help="Check system status")

    # Setup command
    subparsers.add_parser("setup", help="Run initial setup wizard")

    args = parser.parse_args()

    setup_logging()

    if args.command == "web":
        from realtorai.ui.app import run_server

        settings = get_settings()
        host = args.host or settings.web_host
        port = args.port or settings.web_port
        console.print(f"[green]Starting RealtorAI web UI at http://{host}:{port}[/green]")
        run_server(host=host, port=port)

    elif args.command == "daemon":
        from realtorai.daemon import run_daemon

        console.print("[green]Starting RealtorAI daemon...[/green]")
        run_daemon(foreground=args.foreground)

    elif args.command == "status":
        console.print("[bold]RealtorAI Status[/bold]")
        # TODO: Check daemon, model, integrations
        console.print("  Model: [yellow]Not loaded[/yellow]")
        console.print("  Daemon: [yellow]Not running[/yellow]")
        console.print("  Graph API: [yellow]Not configured[/yellow]")

    elif args.command == "setup":
        console.print("[bold]RealtorAI Setup Wizard[/bold]")
        # TODO: Interactive setup
        console.print("Setup wizard not yet implemented.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
