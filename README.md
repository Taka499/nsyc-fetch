# NSYC Fetch - Never Skip Your Content

A simple event fetcher that monitors official sources for artist announcements and extracts time-bound events (concerts, ticket sales, lotteries, releases) into a structured JSON format.

## Why?

- Concert tickets sell out fast. Lottery applications have deadlines.
- Information is scattered across official sites, fan clubs, and ticketing platforms.
- This tool watches official sources daily and extracts **actionable events with deadlines** into your calendar.

## How It Works

```
sources.yaml     → Define what to monitor
    ↓
Webpage scraping → Fetch content from official sites  
    ↓
LLM extraction   → GPT-4o-mini extracts structured events
    ↓
events.json      → Time-bound events with deadlines
```

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key

### Setup

```bash
# Clone and enter directory
git clone https://github.com/Taka499/nsyc-fetch.git
cd nsyc-fetch

# Install dependencies
uv sync

# Configure API key
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### Run Locally

```bash
# Fetch events
uv run nsyc-fetch

# Force re-fetch (ignore cache)
uv run nsyc-fetch --force

# Custom paths
uv run nsyc-fetch --config my-sources.yaml --output my-events.json
```

### Run via GitHub Actions

1. Fork this repository
2. Add `OPENAI_API_KEY` to repository secrets (Settings → Secrets → Actions)
3. The workflow runs daily at 9:00 AM JST
4. Events are committed to `events.json`

## Configuration

### sources.yaml

Create a `sources.yaml` file to define what to monitor. The file has a simple structure:

```yaml
artists:
  - name: Artist Name
    keywords:           # Optional: alternative names for matching
      - AltName
    sources:
      - id: unique-source-id
        url: https://example.com/events
        filter_keywords: # Optional: only follow links containing these
          - keyword
```

#### Full Example

```yaml
artists:
  - name: MyGO!!!!!
    keywords:
      - MyGO
      - マイゴ
    sources:
      # Events listing page
      - id: bangdream-events-mygo
        url: https://bang-dream.com/events
        description: BanG Dream! official events page
        max_detail_pages: 10
        filter_keywords:
          - MyGO

      # News page (same site, different section)
      - id: bangdream-news-mygo
        url: https://bang-dream.com/news
        description: BanG Dream! official news page
        max_detail_pages: 5
        filter_keywords:
          - MyGO

  - name: Ave Mujica
    keywords:
      - Ave Mujica
      - アヴェムジカ
    sources:
      - id: bangdream-events-avemujica
        url: https://bang-dream.com/events
        max_detail_pages: 10
        filter_keywords:
          - Ave Mujica
          - アヴェ
```

#### Field Reference

**Artist fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Artist display name used in extracted events |
| `keywords` | No | Alternative names/spellings for the artist |
| `sources` | Yes | List of sources to monitor |

**Source fields:**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `id` | Yes | — | Unique identifier for this source (used in state tracking) |
| `url` | Yes | — | Listing page URL to scrape for event links |
| `filter_keywords` | No | `[]` | Only follow links whose text/URL contains one of these keywords |
| `max_detail_pages` | No | `10` | Maximum number of detail pages to fetch per source |
| `description` | No | — | Human-readable description (for your reference) |

#### How It Works

1. **Listing page fetch**: The system fetches the `url` you specify
2. **Link discovery**: Finds all links to detail pages (matching `/events/`, `/news/` patterns)
3. **Keyword filtering**: If `filter_keywords` is set, only follows links containing those keywords
4. **Detail page extraction**: Each detail page is sent to the LLM independently for accurate extraction
5. **Change detection**: Pages are tracked by content hash; unchanged pages are skipped on subsequent runs
6. **Continuous monitoring**: Known pages are re-checked until the event date passes

#### Tips

- **One source per listing page**: If a site has separate `/events` and `/news` sections, create separate sources for each
- **Use filter_keywords**: Essential when multiple artists share the same listing page
- **Start with max_detail_pages: 5**: Increase if you're missing events, decrease to save API costs
- **Use descriptive ids**: Makes debugging easier (e.g., `sitename-section-artist` pattern)

### Output: events.json

```json
[
  {
    "artist": "MyGO!!!!!",
    "event_type": "lottery",
    "title": "MyGO!!!!! 9th LIVE 最速先行抽選",
    "date": "2025-12-06",
    "end_date": "2026-02-02",
    "action_required": true,
    "action_deadline": "2026-02-02T23:59:00",
    "action_description": "Apply using serial code from 8th Single (first-press)",
    "event_url": "https://bang-dream.com/events/mygo_9th"
  },
  {
    "artist": "MyGO!!!!!",
    "event_type": "live",
    "title": "MyGO!!!!! 9th LIVE",
    "date": "2026-07-18",
    "end_date": "2026-07-19",
    "venue": "ぴあアリーナMM",
    "location": "Yokohama",
    "action_required": false
  }
]
```

## Event Types

| Type        | Description               | Example               |
| ----------- | ------------------------- | --------------------- |
| `live`      | Concert, live performance | MyGO!!!!! 8th LIVE    |
| `lottery`   | Ticket lottery period     | 先行抽選受付          |
| `sale`      | Ticket general sale       | 一般発売              |
| `release`   | CD, album, single         | 2nd Album "Michinoku" |
| `streaming` | Online live streaming     | Streaming+            |
| `screening` | Theater screening         | LIVE FILM上映         |
| `broadcast` | TV, radio appearance      | THE FIRST TAKE        |

## Cost

- Uses `gpt-4o-mini` (~$0.15/1M input tokens)
- Typical run: <5000 tokens = **<$0.001 per run**
- Daily runs ≈ **$0.03/month**

## Files

| File/Directory | Purpose                                        |
| -------------- | ---------------------------------------------- |
| `sources.yaml` | Source configuration (what to monitor)         |
| `state.json`   | Tracks content hashes and known detail pages   |
| `events.json`  | Extracted events (the output)                  |
| `logs/`        | Debug logs with LLM requests/responses per run |

## Extending

### Add a new artist

1. Edit `sources.yaml` and add a new artist entry (see [sources.yaml](#sourcesyaml) for field reference)
2. Run `uv run nsyc-fetch --force` to fetch immediately

### Export to Google Calendar

Coming soon. For now, manually create calendar events from `events.json`.

## License

MIT
