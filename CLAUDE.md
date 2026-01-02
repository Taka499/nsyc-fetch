# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ExecPlans

When writing complex features or significant refactors, use an ExecPlan (as described in `_docs/PLANS.md`) from design to implementation.

## Project Overview

NSYC-Fetch ("Never Skip Your Content") monitors official artist websites and extracts time-bound events (concerts, ticket lotteries, sales deadlines) into structured JSON. It solves the problem of missing ticket lottery deadlines by proactively monitoring sources and extracting actionable deadlines.

**Core flow:** `sources.yaml` → Webpage scraping → LLM extraction (GPT-4o-mini) → `events.json`

## Commands

```bash
# Install dependencies
uv sync

# Run the fetcher
uv run nsyc-fetch

# Force re-fetch (ignore content hashes)
uv run nsyc-fetch --force

# Custom paths
uv run nsyc-fetch --config my-sources.yaml --output my-events.json
```

## Architecture

```
src/nsyc_fetch/
├── main.py       # CLI entry point, orchestrates fetch→extract→save pipeline
├── fetcher.py    # HTTP requests (httpx), HTML parsing (BeautifulSoup), link extraction
├── extractor.py  # LLM prompt engineering, JSON parsing, Event creation
├── logger.py     # Structured logging for debugging LLM interactions
└── models.py     # Pydantic schemas: Event, EventType, SourceContent, FetchState
```

**Key data flow:**

1. `main.py:run_fetch()` loads `sources.yaml` and iterates over artists/sources
2. `fetcher.py:discover_event_urls()` finds detail page URLs from listing pages
3. `fetcher.py:fetch_detail_page()` fetches each detail page independently
4. Content hashes compared against `state.json` to skip unchanged pages
5. Each detail page is extracted independently via `extractor.py` (per-page extraction)
6. Events upserted by signature `(artist|title|date)` — existing events updated, new ones added
7. Past events automatically marked with `ended=True`
8. State hash updated only after successful extraction (retry-on-failure pattern)
9. Logs saved to `logs/{timestamp}/{source_id}/` for debugging

**Key files (user-managed):**
- `sources.yaml` — source configuration (what to monitor: artists, URLs, filter keywords)
- `state.json` — content hashes and known detail pages (auto-managed)
- `events.json` — extracted events output (auto-generated)
- `logs/` — debug logs with LLM requests/responses (auto-generated)

## Key Implementation Details

**Two-pass fetching** (`fetcher.py`): Listing pages only show summaries. Detail pages have lottery dates and ticket URLs. The fetcher extracts links matching `/events/` or `/news/` patterns and fetches each detail page.

**Per-page extraction**: Each detail page is sent to the LLM independently. This prevents context dilution where lottery info from one event gets lost among content from other events.

**Change detection** (`fetcher.py:compute_content_hash()`): SHA-256 hash of content. Hash only updated after successful LLM extraction, so failures retry on next run.

**LLM extraction prompt** (`extractor.py:EXTRACTION_PROMPT`): Engineered for Japanese entertainment events. Recognizes:
- CD先行/シリアル先行 (CD lottery with serial code prerequisite)
- 先行抽選 (lottery), 先行発売/一般発売 (ticket sales)
- ライブ/LIVE/公演 (concerts), CD/アルバム releases

**Event types** (`models.py:EventType`): live, release, lottery, sale, broadcast, streaming, screening, other

**Structured logging** (`logger.py`): Each run creates `logs/{timestamp}/` with per-source subdirectories containing `fetched_content.json`, `llm_request.json`, `llm_response.json`, and `extracted_events.json`.

## Design Principles

**sources.yaml is about "what to monitor", not "how to process"**: Keep user configuration minimal. Processing decisions (per-page extraction, update detection) are handled automatically by the system, not configured per-source.

**Event lifecycle**: Detail pages change over time (lottery ends → new sale opens). The system monitors known detail pages for updates until the event date passes. Events have an `ended` flag that is automatically set to `true` when the event date passes, distinguishing active from historical events.

## Environment

Requires `OPENAI_API_KEY` environment variable. Use `.env` file (copy from `.env.example`).

## Commit Discipline

- Follow Git-flow workflow to manage branches
- Use small, frequent commits rather than large, infrequent ones
- Only add and commit affected files; keep untracked files as they are
- Never add Claude Code attribution in commits
