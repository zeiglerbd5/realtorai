# RealtorAI Development Progress

## Current Status

**Active — embedded with a working listing team.** I now work as the
transaction coordinator for a Maine listing team, and the project is built
against that team's real workflow: its checklists drive the mock Rooms task
lists, its forwarded inbox validated the intake classifier (see
`scripts/eval_intake_classifier.py`), and its day-to-day TC workload defines
the feature set. Live DocuSign Rooms / MLS cutover remains blocked on
broker- and MLS-side API approval — the integrations run on simulators
built to the live API shapes, so the cutover is two env vars.

Recent: conversational approval queue (scoping copilot + structural
go/no-go gate), verification that blocks downstream side effects, 49-field
MLS publish-readiness as the single validation source, atomic approval
claims, CI (lint + offline suite).

---

## Phase 1: Email Triage MVP — complete

- [x] MLX inference engine with structured output
- [x] Email classification agent
- [x] Email draft response generation
- [x] Web UI dashboard (FastAPI + Jinja2 + HTMX)
- [x] Approval queue interface
- [x] SQLite database for task tracking
- [x] Microsoft Graph OAuth 2.0 authentication
- [x] macOS Keychain token storage
- [x] Background daemon for email polling
- [x] Feedback logging system for RL training data

## Phase 2: Knowledge & Style — mostly complete

### RAG knowledge base — complete
- [x] ChromaDB vector store (`src/realtorai/rag/store.py`)
- [x] Document ingestion: PDF, TXT, MD, RTF, URLs (`src/realtorai/rag/ingestion.py`)
- [x] Retrieval and prompt augmentation (`src/realtorai/rag/retrieval.py`)
- [x] CLI: `realtorai ingest`, `realtorai rag status|query|sources`
- [x] Integrated into chat (knowledge-aware responses)
- [x] Integrated into email drafts (knowledge-aware drafts)
- [x] Ingested corpora: NAR Code of Ethics, Maine RE laws, NAR topical material

### Streaming chat — complete
- [x] CLI chat with streaming + RAG (`scripts/chat.py`)
- [x] CLI chat raw (no RAG, for benchmarking) (`scripts/chat_raw.py`)
- [x] Dashboard streaming chat (Server-Sent Events)
- [x] Quick Chat panel + full Chat page

### Web search — complete
- [x] DuckDuckGo search integration — no API key, free, unlimited
- [x] Tool definition for the LLM (`inference/tools.py:WEB_SEARCH_TOOL`)
- [x] Dispatcher handler (direct execution)

### MLS / market data (Spark API) — complete, awaiting credentials
- [x] OAuth 2.0 flow with browser redirect on port 8422
- [x] HTTP client with token refresh
- [x] Listing search, property details, comps, market stats
- [x] LLM tool definitions (`inference/tools.py:MLS_TOOLS`)
- [x] Buyer-alerts pipeline (recurring saved-search notifications)
- [x] CLI test script (`scripts/spark_test.py`)
- **Status:** Functional pending real Spark API credentials from sparkplatform.com

### Style fine-tuning — deferred
- [ ] LoRA fine-tuning pipeline
- [ ] Email + iMessage corpus preprocessing
- [ ] Communication-style training
- **Status:** Deferred until there's a realtor producing enough real
  correspondence to train on.

### iMessage integration — deferred
- [ ] Read from `~/Library/Messages/chat.db`
- [ ] Send via AppleScript
- [ ] Full Disk Access permission handling
- **Status:** Deferred — same blocker as fine-tuning (needs a working agent
  generating message volume).

## Phase 3: Transactions & Listings — well along

- [x] Transaction tracker (contract-to-close workflow)
- [x] DocuSign Rooms integration
- [x] Matterport tour ingest (email handler + zip download pipeline)
- [x] Document template system (e.g., buyer agency agreement)
- [x] Maine agency agreement gating on client interactions
- [x] Document-received workflow
- [x] Lead management UI + lifecycle
- [x] Client management UI (Add Client modal, Archive Client)
- [x] Active Clients dashboard panel
- [ ] Buyer-listing matching engine
- [ ] zipForm integration

## Phase 4: Mobile & Polish — future

- [ ] Mobile notifications / companion app
- [ ] Voice transcription
- [ ] Dashboard UI refinements

## Phase 5: Cloud — future

- [ ] AWS-hosted deployment for clients without Apple Silicon

---

## What's blocking

The technical surface is ahead of the human surface. The pieces that are
hardest to build on speculation — fine-tuning corpus, iMessage capture,
buyer-listing matching with real saved-search data, MLS credentials —
all want a real Maine realtor running the daemon for a few weeks and
telling me what's missing or wrong. Without that feedback loop the
remaining work is either (a) easy to ship but easy to overbuild without
ground truth, or (b) hard to ship and possibly wasted.

So: paused, not abandoned. The build resumes when there's a working
domain partner.

---

## Local layout

- Web UI: <http://localhost:8421>
- Spark OAuth callback: <http://localhost:8422/spark/callback>
- Daemon: background process, no port

## Quick commands

```bash
# Start web UI (dashboard)
realtorai web

# Start email-polling daemon
realtorai daemon --foreground

# CLI chat with RAG (streaming)
python scripts/chat.py

# CLI chat raw model (streaming)
python scripts/chat_raw.py

# Ingest documents
realtorai ingest /path/to/document.pdf
realtorai ingest https://example.com/page

# Knowledge base inspection
realtorai rag status
realtorai rag sources
realtorai rag query "your question here"

# Spark API (MLS) — needs credentials in .env
python scripts/spark_test.py status     # check connection
python scripts/spark_test.py connect    # OAuth authenticate
python scripts/spark_test.py search     # search listings
python scripts/spark_test.py market     # market stats

# Kill stale processes
pkill -f "realtorai"
lsof -ti :8421 | xargs kill -9
```

---

*Last updated: 2026-05-09*
