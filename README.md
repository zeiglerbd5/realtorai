# RealtorAI

Local-first AI copilot for real estate professionals in Maine.

## Overview

RealtorAI is an AI assistant that runs entirely on your Mac, using Apple Silicon's MLX framework for fast, private inference. It helps real estate agents with:

- **Email Triage** - Automatically prioritizes and drafts responses to client emails
- **Calendar Management** - Schedules showings and appointments
- **Task Tracking** - Manages follow-ups and action items
- **Maine Real Estate Knowledge** - Answers questions about local regulations and practices

All processing happens locally. Your data never leaves your machine.

## Requirements

- macOS with Apple Silicon (M1/M2/M3/M4)
- 16GB+ RAM (8B model) or 8GB+ RAM (3B model)
- Python 3.11+
- Microsoft 365 account (for Outlook integration)

## Installation

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/zeiglerbd5/realtorai.git
cd realtorai

# Install with UV (recommended)
uv sync

# Or with pip
pip install -e .
```

### 2. Download the Model

```bash
# Download the 8B model (recommended for 16GB+ systems)
python scripts/setup_model.py

# Or the smaller 3B model for 8-16GB systems
python scripts/setup_model.py --model 3b
```

### 3. Configure Environment

```bash
# Copy the example environment file
cp .env.example .env

# Edit with your Microsoft Graph credentials
# See Setup section below for details
```

### 4. Start the Application

```bash
# Start the web UI
realtorai web

# In a separate terminal, start the background daemon
realtorai daemon --foreground
```

Open http://localhost:8421 in your browser.

## Setup

### Microsoft Graph (Outlook) Integration

1. Go to [Azure Portal](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps)
2. Register a new application
3. Add redirect URI: `http://localhost:8421/callback`
4. Grant API permissions:
   - `Mail.Read`
   - `Mail.Send`
   - `Calendars.ReadWrite`
5. Copy the Client ID to your `.env` file
6. Visit http://localhost:8421/setup to complete OAuth flow

## Usage

### Web UI

The web UI at http://localhost:8421 provides:

- **Dashboard** - Overview of pending actions and system status
- **Queue** - Review and approve AI-proposed actions
- **Chat** - Direct interaction with the AI
- **Setup** - Configure integrations

### Approval Workflow

RealtorAI never takes action without your approval:

1. New email arrives → AI analyzes and drafts response
2. Draft appears in your Queue → You review
3. **Approve** - Send as-is
4. **Edit** - Modify before sending
5. **Reject** - Discard the proposal

Every interaction trains the AI to match your style (stored locally for future fine-tuning).

### CLI Commands

```bash
# Start web server
realtorai web [--port 8421] [--reload]

# Start background daemon
realtorai daemon [--foreground] [--poll-interval 60]

# Check system status
realtorai status

# Run setup wizard
realtorai setup [--model 8b|3b]
```

## Project Structure

```
realtorai/
├── src/realtorai/
│   ├── cli.py / daemon.py / main.py    # Entry points
│   ├── agents/          # AI agent implementations
│   ├── config/          # Configuration management
│   ├── documents/       # Generated document templates (e.g., buyer agency)
│   ├── inference/       # MLX inference + structured extraction
│   ├── integrations/    # External service adapters
│   │   ├── graph/       # Microsoft Graph (Outlook, Calendar)
│   │   ├── spark/       # Spark / FlexMLS API + buyer alerts
│   │   ├── docusign/    # DocuSign Rooms
│   │   ├── matterport/  # Matterport tour ingest
│   │   └── web/         # Web search
│   ├── orchestration/   # Task queue and human-in-loop approval
│   ├── rag/             # ChromaDB knowledge base + retrieval
│   ├── schemas/         # Pydantic data models
│   ├── storage/         # SQLite + macOS Keychain
│   ├── transactions/    # Contract-to-close tracking
│   └── ui/              # FastAPI + Jinja2 + HTMX web app
│       ├── routes/      # API and HTML endpoints
│       ├── static/      # CSS / JavaScript
│       └── templates/   # Jinja2 HTML
├── scripts/             # Setup and utility scripts
├── tests/               # Test suite
└── data/                # Local data (gitignored)
    ├── realtorai.db     # SQLite database
    ├── chroma/          # Vector store
    └── logs/            # Feedback logs for training
```

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=realtorai

