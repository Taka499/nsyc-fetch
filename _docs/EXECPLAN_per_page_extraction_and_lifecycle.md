# Per-Page Extraction and Event Lifecycle Monitoring

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document must be maintained in accordance with `_docs/PLANS.md`.


## Purpose / Big Picture

NSYC-Fetch currently batches all detail page content together and sends it to the LLM in a single call. This causes context dilution where critical lottery information from one event can be overshadowed by content from other events. Additionally, the system only detects when new events appear on listing pages but misses updates to existing events (such as when a lottery period ends and a new ticket sale opens).

After this work is complete:

1. Each detail page is extracted independently, ensuring no information is lost to context dilution or truncation.
2. Known detail pages are monitored for updates, so users are notified when lottery periods end and new ticket sales become available.
3. Events have an `ended` flag to distinguish active events from historical records, and the system updates existing events instead of creating duplicates.

To verify success, run `uv run nsyc-fetch --force` and observe:
- Logs show separate LLM calls per detail page (not one combined call)
- State file tracks individual detail page URLs and their content hashes
- Running again (without --force) still checks known detail pages for updates


## Progress

- [x] Milestone 1: Implement per-page extraction as default
- [x] Milestone 2: Track detail page URLs in state
- [x] Milestone 3: Detect and handle updates to known detail pages
- [x] Milestone 4: Add ended flag and event update logic


## Surprises & Discoveries

- Milestone 1 (2026-01-02): Per-page extraction significantly increases the number of events extracted. The previous batch approach was likely losing some events to context dilution. With per-page extraction, we now get more accurate lottery information for each event.

- Milestone 2 (2026-01-02): Added `source_id` field to `DetailPageState` beyond what was originally planned. This allows filtering known pages by source during Milestone 3 implementation. Also added `detail_page_hashes` to `SourceContent` to pass per-page hashes from fetcher to main.py cleanly.

- Milestone 3 (2026-01-02): Major refactor to separate URL discovery from detail page fetching. Removed `SourceContent` in favor of simpler `DetailPageContent`. The fetcher is now stateless with two functions: `discover_event_urls()` and `fetch_detail_page()`. All state logic moved to main.py orchestrator. Removed `source_hashes` from `FetchState` since we now track at detail page level only.

- Milestone 4 (2026-01-02): Changed `save_events()` from conditional to always-run. Previously it only saved when new events were extracted, but we need to mark ended events on every run even when no pages changed.


## Decision Log

- Decision: Per-page extraction is the default, not an optional mode.
  Rationale: Batch extraction was an MVP shortcut that sacrifices accuracy for cost savings. Getting exact information from each event page is essential; users will miss tickets if lottery info is lost to context dilution. The cost increase (~10x API calls) is acceptable for accuracy.
  Date/Author: 2026-01-02

- Decision: Keep `sources.yaml` focused on "what to monitor", not "how to process".
  Rationale: Processing decisions like extraction mode belong in code defaults or CLI flags, not per-source configuration. This keeps the user-facing config simple and reduces confusion from overlapping fields.
  Date/Author: 2026-01-02

- Decision: Monitor detail pages until the event date passes.
  Rationale: Event pages evolve over time (lottery ends → new sale opens → general sale → day-of info). The event date is the natural stopping point after which no new actionable deadlines will appear.
  Date/Author: 2026-01-02

- Decision: Keep ended events for historical record rather than deleting them.
  Rationale: Users may want to review past events, and the data volume is low. An `ended: true` flag distinguishes active from historical events without losing data.
  Date/Author: 2026-01-02

- Decision: Separate URL discovery from detail page fetching with stateless fetcher.
  Rationale: The original `fetch_source()` mixed concerns: discovering URLs, fetching detail pages, formatting content, and computing hashes. For update detection (Milestone 3), we need to compare fetched content against stored state. Rather than making the fetcher state-aware, we split it into two simple functions: `discover_event_urls()` returns URLs from the listing page, `fetch_detail_page()` fetches a single page and returns (content, hash). The orchestrator in main.py handles all state logic: merging known URLs with newly discovered ones, comparing hashes, deciding what to extract, and updating state. This keeps the fetcher pure (URL in → content out) and puts all state management in one place.
  Date/Author: 2026-01-02


## Outcomes & Retrospective

**Completed 2026-01-02**

All four milestones completed successfully:

1. **Per-page extraction**: Each detail page is now sent to the LLM independently. This eliminated context dilution and increased extraction accuracy.

2. **Detail page state tracking**: `state.json` now tracks individual detail pages with their content hashes, enabling update detection.

3. **Update detection**: The system merges known URLs with newly discovered ones. Pages are re-extracted only when their content hash changes.

