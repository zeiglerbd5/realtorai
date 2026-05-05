"""FastAPI web application for RealtorAI dashboard."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from realtorai.config.settings import get_settings

from realtorai.storage.database import get_database
from realtorai.ui.routes import actions, chat, clients, pending, queue

logger = structlog.get_logger()

# Paths
UI_DIR = Path(__file__).parent
TEMPLATES_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler - startup and shutdown."""
    # Startup
    logger.info("web_ui_starting")
    settings = get_settings()
    settings.ensure_directories()

    # Connect to database
    await get_database()

    yield

    # Shutdown
    logger.info("web_ui_stopping")


# Create FastAPI app
app = FastAPI(
    title="RealtorAI",
    description="Local-first AI copilot for real estate professionals",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Include routers
app.include_router(queue.router, prefix="/queue", tags=["queue"])
app.include_router(actions.router, prefix="/actions", tags=["actions"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(clients.router, prefix="/clients", tags=["clients"])
app.include_router(pending.router, prefix="/pending", tags=["pending"])


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Main dashboard page."""
    from realtorai.orchestration.queue import task_queue
    from realtorai.integrations.graph.auth import graph_auth
    from realtorai.integrations.docusign.auth import docusign_auth

    db = await get_database()

    # Get pending tasks
    pending_tasks = await task_queue.get_pending(limit=20)

    # Get active clients (not leads)
    clients = await db.get_clients(status="active", limit=10)

    # Get leads separately
    leads = await db.get_clients(status="lead", limit=10)

    # Get pending items (what system is waiting on)
    waiting_on = await db.get_pending_items(status="waiting")

    # Check integration status
    graph_connected = await graph_auth.is_connected()
    docusign_connected = await docusign_auth.is_connected()

    # Check daemon status (simple check via database last activity)
    daemon_running = await _check_daemon_running()

    settings = get_settings()
    # Get short model name (last part of path)
    model_name = settings.model_name.split("/")[-1]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "pending_tasks": pending_tasks,
            "pending_count": len(pending_tasks),
            "clients": clients,
            "leads": leads,
            "waiting_on": waiting_on,
            "graph_connected": graph_connected,
            "docusign_connected": docusign_connected,
            "daemon_running": daemon_running,
            "model_name": model_name,
        },
    )


async def _check_daemon_running() -> bool:
    """Check if daemon is running by looking for recent activity."""
    import os
    from pathlib import Path

    # Check for PID file
    pid_file = Path(get_settings().data_dir) / "daemon.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            # Check if process exists
            os.kill(pid, 0)
            return True
        except (ValueError, OSError):
            # PID file exists but process doesn't
            pass

    return False


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    from realtorai.integrations.graph.auth import graph_auth

    return {
        "status": "ok",
        "graph_connected": await graph_auth.is_connected(),
    }


@app.get("/setup", response_class=HTMLResponse)
async def setup(request: Request) -> HTMLResponse:
    """Setup wizard page."""
    from realtorai.integrations.graph.auth import graph_auth

    return templates.TemplateResponse(
        "setup.html",
        {
            "request": request,
            "graph_configured": await graph_auth.is_configured(),
            "graph_connected": await graph_auth.is_connected(),
        },
    )


@app.post("/setup/graph")
async def setup_graph() -> dict:
    """Initiate Microsoft Graph OAuth flow."""
    from realtorai.integrations.graph.auth import graph_auth

    success = await graph_auth.connect()
    return {"success": success}


def run_server(host: str = "127.0.0.1", port: int = 8420) -> None:
    """Run the web server."""
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


def main() -> None:
    """Entry point for realtorai-web command."""
    settings = get_settings()
    run_server(host=settings.web_host, port=settings.web_port)


if __name__ == "__main__":
    main()