# Run specific test file
pytest tests/test_schemas.py
```

### Code Style

```bash
# Format code
ruff format .

# Lint
ruff check .

# Type check
mypy src/realtorai
```

### Development Mode

```bash
# Run web server with auto-reload
realtorai web --reload

# Run daemon in foreground for debugging
realtorai daemon --foreground
```

## Architecture

### Core Loop

```
Email arrives
    ↓
Daemon polls Graph API
    ↓
Email Agent classifies & drafts
    ↓
Task added to Queue
    ↓
Agent reviews in Web UI
    ↓
Approve / Edit / Reject
    ↓
Action executed via integrations
    ↓
Feedback logged for training
```

### Key Components

- **Inference Engine** - MLX wrapper for Llama 3.1 8B with structured output
- **Email Agent** - Specialized agent for email triage and response
- **Task Queue** - SQLite-backed queue for pending approvals
- **Approval Loop** - Human-in-the-loop confirmation system
- **RAG Knowledge Base** - ChromaDB store for ingested domain documents (NAR Code of Ethics, Maine RE laws, etc.) augmented into chat and email drafts
- **MLS Integration** - Spark / FlexMLS API for listings, comps, and market stats with browser-based OAuth
- **Transaction Tracker** - Contract-to-close workflow with DocuSign Rooms and document template generation
- **Web Search** - DuckDuckGo tool for grounding responses in current news
- **Feedback Logger** - Captures decisions for future RL fine-tuning

## Privacy & Security

- **100% Local Processing** - LLM runs on your Mac, no cloud APIs
- **Secure Token Storage** - OAuth tokens stored in macOS Keychain
- **Encrypted Database** - SQLite with application-level encryption
- **No Telemetry** - No data sent anywhere without explicit action

## Roadmap

See [PROGRESS.md](PROGRESS.md) for the detailed development tracker.

### Phase 1: Email Triage MVP — complete
- [x] MLX inference engine with structured output
- [x] Email classification + draft response generation
- [x] Web UI dashboard with approval queue
- [x] Microsoft Graph OAuth + Keychain token storage
- [x] Background daemon for email polling
- [x] Feedback logging for future fine-tuning

### Phase 2: Knowledge & Style — in progress
- [x] ChromaDB RAG knowledge base (NAR ethics, Maine RE laws ingested)
- [x] Streaming chat (CLI + dashboard SSE)
- [x] Web search via DuckDuckGo (no API key)
- [x] Spark / FlexMLS API integration (search, comps, market stats)
- [ ] LoRA fine-tuning for personal communication style
- [ ] iMessage integration

### Phase 3: Transactions & Listings — in progress
- [x] Transaction tracker (contract-to-close workflow)
- [x] DocuSign Rooms integration
- [x] Matterport tour ingest (email + zip download)
- [x] Document template system (e.g., buyer agency agreement)
- [x] Maine agency agreement gating
- [x] Buyer alerts via Spark
- [ ] Buyer-listing matching engine
- [ ] zipForm integration

### Phase 4: Mobile & Polish — future
- [ ] Mobile notifications / companion app
- [ ] Voice transcription
- [ ] Dashboard UI refinements

### Phase 5: Cloud — future
- [ ] AWS-hosted deployment for clients without Apple Silicon

## License

All rights reserved. This source is published for portfolio review and
evaluation only — no use, copying, modification, or redistribution is
permitted without written permission. See [LICENSE](LICENSE).

## Support

For issues and feature requests, please open an issue on GitHub.