4. **Ended flag and upsert logic**: Events now have an `ended: bool` field. Past events are automatically marked as ended on every run. `save_events()` uses upsert logic to update existing events by signature rather than creating duplicates.

**Verified behavior:**
- 16 of 36 events correctly marked as `ended=True` (dates before 2026-01-02)
- Active events sorted before ended events in output
- `save_events()` runs on every fetch, even with no new events, to keep ended status current


## Context and Orientation

NSYC-Fetch is a Python CLI tool that monitors Japanese artist websites and extracts time-bound events (concerts, ticket lotteries, deadlines) into structured JSON. The codebase lives in `src/nsyc_fetch/` with these modules:

- `main.py` — CLI entry point, orchestrates the fetch-extract-save pipeline
- `fetcher.py` — HTTP requests using httpx, HTML parsing with BeautifulSoup, link extraction
- `extractor.py` — LLM prompt construction, OpenAI API calls, JSON response parsing
- `logger.py` — Structured logging for debugging (created in prior ExecPlan)
- `models.py` — Pydantic schemas for Event, EventType, SourceContent, FetchState

Current data flow:

1. `main.py:run_fetch()` loads `sources.yaml` and iterates over artists/sources
2. `fetcher.py:fetch_source()` fetches listing page, extracts links, fetches detail pages
3. All detail page content is combined into `relevant_sections` list
4. `extractor.py:extract_events_from_sections()` sends combined content to GPT-4o-mini in ONE call
5. Content hash (of combined content) compared against `state.json` to skip unchanged sources
6. Events saved to `events.json`, deduplicated by `(artist, title, date)` signature

Current state tracking (in `state.json`):

    {
      "last_run": "2026-01-02T00:00:00",
      "source_hashes": {
        "bangdream-events-mygo": "abc123..."  // hash of COMBINED content
      },
      "seen_event_ids": []
    }

The problem with current design:

1. **Context dilution**: When 10 detail pages are combined, the LLM may miss lottery info from one page because it's buried among concert info from other pages.

2. **No update detection**: Once a detail page is fetched, it's only re-fetched if the listing page hash changes. But detail pages change independently (lottery ends, new sale opens).

3. **No event updates**: The system only adds new events. If an existing event's page changes (new lottery period), a duplicate event may be created or the update may be missed entirely.

Prior work: `_docs/EXECPLAN_logging_and_extraction_improvements.md` implemented logging infrastructure and improved the extraction prompt for CD先行 patterns. Milestone 3 from that plan was moved here due to scope expansion.


## Plan of Work

### Milestone 1: Implement Per-Page Extraction as Default

Change the extraction flow so each detail page is processed independently.

**Current flow in `main.py:fetch_artist_events()`**:

    content = await fetch_source(...)
    # content.relevant_sections contains ALL detail pages combined
    events = extract_events_from_sections(sections=content.relevant_sections, ...)

**New flow**:

    content = await fetch_source(...)
    all_events = []
    for section in content.relevant_sections:
        if section.startswith("=== Detail Page:"):
            # Extract URL from section header
            url = parse_detail_url(section)
            events = extract_events_from_section(section, artist_name, url, client)
            all_events.extend(events)

This requires creating a new function `extract_events_from_section()` that handles a single section.

**Modifications to `extractor.py`**:

Add a new function `extract_events_from_section()` that takes a single section's content and calls the LLM. This can reuse most of the existing prompt but with less content.

**Logging changes**:

Instead of one `llm_request.json` per source, create `llm_request_{page_index}.json` for each detail page.


### Milestone 2: Track Detail Page URLs in State

Expand `FetchState` to track individual detail pages.

**Modifications to `models.py`**:

Add a new model for tracking detail pages:

    class DetailPageState(BaseModel):
        url: str
        content_hash: str
        last_checked: datetime
        event_date: datetime | None = None  # Stop monitoring after this date

Modify `FetchState`:

    class FetchState(BaseModel):
        last_run: datetime | None = None
        source_hashes: dict[str, str] = Field(default_factory=dict)
        detail_pages: dict[str, DetailPageState] = Field(default_factory=dict)  # NEW
        seen_event_ids: list[str] = Field(default_factory=list)

**Modifications to `main.py`**:

After fetching each detail page, record its URL and content hash in `state.detail_pages`. The key should be the URL (normalized).


### Milestone 3: Detect and Handle Updates to Known Detail Pages

Each run should re-check known detail pages (not just new ones from the listing page).

**Refactor `fetcher.py`** into two stateless functions:

    async def discover_event_urls(
        listing_url: str,
        filter_keywords: list[str] | None = None,
    ) -> list[str]:
        """Fetch listing page and return discovered event detail page URLs."""

    async def fetch_detail_page(url: str) -> tuple[str, str]:
        """Fetch a single detail page. Returns (content, content_hash)."""

