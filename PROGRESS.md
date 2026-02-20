# RealtorAI Development Progress

## Current Status
**Phase 2: Knowledge & Style** - IN PROGRESS

## Phase 1: Email Triage MVP ✓ COMPLETE
- [x] Project setup (pyproject.toml, uv, structure)
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

## Phase 2: Knowledge & Style (Current)

### RAG Knowledge Base ✓ COMPLETE
- [x] ChromaDB vector store (`src/realtorai/rag/store.py`)
- [x] Document ingestion - PDF, TXT, MD, RTF, URLs (`src/realtorai/rag/ingestion.py`)
- [x] Retrieval and prompt augmentation (`src/realtorai/rag/retrieval.py`)
- [x] Config from `realtorAI_config.yaml` (`src/realtorai/rag/config.py`)
- [x] CLI commands: `realtorai ingest`, `realtorai rag status|query|sources`
- [x] Integrated into chat (knowledge-aware responses)
- [x] Integrated into email drafts (knowledge-aware drafts)
- [x] Ingested: NAR Code of Ethics (30 chunks), Maine RE Laws (7 chunks), NAR Topics (9 chunks)

### Streaming Chat ✓ COMPLETE
- [x] CLI chat with streaming (`scripts/chat.py` - with RAG)
- [x] CLI chat raw (`scripts/chat_raw.py` - no RAG, for benchmarking)
- [x] Dashboard streaming chat (Server-Sent Events)
- [x] Quick Chat streaming on dashboard
- [x] Full Chat page streaming

### Web Search ✓ COMPLETE
- [x] DuckDuckGo search integration (`src/realtorai/integrations/web/search.py`)
- [x] Tool definition for LLM (`inference/tools.py` - WEB_SEARCH_TOOL)
- [x] Dispatcher handler (direct execution)
- [x] News search function available
- **No API key required, free, unlimited**

### MLS / Market Data ✓ COMPLETE (Awaiting Credentials)
- [x] Spark API integration module (`src/realtorai/integrations/spark/`)
- [x] OAuth2 authentication flow (`auth.py` - browser redirect on port 8422)
- [x] HTTP client with token refresh (`client.py`)
- [x] Listing search function (`listings.py:search_listings`)
- [x] Property details retrieval (`listings.py:get_listing`, `get_listing_photos`)
- [x] Comparable sales search (`listings.py:find_comps`)
- [x] Market statistics (`listings.py:get_market_stats`)
- [x] LLM tool definitions (`inference/tools.py` - MLS_TOOLS)
- [x] Dispatcher handlers (direct execution for read-only MLS queries)
- [x] CLI test script (`scripts/spark_test.py`)
- [ ] Local SQLite listing cache (deferred - API works fine)
- **Status:** Need Spark API credentials from sparkplatform.com to test

### Fine-Tuning (Planned)
- [ ] LoRA fine-tuning pipeline
- [ ] Email corpus preprocessing
- [ ] Text message corpus preprocessing
- [ ] Communication style training

### iMessage Integration (Planned)
- [ ] Read from `~/Library/Messages/chat.db`
- [ ] Send via AppleScript
- [ ] Full Disk Access permission handling
- **Reference:** `/Users/bz/RealtyAI/imessage_integration_reference.md`

## Phase 3: Transactions & Listings (Future)
- [ ] Transaction checklist system
- [ ] Deal file management
- [ ] DocuSign Rooms integration
- [ ] zipForm integration
- [ ] Matterport API integration
- [ ] Buyer-listing matching engine

## Phase 4: Mobile & Polish (Future)
- [ ] Mobile notifications
- [ ] Auto-open browser on `realtorai web`
- [ ] Dashboard UI refinements
- [ ] Performance optimization

---

## Key Files

**RAG Module:**
- `src/realtorai/rag/config.py` - loads settings from YAML
- `src/realtorai/rag/store.py` - ChromaDB wrapper
- `src/realtorai/rag/ingestion.py` - document chunking & ingestion
- `src/realtorai/rag/retrieval.py` - semantic search & prompt augmentation

**Web Search:**
- `src/realtorai/integrations/web/search.py` - DuckDuckGo search (free, no API key)

**Spark API Integration:**
- `src/realtorai/integrations/spark/auth.py` - OAuth 2.0 flow
- `src/realtorai/integrations/spark/client.py` - HTTP client
- `src/realtorai/integrations/spark/listings.py` - MLS search, comps, market stats
- `scripts/spark_test.py` - CLI test script

**CLI Scripts:**
- `scripts/chat.py` - streaming CLI chat with RAG
- `scripts/chat_raw.py` - streaming CLI chat, raw model only
- `scripts/bench_*.py` - benchmarking scripts

**Config:**
- `/Users/bz/RealtyAI/realtorAI_config.yaml` - all tunable parameters
- Embedding model: `all-MiniLM-L6-v2`
- Chunk size: 512 tokens, overlap: 50 tokens

**Design Doc:**
- `/Users/bz/RealtyAI/knowledge_docs/RealtorAI_Technical_Design_v3.docx`

---

## Configuration

**Azure App Registration:**
- Client ID: `fc3447cb-f95c-4ec0-b4a1-1a47f8156eb4`
- Redirect URI: `http://localhost:8421/callback`
- Permissions: Mail.Read, Mail.Send, User.Read, Calendars.ReadWrite

**Email:** `realtorai@outlook.com` (alias for testing)

**Spark API (MLS):**
- Developer portal: https://sparkplatform.com/
- Set in `.env`: `SPARK_CLIENT_ID` and `SPARK_CLIENT_SECRET`
- OAuth redirect: `http://localhost:8422/spark/callback`

**Model:** `mlx-community/Meta-Llama-3.1-8B-Instruct-4bit`

**Ports:**
- Web UI: 8421
- Spark OAuth callback: 8422
- (Daemon runs in background, no port)

---

## Quick Commands

```bash
# Activate environment
cd /Users/bz/RealtyAI/realtorai
source .venv/bin/activate

# Start web UI (dashboard)
realtorai web

# Start daemon (email polling)
realtorai daemon --foreground

# CLI chat with RAG (streaming)
python scripts/chat.py

# CLI chat raw model (streaming)
python scripts/chat_raw.py

# Ingest documents to knowledge base
realtorai ingest /path/to/document.pdf
realtorai ingest https://example.com/page

# Check knowledge base status
realtorai rag status
realtorai rag sources
realtorai rag query "your question here"

# Spark API (MLS)
python scripts/spark_test.py status     # Check connection
python scripts/spark_test.py connect    # OAuth authenticate
python scripts/spark_test.py search     # Search listings
python scripts/spark_test.py market     # Get market stats

# Kill stale processes
pkill -f "realtorai"
lsof -ti :8421 | xargs kill -9
```

---

*Last updated: 2026-02-17*

## Future Improvements

### Matterport Integration
- [ ] Filter dashboard to show only MLS-ready images (curated listing photos), not all panoramic skybox images
- [ ] Matterport zip downloads typically include curated "highlight" images - prioritize those in the UI

