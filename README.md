# RealtorAI

Local-first AI copilot for real estate professionals in Maine.

## Overview

RealtorAI is an AI assistant that runs entirely on your Mac, using Apple Silicon's MLX framework for fast, private inference. It helps real estate agents with:

- **Email Triage** - Automatically prioritizes and drafts responses to client emails
- **Transaction Workflow Automation** - New-client paperwork → DocuSign Transaction Room,
  auto-filled Maine forms, draft MLS listing, deed review, and public-records pulls
- **Calendar Management** - Schedules showings and appointments
- **Task Tracking** - Manages follow-ups and action items
- **Maine Real Estate Knowledge** - Answers questions about local regulations and practices

Chat and email triage run entirely on-device via MLX. The transaction
workflows optionally use the Claude API with automatic model selection —
and degrade gracefully to a fully offline demo without an API key.

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

## Transaction Workflow Automation (DTR + MLS)

The centerpiece workflow: a realtor signs a new client and emails the bot the
paperwork; the bot runs the whole intake.

```
"Here's the new client's paperwork" (email + attachments)
    ↓
Classify intake (listing vs. buyer)          Claude Sonnet
    ↓
Extract Master Information Document          Claude Sonnet → TransactionRecord
    ↓
Verify extraction against source docs        Claude Opus (second-model audit)
    ↓
Create DocuSign Transaction Room (DTR)       field data auto-synced
    ├─ Add "New Listing" task list           from the Actions menu templates
    ├─ Attach Maine forms                    auto-filled from room field data
    │    Exclusive Right to Sell · Brokerage Relationship (MREC #3)
    ├─ File signed paperwork into the room
    └─ Start property disclosures            waits on client, doesn't block
    ↓
Create draft MLS listing (Maine Listings)    agent reviews + publishes in Flexmls
    ↓
Pull tax map (parcel pin) · tax card · FEMA flood map
    │    flood determination is LIVE: Census geocoder + FEMA NFHL
    │    → zone, SFHA flag, FIRM panel + pinned map composite (~3s)
    ↓
Deed review — restrictions & rights of way   Claude Opus
    ↓
Master doc updated with findings             internal only, never filed to DTR
```

Buyer clients get the same intake with a "Buyer Agreement" task list and an
auto-filled Exclusive Buyer Representation Agreement — no MLS activity.

### Try it

```bash
python scripts/demo_listing_workflow.py --fresh   # 22 Penobscot St reference listing
python scripts/demo_buyer_workflow.py             # buyer-side intake
```

Then open the **Transactions** tab in the web UI to browse the room contents,
form auto-fill coverage, workflow timeline, and MLS draft.

### Mock backends (until API approval lands)

Rooms API access requires broker-account approval and Maine Listings
(Flexmls/Spark) requires MLS approval — neither of which a TC can self-serve.
The integrations are therefore built against the real API surfaces
(`docusign/rooms.py` follows the official Rooms v2 spec; MLS submission the
Spark `POST /listings` shape) with local simulators behind the same client
interface:

| Setting | `mock` (default) | `live` |
|---|---|---|
| `DOCUSIGN_BACKEND` | JSON-backed Rooms simulator seeded with Maine forms + agency team task lists | `demo.rooms.docusign.com` / production |
| `MLS_BACKEND` | Local draft-listing store | Spark API |

Flipping the env var is the entire migration — every workflow, test, and UI
page runs identically on both.

**Public records need no approval at all** — controlled by
`PUBLIC_RECORDS_LIVE`, falling back to manual pull sheets on any failure:

- **Flood** (live): Census geocoder → FEMA National Flood Hazard Layer →
  USGS topo basemap. Flood zone, SFHA flag, FIRM panel, and a pinned
  flood-map composite in ~3 seconds. Also available standalone:
  `python scripts/flood_lookup.py "22 Penobscot St, Orono, ME"`.
- **Tax map** (live): Maine GeoLibrary statewide parcel layer. Finds the
  parcel by address (buffered point query as fallback), renders parcel
  boundaries with lot labels, subject lot highlighted and pinned — and
  cross-checks the state layer's Map/Block/Lot against the record's tax-card
  map/lot, flagging mismatches for reconciliation.
- **Tax card** (live): Vision Government Solutions (VGSI), the vendor platform
  most Maine towns publish assessments through. Uses the site's JSON search
  service + server-rendered parcel page — two HTTP requests, no browser.
  Every card field is cross-checked against the record (assessed value,
  map/lot, deed book/page, year built) with ⚠️ flags on mismatches. First
  adapter in a vendor registry; non-VGSI towns fall back to the pull sheet.
- **Recorded deeds** (live, Penobscot County): the Browntech ALIS registry
  system turns out to be fully driveable with plain GETs — book/page search
  → index record (grantor/grantee/type/town, cross-checked against the
  record) → free-view PDF of the actual recorded deed. The Opus deed-review
  step then reads the scan directly (no OCR needed) and flags restrictions,
  rights of way, and chain-of-title issues. Standalone:
  `python scripts/deed_lookup.py penobscot 16601 156 --review`. Other
  Browntech counties are a base-URL away; Hancock (AcclaimWeb) and Waldo
  need their own adapters.

### Paperwork filling: capture once, verify once, fill everywhere

The LLM never transcribes values into forms. Sonnet extracts the paperwork
into the canonical `TransactionRecord` once; Opus verifies it once; after
that every destination is a deterministic Python mapping — DocuSign room
field data (forms auto-fill in Rooms), the Spark/MLS payload, the master
info document, and the **Transaction Worksheet**, a genuine fillable PDF
filled field-by-field with pypdf (`documents/tw_filler.py`), Room ID join
key included. Deterministic fill means a price or deadline can never be
hallucinated in transit, and re-syncs are free.

### Automatic model selection

| Task | Tier | Default model |
|---|---|---|
| Intake classification, extraction, form fill, remarks drafting | Standard | `claude-sonnet-5` |
| Extraction verification, deed review | Review | `claude-opus-4-8` |

Configured via `CLAUDE_MODEL_STANDARD` / `CLAUDE_MODEL_REVIEW`. Without an
`ANTHROPIC_API_KEY`, LLM steps skip with a note and everything else runs.

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
- **Workflow Engine** - Resumable step-based automation (rooms, forms, MLS drafts) with waiting-on-client states
- **Claude Engine** - Cloud inference for transaction workflows with task-based model routing (Sonnet for structured work, Opus for verification/deed review)
- **Web Search** - DuckDuckGo tool for grounding responses in current news
- **Feedback Logger** - Captures decisions for future RL fine-tuning

## Privacy & Security

- **Local-first Processing** - Chat and email triage run on-device; only the
  transaction workflows call the Claude API (opt-in via `ANTHROPIC_API_KEY`)
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
- [x] Listing + buyer intake workflows (paperwork → room + forms + MLS draft)
- [x] Mock DTR / MLS backends behind the live client interfaces
- [x] Claude API engine with automatic model selection (Sonnet/Opus)
- [x] Deed review + public-records pull sheets (tax map, tax card, flood map)
- [ ] Live Rooms / Spark cutover once broker + MLS API approval lands
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
