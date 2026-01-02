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
git clone <your-repo-url>
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

Define artists and their official sources. Keep it simple — just specify what to monitor:

```yaml
artists:
  - name: MyGO!!!!!
    keywords:
      - MyGO
    sources:
      - id: bangdream-events-mygo
        url: https://bang-dream.com/events
        filter_keywords:
          - MyGO
```

The system automatically:
- Fetches the listing page and discovers detail page links
- Extracts each detail page independently for accuracy
- Monitors known pages for updates (lottery ended → new sale opened)

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

| File/Directory | Purpose                                         |
| -------------- | ----------------------------------------------- |
| `sources.yaml` | Source configuration (what to monitor)          |
| `state.json`   | Tracks content hashes and known detail pages    |
| `events.json`  | Extracted events (the output)                   |
| `logs/`        | Debug logs with LLM requests/responses per run  |

## Extending

### Add a new artist

Edit `sources.yaml`:

```yaml
artists:
  - name: Your Artist
    sources:
      - id: artist-official
        url: https://example.com/news
        filter_keywords:
          - keyword1
```

Run `uv run nsyc-fetch --force` to fetch immediately.

### Export to Google Calendar

Coming soon. For now, manually create calendar events from `events.json`.

## License

MIT
