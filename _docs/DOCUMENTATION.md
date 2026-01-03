# NSYC-Fetch: Never Skip Your Content

## Project Documentation

**Version:** 0.1.0  
**Last Updated:** January 2026  
**Status:** MVP Implementation Complete

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Market Context](#3-market-context)
4. [Our Approach](#4-our-approach)
5. [Architecture](#5-architecture)
6. [Implementation Details](#6-implementation-details)
7. [Setup Guide](#7-setup-guide)
8. [Usage](#8-usage)
9. [Configuration](#9-configuration)
10. [Output Format](#10-output-format)
11. [Known Issues & Limitations](#11-known-issues--limitations)
12. [Future Roadmap](#12-future-roadmap)
13. [Cost Analysis](#13-cost-analysis)
14. [File Structure](#14-file-structure)

---

## 1. Executive Summary

NSYC-Fetch is a **calendar population system** that monitors official artist websites and extracts time-bound events (concerts, ticket lotteries, sales deadlines) into structured JSON format.

**Core Value Proposition:**  
> "Never miss a ticket lottery deadline because it's already in your calendar."

Unlike general-purpose AI assistants that provide information on-demand, this system:
- **Proactively monitors** specific sources you care about
- **Extracts actionable deadlines** (not just announcements)
- **Outputs structured data** ready for calendar integration

---

## 2. Problem Statement

### The User Pain Point

Fans of Japanese artists (bands, voice actors, etc.) face a recurring problem:

1. **Information is scattered** across official websites, Twitter/X, fan clubs, and ticketing platforms
2. **Ticket sales have short windows** — lottery applications may only be open for 1-2 weeks
3. **Multiple deadlines per event** — CD pre-order (with lottery code), lottery application period, general sale date
4. **Manual tracking is tedious** — checking multiple sites daily is unsustainable

### Concrete Example: BanG Dream! Concert Ticket Flow

```
Timeline for "MyGO!!!!! 9th LIVE" (July 2026):

[February] CD "Michinoku" announced with lottery code for concert
     ↓
[March 1-15] CD purchase window to get lottery code
     ↓
[March 20 - April 5] Lottery application period (requires code)
     ↓
[April 15] Lottery results announced
     ↓
[May 1] General ticket sale (sells out in minutes)
     ↓
[July 18-19] Concert dates
```

**Missing ANY deadline = no ticket.**

The system must track not just the concert date, but ALL intermediate deadlines.

---

## 3. Market Context

### Competitive Landscape (as of January 2026)

**OpenAI ChatGPT Pulse** (Released September 2025):
- Proactive daily briefings based on chat history and connected apps
- Uses memory + Gmail/Calendar integration
- Overnight batch processing → morning delivery
- $200/month (Pro tier only)

**Google Gemini Scheduled Actions:**
- Recurring prompts at set times
- $20/month
- Limited to 10 scheduled actions

### Why These Don't Solve Our Problem

| Feature | ChatGPT Pulse | NSYC-Fetch |
|---------|---------------|------------|
| Real-time monitoring | ❌ Overnight batch | ✅ Configurable frequency |
| Source-specific tracking | ❌ General web search | ✅ Specific URLs monitored |
| Domain knowledge | ❌ Generic | ✅ Understands lottery/presale patterns |
| Deadline extraction | ❌ Informational only | ✅ Actionable deadlines |
| Cost | $200/month | ~$0.03/month |
| Data ownership | ❌ OpenAI's servers | ✅ Your JSON files |

### Our Differentiation

1. **Specificity over generality** — We monitor exact sources, not "the web"
2. **Deadlines over information** — We extract "apply by March 15" not "tickets available"
3. **Transparency** — Plain JSON output, no black box
4. **Cost efficiency** — Run on GitHub Actions for free, pay only for LLM API (~$0.001/run)

---

## 4. Our Approach

### Core Insight

This is a **monitoring problem**, not a search problem.

| Step | Requires LLM? | Implementation |
|------|---------------|----------------|
| Source Discovery | Yes (one-time) | Manual or assisted setup |
| Source Monitoring | No | Cron job + HTTP requests |
| Content Understanding | **Yes** | LLM classification |
| Deadline Extraction | **Yes** | LLM structured output |
| Notification Delivery | No | JSON → Calendar API |

**LLM value concentrates in steps 3-4.** Everything else is standard infrastructure.

### Design Decisions

1. **Two-pass fetching**: Listing page → Detail pages (to get full info)
2. **Change detection**: Hash-based, only process when content changes
3. **Retry on failure**: Don't update hash until extraction succeeds
4. **Structured output**: JSON schema for calendar integration
5. **Minimal dependencies**: Python + httpx + BeautifulSoup + OpenAI

---

## 5. Architecture

### System Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        sources.yaml                              │
│   Define: artist name, source URLs, keywords                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Fetcher (fetcher.py)                         │
│                                                                  │
│   1. Fetch listing page (e.g., bang-dream.com/events)           │
│   2. Extract links to detail pages                               │
│   3. Fetch each detail page                                      │
│   4. Combine all content                                         │
│   5. Compute content hash for change detection                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    State Check (state.json)                      │
│                                                                  │
│   - Compare current hash vs stored hash                          │
│   - Skip if unchanged (save API cost)                            │
│   - Continue if new/changed content                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Extractor (extractor.py)                       │
│                                                                  │
│   - Send content to GPT-4o-mini                                  │
│   - Prompt engineered for Japanese entertainment events          │
│   - Extract: dates, venues, lottery periods, deadlines, URLs     │
│   - Return structured Event objects                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Output (events.json)                          │
│                                                                  │
│   - Merge with existing events                                   │
│   - Deduplicate by event_id                                      │
│   - Sort by date                                                 │
│   - Ready for calendar integration                               │
└─────────────────────────────────────────────────────────────────┘
```

### Key Components

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point, orchestrates fetch→extract→save |
| `fetcher.py` | HTTP requests, HTML parsing, link extraction |
| `extractor.py` | LLM prompt, JSON parsing, Event creation |
| `models.py` | Pydantic schemas for Event, FetchState, etc. |
| `sources.yaml` | User configuration — what to monitor |
| `state.json` | Persistent state — content hashes, last run time |
| `events.json` | Output — extracted events |

---

## 6. Implementation Details

### Two-Pass Fetching

**Problem:** Listing pages only show summaries. Detail pages have lottery dates, ticket URLs.

**Solution:**

```python
# Pass 1: Fetch listing page
html = await fetch_webpage("https://bang-dream.com/events")

# Extract links to detail pages
links = extract_event_links(html, base_url, filter_keywords)
# → ["https://bang-dream.com/events/mygo-9th", ...]

# Pass 2: Fetch each detail page
for link in links[:max_detail_pages]:
    detail_html = await fetch_webpage(link)
    detail_text = extract_detail_page_content(detail_html)
    # Combine with listing content
```

### Change Detection

**Problem:** Don't waste API calls if nothing changed.

**Solution:** Per-page hash tracking:

```python
# For each detail page URL
page_content = await fetch_detail_page(url)
old_state = state.detail_pages.get(url)
old_hash = old_state.content_hash if old_state else None

# Skip if unchanged
if old_hash == page_content.content_hash:
    print("No changes detected")
    continue  # Skip extraction for this page

# Only update hash AFTER successful extraction
events = extract_events(page_content.content)
if events is not None:  # None = failure, [] = success with no events
    state.detail_pages[url] = DetailPageState(
        url=url,
        content_hash=page_content.content_hash,
        last_checked=now,
        event_date=max_event_date,
        source_id=source_id,
    )
```

### LLM Extraction Prompt

The prompt is engineered for Japanese entertainment events:

```python
EXTRACTION_PROMPT = """
Extract time-bound events related to "{artist_name}".

Pay special attention to:
- 先行抽選 / 抽選 (lottery) - note the application period
- 先行発売 / 一般発売 (ticket sales) - note as "sale" event
- ライブ / LIVE / 公演 (concerts) - note as "live" event
- CD / アルバム / シングル releases - note as "release" event

For each event, extract:
- event_id: Stable identifier (lowercase-title-YYYY-MM-DD)
- parent_event_id: For lottery/sale, the parent concert's event_id
- event_type: live, lottery, sale, release, streaming, screening, other
- title: Event title (original language)
- date: Start date (ISO format)
- end_date: End date if multi-day
- venue, location
- action_required: true if user needs to take action
- action_deadline: When action must be completed
- action_description: What to do
- event_url, ticket_url

Respond with JSON only.
"""
```

### Error Handling

| Scenario | Behavior |
|----------|----------|
| Network error | Don't update hash → retry next run |
| LLM API error | Return `None` → don't update hash → retry |
| JSON parse error | Return `None` → retry |
| No events found | Return `[]` → update hash (nothing to find) |
| Success | Return events → update hash |

---

## 7. Setup Guide

### Prerequisites

- **Python 3.11+**
- **uv** (Python package manager): https://docs.astral.sh/uv/
- **OpenAI API key**: https://platform.openai.com/api-keys

### Installation

```bash
# Clone or download the project
cd nsyc-fetch

# Install dependencies
uv sync

# Configure API key
cp .env.example .env
# Edit .env:
# OPENAI_API_KEY=sk-your-key-here
```

### Verify Installation

```bash
uv run nsyc-fetch --help
```

Expected output:
```
usage: nsyc-fetch [-h] [--config CONFIG] [--state STATE] [--output OUTPUT] [--force]

Fetch events for tracked artists

options:
  -h, --help       show this help message and exit
  --config CONFIG  Path to sources configuration file
  --state STATE    Path to state file
  --output OUTPUT  Path to output events file
  --force          Force re-fetch even if content hasn't changed
```

---

## 8. Usage

### Run Locally

```bash
# Standard run (skip unchanged sources)
uv run nsyc-fetch

# Force re-fetch all sources
uv run nsyc-fetch --force

# Custom file paths
uv run nsyc-fetch --config my-sources.yaml --output my-events.json
```

### Run via GitHub Actions

1. **Fork/create repository** with this code
2. **Add secret**: Settings → Secrets → Actions → `OPENAI_API_KEY`
3. **Enable workflow**: Actions tab → Enable workflows
4. **Schedule**: Runs daily at 9:00 AM JST (configurable in `.github/workflows/daily.yaml`)

The workflow:
```yaml
on:
  schedule:
    - cron: '0 0 * * *'  # 00:00 UTC = 09:00 JST
  workflow_dispatch:      # Manual trigger

jobs:
  fetch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run nsyc-fetch
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      - run: |
          git add state.json events.json
          git commit -m "Update events" || true
          git push
```

---

## 9. Configuration

### sources.yaml

```yaml
artists:
  - name: MyGO!!!!!                    # Artist display name
    keywords:                          # Alternative names/spellings
      - MyGO
      - 迷跡波
      - マイゴ
    sources:
      - id: bangdream-events-mygo      # Unique identifier
        type: webpage
        url: https://bang-dream.com/events
        description: BanG Dream! official events page
        max_detail_pages: 10           # Limit detail pages per source
        filter_keywords:               # Only fetch pages containing these
          - MyGO
          - 迷跡波

  - name: Ave Mujica
    keywords:
      - Ave Mujica
      - アヴェムジカ
    sources:
      - id: bangdream-events-avemujica
        type: webpage
        url: https://bang-dream.com/events
        max_detail_pages: 10
        filter_keywords:
          - Ave Mujica
          - アヴェ
```

### Source Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | string | required | Unique identifier for state tracking |
| `type` | string | required | Currently only "webpage" supported |
| `url` | string | required | URL to monitor |
| `description` | string | optional | Human-readable description |
| `max_detail_pages` | int | `10` | Maximum detail pages to fetch |
| `filter_keywords` | list | `[]` | Keywords to filter relevant content |

### Adding a New Artist

1. Edit `sources.yaml`
2. Add new artist entry:

```yaml
  - name: Your Artist
    keywords:
      - keyword1
      - keyword2
    sources:
      - id: unique-source-id
        type: webpage
        url: https://official-site.com/news
        filter_keywords:
          - keyword1
```

3. Run with `--force` to fetch immediately:

```bash
uv run nsyc-fetch --force
```

---

## 10. Output Format

### events.json

```json
[
  {
    "event_id": "mygo-9th-live-2026-07-18",
    "parent_event_id": null,
    "artist": "MyGO!!!!!",
    "event_type": "live",
    "title": "MyGO!!!!! 9th LIVE",
    "date": "2026-07-18T00:00:00",
    "end_date": "2026-07-19T00:00:00",
    "venue": "ぴあアリーナMM",
    "location": "Yokohama",
    "action_required": false,
    "action_deadline": null,
    "action_description": null,
    "event_url": "https://bang-dream.com/events/mygo-9th",
    "ticket_url": null,
    "source_url": "https://bang-dream.com/events",
    "extracted_at": "2026-01-15T10:30:00.000000",
    "raw_text": null,
    "ended": false
  },
  {
    "event_id": "mygo-9th-live-2026-07-18-lottery-cd",
    "parent_event_id": "mygo-9th-live-2026-07-18",
    "artist": "MyGO!!!!!",
    "event_type": "lottery",
    "title": "MyGO!!!!! 9th LIVE CD先行抽選",
    "date": "2026-03-20T00:00:00",
    "end_date": "2026-04-05T00:00:00",
    "venue": null,
    "location": null,
    "action_required": true,
    "action_deadline": "2026-04-05T23:59:00",
    "action_description": "Apply using serial code from CD (first-press edition)",
    "event_url": "https://bang-dream.com/events/mygo-9th",
    "ticket_url": "https://eplus.jp/mygo-9th/",
    "source_url": "https://bang-dream.com/events",
    "extracted_at": "2026-01-15T10:30:00.000000",
    "raw_text": null,
    "ended": false
  }
]
```

### Event Types

| Type | Description | Example |
|------|-------------|---------|
| `live` | Concert, live performance | MyGO!!!!! 9th LIVE |
| `lottery` | Ticket lottery application period | 先行抽選受付 |
| `sale` | Ticket general sale | 一般発売 |
| `release` | CD, album, single release | 2nd Album "Michinoku" |
| `streaming` | Online live streaming | Streaming+ |
| `screening` | Theater screening | LIVE FILM上映 |
| `broadcast` | TV, radio appearance | THE FIRST TAKE |
| `other` | Anything else | Fan meeting, exhibition |

### state.json

```json
{
  "last_run": "2026-01-15T10:30:00.000000",
  "detail_pages": {
    "https://bang-dream.com/events/mygo-9th": {
      "url": "https://bang-dream.com/events/mygo-9th",
      "content_hash": "a1b2c3d4e5f6g7h8",
      "last_checked": "2026-01-15T10:30:00.000000",
      "event_date": "2026-07-19T00:00:00",
      "source_id": "bangdream-events-mygo"
    }
  },
  "seen_event_ids": []
}
```

---

## 11. Known Issues & Limitations

### Current Limitations

1. **Japanese sites only** — Prompt and keyword matching optimized for Japanese
2. **Static HTML only** — Cannot handle JavaScript-rendered content
3. **No authentication** — Cannot access fan club pages requiring login
4. **Single timezone** — Dates extracted without timezone info
5. **No notification** — Outputs JSON only, no push notifications yet

### Known Issues

| Issue | Workaround |
|-------|------------|
| Link extraction may miss some patterns | Add more regex patterns to `extract_event_links()` |
| LLM may hallucinate dates | Verify critical deadlines manually |
| Rate limiting on target sites | Reduce `max_detail_pages` |
| Large content truncation | Content truncated at 12K chars for LLM |

### Sites That Won't Work

- Fan club members-only pages (require login)
- eplus.jp (JavaScript-heavy, requires session)
- Sites with bot protection (Cloudflare, etc.)

---

## 12. Future Roadmap

### Phase 1: Calendar Integration (Next)

- [ ] Google Calendar API integration
- [ ] iCal (.ics) file export
- [ ] Notion database sync

### Phase 2: Better Extraction

- [ ] Structured scraping for known sites (BanG Dream!, etc.)
- [ ] Template-based extraction (fallback when LLM fails)
- [ ] Multi-language support

### Phase 3: Notifications

- [ ] Email notifications for new events
- [ ] LINE Bot integration
- [ ] Discord webhook

### Phase 4: Source Discovery

- [ ] Automatic source discovery from artist name
- [ ] Social media monitoring (Twitter/X via RSS bridge)
- [ ] Ticketing platform integration

---

## 13. Cost Analysis

### API Costs

| Component | Cost |
|-----------|------|
| GPT-4o-mini input | $0.15 / 1M tokens |
| GPT-4o-mini output | $0.60 / 1M tokens |

### Typical Run

- Content per source: ~3,000 tokens
- 4 sources (2 artists × 2 pages): ~12,000 input tokens
- Output: ~500 tokens per source = ~2,000 tokens

**Cost per run:** ~$0.003 (less than 1 cent)

### Monthly Cost

- Daily runs: 30 × $0.003 = **$0.09/month**
- With detail page fetching (more content): ~**$0.30/month**

### Comparison

| Service | Monthly Cost |
|---------|--------------|
| ChatGPT Pro (Pulse) | $200 |
| ChatGPT Plus | $20 |
| NSYC-Fetch | ~$0.30 |

---

## 14. File Structure

```
nsyc-fetch/
├── pyproject.toml              # Project config and dependencies
├── uv.lock                     # Locked dependencies
├── .env.example                # API key template
├── .gitignore
├── README.md                   # Quick start guide
├── DOCUMENTATION.md            # This file
│
├── sources.yaml                # Source configuration (edit this)
├── state.json                  # Persistent state (auto-managed)
├── events.json                 # Output events (auto-generated)
│
├── src/
│   └── nsyc_fetch/
│       ├── __init__.py
│       ├── main.py             # CLI entry point
│       ├── fetcher.py          # HTTP fetching, HTML parsing
│       ├── extractor.py        # LLM extraction logic
│       └── models.py           # Pydantic data models
│
└── .github/
    └── workflows/
        └── daily.yaml          # GitHub Actions cron job
```

---

## Appendix: Quick Reference

### Commands

```bash
# Install
uv sync

# Run (normal)
uv run nsyc-fetch

# Run (force refresh)
uv run nsyc-fetch --force

# Run (custom config)
uv run nsyc-fetch --config my-sources.yaml --output my-events.json
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key for GPT-4o-mini |

### Files to Edit

| File | When to Edit |
|------|--------------|
| `sources.yaml` | Add/remove artists or sources |
| `.env` | Set API key |
| `state.json` | Delete to force re-fetch all |
| `events.json` | Don't edit (auto-generated) |

### Troubleshooting

| Problem | Solution |
|---------|----------|
| "OPENAI_API_KEY not set" | Create `.env` file with your key |
| No events extracted | Check `filter_keywords` match content |
| Same events every run | Content unchanged; use `--force` |
| API rate limit | Wait and retry, or reduce `max_detail_pages` |
| Missing detail info | Site may use JavaScript; check manually |

---

*Document generated: January 2026*
