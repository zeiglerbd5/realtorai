"""
RealtorAI CLI entry points.
"""

import argparse
import sys


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="realtorai",
        description="RealtorAI - Local-first AI copilot for real estate professionals",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Web server command
    web_parser = subparsers.add_parser("web", help="Start the web UI server")
    web_parser.add_argument(
        "--port",
        type=int,
        default=8421,
        help="Port to run the web server on (default: 8421)",
    )
    web_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    web_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    # Daemon command
    daemon_parser = subparsers.add_parser("daemon", help="Start the background daemon")
    daemon_parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run in foreground (don't daemonize)",
    )
    daemon_parser.add_argument(
        "--poll-interval",
        type=int,
        default=60,
        help="Email polling interval in seconds (default: 60)",
    )

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Run setup wizard")
    setup_parser.add_argument(
        "--model",
        choices=["3b", "8b"],
        default="8b",
        help="Model size to download (default: 8b)",
    )

    # Status command
    subparsers.add_parser("status", help="Show system status")

    # Ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Add documents to knowledge base")
    ingest_parser.add_argument(
        "source",
        nargs="+",
        help="File path(s) or URL(s) to ingest",
    )

    # RAG command
    rag_parser = subparsers.add_parser("rag", help="RAG knowledge base commands")
    rag_subparsers = rag_parser.add_subparsers(dest="rag_command", help="RAG commands")

    rag_subparsers.add_parser("status", help="Show knowledge base status")

    rag_query_parser = rag_subparsers.add_parser("query", help="Test RAG retrieval")
    rag_query_parser.add_argument("query_text", help="Query to search for")
    rag_query_parser.add_argument("-n", "--num-results", type=int, default=5, help="Number of results")

    rag_subparsers.add_parser("sources", help="List all ingested sources")

    args = parser.parse_args()

    if args.command == "web":
        run_web(args)
    elif args.command == "daemon":
        run_daemon(args)
    elif args.command == "setup":
        run_setup(args)
    elif args.command == "status":
        run_status(args)
    elif args.command == "ingest":
        run_ingest(args)
    elif args.command == "rag":
        run_rag(args)
    else:
        parser.print_help()


def run_web(args):
    """Start the web server."""
    import uvicorn

    print(f"Starting RealtorAI web UI on http://{args.host}:{args.port}")

    uvicorn.run(
        "realtorai.ui.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def run_daemon(args):
    """Start the background daemon."""
    import asyncio
    from realtorai.daemon import RealtorAIDaemon
    from realtorai.config.settings import get_settings

    settings = get_settings()

    if args.poll_interval:
        settings.daemon_poll_interval = args.poll_interval

    daemon = RealtorAIDaemon(settings)

    if args.foreground:
        print("Starting RealtorAI daemon in foreground mode...")
        print(f"Polling interval: {settings.daemon_poll_interval}s")
        print("Press Ctrl+C to stop")
        asyncio.run(daemon.run())
    else:
        print("Daemonizing is not yet implemented. Use --foreground for now.")
        sys.exit(1)


def run_setup(args):
    """Run the setup wizard."""
    import subprocess
    import sys
    from pathlib import Path

    script_path = Path(__file__).parent.parent.parent / "scripts" / "setup_model.py"

    if script_path.exists():
        subprocess.run([sys.executable, str(script_path), "--model", args.model])
    else:
        print("Setup script not found. Run from project root:")
        print("  python scripts/setup_model.py")


def run_status(args):
    """Show system status."""
    from realtorai.config.settings import get_settings
    from realtorai.storage.keychain import get_graph_tokens

    settings = get_settings()

    print("\nRealtorAI Status")
    print("=" * 40)

    # Check database
    db_exists = settings.db_path.exists()
    print(f"Database: {'OK' if db_exists else 'Not initialized'}")
    print(f"  Path: {settings.db_path}")

    # Check Graph connection
    tokens = get_graph_tokens()
    graph_status = "Connected" if tokens else "Not connected"
    print(f"Outlook: {graph_status}")

    # Check model
    print(f"Model: {settings.model_name}")

    # Check daemon (via PID file or similar - placeholder)
    print("Daemon: Unknown (check manually)")

    print()


def run_ingest(args):
    """Ingest documents into the knowledge base."""
    from realtorai.rag.ingestion import ingest

    print("Ingesting documents into knowledge base...")
    print()

    total_chunks = 0
    for source in args.source:
        try:
            print(f"  Processing: {source}")
            chunks = ingest(source)
            print(f"    Added {chunks} chunks")
            total_chunks += chunks
        except Exception as e:
            print(f"    Error: {e}")

    print()
    print(f"Total: {total_chunks} chunks added to knowledge base")


def run_rag(args):
    """Run RAG-related commands."""
    from realtorai.rag.store import get_vector_store

    if args.rag_command == "status":
        store = get_vector_store()
        count = store.count()
        sources = store.list_sources()

        print("\nKnowledge Base Status")
        print("=" * 40)
        print(f"Total chunks: {count}")
        print(f"Sources: {len(sources)}")
        if sources:
            print("\nIngested sources:")
            for source in sources:
                print(f"  - {source}")
        print()

    elif args.rag_command == "query":
        from realtorai.rag.retrieval import get_retriever

        retriever = get_retriever()
        results = retriever.retrieve(args.query_text, n_results=args.num_results)

        print(f"\nQuery: {args.query_text}")
        print("=" * 40)

        if not results:
            print("No results found.")
        else:
            for i, result in enumerate(results, 1):
                source = result.get("metadata", {}).get("source", "unknown")
                distance = result.get("distance", 0)
                text = result["text"][:200] + "..." if len(result["text"]) > 200 else result["text"]

                print(f"\n[{i}] ({source}) - distance: {distance:.3f}")
                print(f"    {text}")
        print()

    elif args.rag_command == "sources":
        store = get_vector_store()
        sources = store.list_sources()

        print("\nIngested Sources")
        print("=" * 40)
        if not sources:
            print("No sources ingested yet.")
        else:
            for source in sources:
                print(f"  - {source}")
        print()

    else:
        print("Use: realtorai rag status|query|sources")


def web_main():
    """Direct entry point for realtorai-web."""
    sys.argv = ["realtorai", "web"] + sys.argv[1:]
    main()


def daemon_main():
    """Direct entry point for realtorai-daemon."""
    sys.argv = ["realtorai", "daemon"] + sys.argv[1:]
    main()


if __name__ == "__main__":
    main()