**Rewrite `main.py` orchestration**:

The orchestrator handles all state logic:

1. Get known URLs from `state.detail_pages` for this source (filter by `event_date > now`)
2. Discover new URLs from listing page via `discover_event_urls()`
3. Merge: `all_urls = known_urls ∪ new_urls`
4. For each URL in `all_urls`:
   - Fetch via `fetch_detail_page()`
   - Compare hash with `state.detail_pages[url].content_hash`
   - If new or changed → extract events
   - Update `state.detail_pages[url]` with new hash and timestamp
5. Save state after processing all sources


### Milestone 4: Add Ended Flag and Event Update Logic

**Modifications to `models.py:Event`**:

Add `ended` field:

    class Event(BaseModel):
        ...
        ended: bool = Field(default=False, description="True if event has passed or action window closed")

**Modifications to `main.py:save_events()`**:

Change from "add only new events" to "update existing events":

1. Match events by a stable ID (URL-based or `artist|title|date` signature)
2. If match found, update fields (except historical metadata like `extracted_at`)
3. If no match, add as new event

**Automatic ended detection**:

When loading events, check if `date < now` and set `ended = True`.

Alternatively, when a detail page shows lottery as 受付終了 (ended), the extraction should detect this. This may require prompt additions.


## Concrete Steps

### Milestone 1: Per-Page Extraction

**Step 1.1: Create extract_events_from_section() in extractor.py**

In `src/nsyc_fetch/extractor.py`, add a new function:

    def extract_events_from_section(
        section: str,
        artist_name: str,
        source_url: str,
        client: OpenAI,
        source_id: str,
        page_index: int = 0,
    ) -> list[Event] | None:
        """Extract events from a single section (detail page).

        Returns list of events, empty list if none found, None if extraction failed.
        """

This function should:
- Build the prompt with just this section's content
- Call the LLM
- Parse the response
- Log request/response with page_index in filename

**Step 1.2: Modify fetch_artist_events() to use per-page extraction**

In `src/nsyc_fetch/main.py`, change the extraction loop:

    # OLD: Single extraction call
    # events = extract_events_from_sections(sections=content.relevant_sections, ...)

    # NEW: Per-page extraction
    all_events = []
    page_index = 0
    for section in content.relevant_sections:
        if section.startswith("=== Detail Page:"):
            events = extract_events_from_section(
                section=section,
                artist_name=artist_name,
                source_url=url,
                client=openai_client,
                source_id=source_id,
                page_index=page_index,
            )
            if events:
                all_events.extend(events)
            page_index += 1

**Step 1.3: Update logger to handle per-page logging**

Modify logger methods to accept optional `page_index` parameter and create files like `llm_request_0.json`, `llm_request_1.json`, etc.

**Step 1.4: Verify per-page extraction works**

Run:

    uv run nsyc-fetch --force

Check logs directory for multiple `llm_request_*.json` files per source. Verify events are correctly extracted.


### Milestone 2: Detail Page State Tracking

**Step 2.1: Add DetailPageState model**

In `src/nsyc_fetch/models.py`, add:

    class DetailPageState(BaseModel):
        url: str
        content_hash: str
        last_checked: datetime
        event_date: datetime | None = None

**Step 2.2: Update FetchState model**

In `src/nsyc_fetch/models.py`, modify FetchState:

    class FetchState(BaseModel):
        last_run: datetime | None = None
        source_hashes: dict[str, str] = Field(default_factory=dict)
        detail_pages: dict[str, DetailPageState] = Field(default_factory=dict)
        seen_event_ids: list[str] = Field(default_factory=list)

**Step 2.3: Record detail page state after extraction**

In `src/nsyc_fetch/main.py`, after extracting from a detail page:

    # After successful extraction
    state.detail_pages[detail_url] = DetailPageState(
        url=detail_url,
        content_hash=page_hash,
        last_checked=datetime.now(),
        event_date=max_event_date,  # Latest event date from this page
    )

**Step 2.4: Verify state tracking**

Run `uv run nsyc-fetch --force` and check `state.json` for `detail_pages` entries.


### Milestone 3: Update Detection

**Step 3.1: Create fetch_known_detail_pages() function**

In `src/nsyc_fetch/fetcher.py`, add function to fetch known pages and detect changes.

**Step 3.2: Modify fetch flow to check known pages**

In `main.py`, before processing a source:
1. Get known detail pages for this source from state
2. Fetch both known pages and new pages from listing
3. For each page, compare hash and re-extract if changed

**Step 3.3: Verify update detection**

Manually modify a cached detail page's hash in `state.json`, then run without --force. The page should be re-fetched and re-extracted.


### Milestone 4: Ended Flag and Event Updates

**Step 4.1: Add ended field to Event model**

In `models.py`:

    ended: bool = Field(default=False, description="True if event has passed")

**Step 4.2: Modify save_events() for update logic**

Change from "add only" to "upsert" logic matching on event signature.

**Step 4.3: Add automatic ended detection**

When loading events or during extraction, check event dates and update `ended` flag.

**Step 4.4: Verify event updates work**

Create a test scenario where an event is extracted, then the source is modified (simulated), and verify the event is updated rather than duplicated.


## Validation and Acceptance

### Milestone 1 Acceptance

After completing Milestone 1:

    uv run nsyc-fetch --force
    ls logs/*/bangdream-events-mygo/

Expected: Multiple `llm_request_*.json` files (one per detail page), not just one.

    cat events.json | python -c "import json,sys; print(len(json.load(sys.stdin)))"

Expected: Same or more events as before (no regression).


### Milestone 2 Acceptance

After completing Milestone 2:

    cat state.json | python -m json.tool | grep -A5 detail_pages

Expected: Shows tracked detail page URLs with hashes and timestamps.


### Milestone 3 Acceptance

After completing Milestone 3:

1. Run `uv run nsyc-fetch --force` (initial fetch)
2. Run `uv run nsyc-fetch` (should skip unchanged)
3. Edit `state.json` to change one detail page's hash
4. Run `uv run nsyc-fetch` (should re-fetch that specific page)

Expected: Step 4 shows re-extraction for only the modified page.


### Milestone 4 Acceptance

After completing Milestone 4:

    cat events.json | python -c "
    import json, sys
    events = json.load(sys.stdin)
    for e in events:
        print(f\"{e['title']}: ended={e.get('ended', False)}\")
    "

Expected: Past events show `ended=True`, future events show `ended=False`.


## Idempotence and Recovery

All changes are idempotent and recoverable:

- Running `uv run nsyc-fetch` multiple times is safe; unchanged pages are skipped
- State is updated atomically after successful operations
- Failed extractions don't update state, ensuring retry on next run
- Event updates are based on stable signatures, preventing duplicates

To reset state:

    rm state.json
    # or just clear detail_pages:
    python -c "import json; s=json.load(open('state.json')); s['detail_pages']={}; json.dump(s, open('state.json','w'), indent=2)"

To reset events:

    rm events.json


## Artifacts and Notes

**Example state.json after Milestone 2:**

    {
      "last_run": "2026-01-02T12:00:00",
      "source_hashes": {
        "bangdream-events-mygo": "abc123"
      },
      "detail_pages": {
        "https://bang-dream.com/events/mygo_9th": {
          "url": "https://bang-dream.com/events/mygo_9th",
          "content_hash": "def456",
          "last_checked": "2026-01-02T12:00:00",
          "event_date": "2026-07-19T00:00:00"
        }
      },
      "seen_event_ids": []
    }

**Example events.json after Milestone 4:**

    [
      {
        "artist": "MyGO!!!!!",
        "event_type": "lottery",
        "title": "MyGO!!!!! 9th LIVE 最速先行抽選",
        "date": "2025-12-06T21:00:00",
        "end_date": "2026-02-02T23:59:00",
        "action_required": true,
        "action_deadline": "2026-02-02T23:59:00",
        "action_description": "Apply using serial code from 8th Single (first-press)",
        "ended": false,
        "source_url": "https://bang-dream.com/events/mygo_9th"
      }
    ]


## Interfaces and Dependencies

### Milestone 1: New extractor function

In `src/nsyc_fetch/extractor.py`:

    def extract_events_from_section(
        section: str,
        artist_name: str,
        source_url: str,
        client: OpenAI,
        source_id: str,
        page_index: int = 0,
    ) -> list[Event] | None:
        """Extract events from a single section."""
        ...

### Milestone 2: New model

In `src/nsyc_fetch/models.py`:

    class DetailPageState(BaseModel):
        url: str
        content_hash: str
        last_checked: datetime
        event_date: datetime | None = None

### Milestone 3: New fetcher function

In `src/nsyc_fetch/fetcher.py`:

    async def fetch_known_detail_pages(
        known_pages: dict[str, DetailPageState],
        current_date: datetime,
    ) -> list[tuple[str, str, bool]]:
        """Fetch known detail pages and detect changes."""
        ...

### Milestone 4: Event model update

In `src/nsyc_fetch/models.py`, add to Event:

    ended: bool = Field(default=False, description="True if event has passed")


---

**Revision Note (2026-01-02):** Created this ExecPlan from design discussion. Milestone 3 from the prior ExecPlan (`_docs/EXECPLAN_logging_and_extraction_improvements.md`) was expanded to include event lifecycle monitoring based on the insight that detail pages change over time (lottery periods end, new sales open). The `extraction_mode` per-source config was removed in favor of per-page extraction as the default behavior.
